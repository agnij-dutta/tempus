# Backend ECS task definition
resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.project_name}-backend"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.container_image
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ecs"
        }
      }
      environment = [
        { name = "AWS_REGION", value = var.region },
        { name = "ECS_CLUSTER_NAME", value = aws_ecs_cluster.main.name },
        { name = "ALB_ARN", value = aws_lb.main.arn },
        { name = "ALB_LISTENER_ARN", value = aws_lb_listener.main.arn },
        { name = "TASK_EXECUTION_ROLE_ARN", value = aws_iam_role.ecs_task_execution.arn },
        { name = "TASK_ROLE_ARN", value = aws_iam_role.ecs_task.arn },
        { name = "ECS_SECURITY_GROUP_ID", value = aws_security_group.ecs.id },
        { name = "SUBNET_IDS", value = join(",", data.aws_subnets.main.ids) },
        { name = "CONTAINER_IMAGE", value = var.container_image },
        { name = "DYNAMODB_TABLE_NAME", value = aws_dynamodb_table.previews.name },
        { name = "LAMBDA_CLEANUP_ARN", value = aws_lambda_function.cleanup.arn },
        { name = "ALB_DNS_NAME", value = aws_lb.main.dns_name },
        { name = "LOG_GROUP_NAME", value = aws_cloudwatch_log_group.ecs.name }
      ]
    }
  ])
}

# Backend ECS service (always-on API)
resource "aws_ecs_service" "backend" {
  name            = "${var.project_name}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = data.aws_subnets.main.ids
    security_groups = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.default.arn
    container_name   = "backend"
    container_port   = 8000
  }

  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.main]
}

