# API layer for the Wend cloud-agent feature, packaged as a Lambda
# container image. The Lambda runs the FastAPI app under AWS Lambda Web
# Adapter so it can stream SSE responses through a Function URL with
# InvokeMode = RESPONSE_STREAM. No ALB, no always-on Fargate task, zero
# idle baseline cost.

resource "aws_ecr_repository" "wend_cloud_api" {
  name                 = "wend-cloud-api"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name        = "wend-cloud-api"
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_ecr_lifecycle_policy" "wend_cloud_api" {
  repository = aws_ecr_repository.wend_cloud_api.name

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
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "wend_cloud_api" {
  name              = "/aws/lambda/wend-cloud-api"
  retention_in_days = 14
}

resource "aws_secretsmanager_secret" "clerk_secret_key" {
  name        = "/wend/clerk/secret-key"
  description = "Clerk backend secret key for server-side API calls"
}

resource "aws_secretsmanager_secret_version" "clerk_secret_key" {
  secret_id     = aws_secretsmanager_secret.clerk_secret_key.id
  secret_string = var.clerk_secret_key
}

resource "aws_iam_role" "wend_cloud_api" {
  name = "wend-cloud-api-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "wend_cloud_api_basic" {
  role       = aws_iam_role.wend_cloud_api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "wend_cloud_api_inline" {
  name = "wend-cloud-api-inline"
  role = aws_iam_role.wend_cloud_api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:RunTask",
          "ecs:StopTask",
          "ecs:DescribeTasks",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.wend_agent_task.arn,
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
        ]
        Resource = [
          aws_dynamodb_table.wend_agents.arn,
          "${aws_dynamodb_table.wend_agents.arn}/index/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter",
          "ssm:DeleteParameter",
        ]
        Resource = "arn:aws:ssm:${var.region}:${local.aws_account_id}:parameter/wend/agents/*"
      },
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          "arn:aws:secretsmanager:${var.region}:${local.aws_account_id}:secret:/wend/github-app/*",
          aws_secretsmanager_secret.clerk_secret_key.arn,
        ]
      },
    ]
  })
}

# The actual function and image_uri are deployed by scripts/deploy-api.sh
# after the wend-cloud-api ECR repo exists (chicken-and-egg with the first
# terraform apply: the repo must exist before the image can be pushed, but
# the function needs an image to point at). The function is created here
# with a placeholder image URI; the deploy script overwrites it via
# update-function-code on every push.

resource "aws_lambda_function" "wend_cloud_api" {
  function_name = "wend-cloud-api"
  role          = aws_iam_role.wend_cloud_api.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.wend_cloud_api.repository_url}:${var.wend_agent_image_tag}"
  timeout       = 900
  memory_size   = 1024
  architectures = ["x86_64"]

  environment {
    variables = {
      AWS_LWA_INVOKE_MODE           = "BUFFERED"
      AWS_LWA_READINESS_CHECK_PATH  = "/health"
      AWS_LWA_PORT                  = "8000"
      ECS_CLUSTER_NAME              = "default"
      WEND_AGENT_TASK_DEF           = aws_ecs_task_definition.wend_agent.arn
      WEND_AGENT_TABLE              = aws_dynamodb_table.wend_agents.name
      WEND_AGENT_SG                 = aws_security_group.wend_agent.id
      SUBNET_IDS                    = join(",", local.effective_subnet_ids)
      WEND_AGENT_MAX_CONCURRENT     = tostring(var.wend_agent_max_concurrent_per_user)
      WEND_AGENT_IDLE_TIMEOUT_SEC   = tostring(var.wend_agent_idle_timeout_sec)
      GITHUB_APP_ID                 = var.github_app_id
      GITHUB_APP_PRIVATE_KEY_SECRET = var.github_app_private_key_secret
      CLERK_JWKS_URL                = var.clerk_jwks_url
      CLERK_ISSUER                  = var.clerk_issuer
      CLERK_SECRET_KEY_SECRET       = aws_secretsmanager_secret.clerk_secret_key.name
      AWS_REGION_OVERRIDE           = var.region
    }
  }

  lifecycle {
    # The deploy script (scripts/deploy-api.sh) updates image_uri on every
    # push; ignoring it here prevents terraform from reverting deploys.
    ignore_changes = [image_uri]
  }

  depends_on = [
    aws_cloudwatch_log_group.wend_cloud_api,
  ]
}

resource "aws_lambda_function_url" "wend_cloud_api" {
  function_name      = aws_lambda_function.wend_cloud_api.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "RESPONSE_STREAM"

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    allow_methods     = ["*"]
    allow_headers     = ["authorization", "content-type"]
    max_age           = 600
  }
}

# ECS cluster the wend-agent tasks launch into. Cheaper than a Fargate
# service since this only holds the cluster object; we pay per task.
resource "aws_ecs_cluster" "wend_agents" {
  name = "default"

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = {
    Name        = "wend-agents"
    Environment = var.environment
    Project     = var.project_name
  }
}
