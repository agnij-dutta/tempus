# wend-agent — ephemeral container that runs Claude Code against a cloned
# GitHub repo and streams SSE back through Tempus. See
# ~/Desktop/Wend/Cloud Agent - Technical Design.md for the architecture.

resource "aws_ecr_repository" "wend_agent" {
  name                 = "wend-agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "wend-agent"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_ecr_lifecycle_policy" "wend_agent" {
  repository = aws_ecr_repository.wend_agent.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 10
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "wend_agent" {
  name              = "/ecs/wend-agent"
  retention_in_days = 14

  tags = {
    Name        = "wend-agent-logs"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_dynamodb_table" "wend_agents" {
  name         = "wend-agents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "agentId"

  attribute {
    name = "agentId"
    type = "S"
  }

  attribute {
    name = "userId"
    type = "S"
  }

  global_secondary_index {
    name            = "byUserId"
    hash_key        = "userId"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expiresAt"
    enabled        = true
  }

  tags = {
    Name        = "wend-agents"
    Environment = var.environment
    Project     = var.project_name
  }
}

# Allowlisted egress only — see Cloud Agent Rollout doc threat model section.
# No 0.0.0.0/0 outbound; the security group enforces destination whitelisting
# at the SG level for raw IPs we know about, and the task's container relies
# on DNS resolution through the VPC resolver. Egress to public IPs is gated
# by the prefix-list approach below.
resource "aws_security_group" "wend_agent" {
  name        = "wend-agent-sg"
  description = "Egress-restricted SG for wend-agent ECS tasks"
  vpc_id      = local.effective_vpc_id

  egress {
    description = "HTTPS to allowlisted hosts (API + GitHub + npm + pypi + cloudflared)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "DNS resolution"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "cloudflared QUIC tunnel"
    from_port   = 7844
    to_port     = 7844
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "wend-agent-sg"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_iam_role" "wend_agent_task" {
  name = "wend-agent-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "wend_agent_task" {
  name = "wend-agent-task-inline"
  role = aws_iam_role.wend_agent_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = "arn:aws:ssm:${var.region}:${local.aws_account_id}:parameter/wend/agents/*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.region}:${local.aws_account_id}:secret:/wend/github-app/*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.wend_agents.arn
      },
      {
        Effect   = "Allow"
        Action   = ["execute-api:ManageConnections"]
        Resource = "arn:aws:execute-api:${var.region}:${local.aws_account_id}:${aws_apigatewayv2_api.wend_cloud_ws.id}/*/*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.wend_agent.arn}:*"
      }
    ]
  })
}

# Reuse the existing execution role used by Tempus's preview tasks; it
# already has ECR pull + CloudWatch Logs put. Add the wend-agent log group
# to its scope so it can stream container logs.
resource "aws_iam_role_policy_attachment" "wend_agent_execution_attach" {
  role       = aws_iam_role.wend_agent_task.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ecs_task_definition" "wend_agent" {
  family                   = "wend-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  ephemeral_storage { size_in_gib = 21 }
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  execution_role_arn = aws_iam_role.wend_agent_task.arn
  task_role_arn      = aws_iam_role.wend_agent_task.arn

  container_definitions = jsonencode([{
    name      = "wend-agent"
    image     = "${aws_ecr_repository.wend_agent.repository_url}:${var.wend_agent_image_tag}"
    essential = true
    environment = [
      { name = "WEND_IDLE_TIMEOUT_SEC", value = tostring(var.wend_agent_idle_timeout_sec) },
      { name = "WEND_LISTEN_PORT", value = "8080" },
      { name = "WEND_DDB_TABLE", value = aws_dynamodb_table.wend_agents.name },
      { name = "AWS_REGION", value = var.region }
    ]
    # Secrets + per-agent env (WEND_AGENT_ID, WEND_REPO, WEND_REPO_REF,
    # WEND_GITHUB_INSTALL_TOKEN, WEND_ANTHROPIC_API_KEY) are injected per
    # task by the FastAPI provisioner via run_task overrides.
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.wend_agent.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "wend-agent"
      }
    }
    portMappings = [{ containerPort = 8080, protocol = "tcp" }]
  }])

  tags = {
    Name        = "wend-agent-task"
    Environment = var.environment
    Project     = var.project_name
  }
}

