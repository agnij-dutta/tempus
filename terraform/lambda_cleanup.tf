# Build Lambda package
resource "null_resource" "lambda_build" {
  triggers = {
    cleanup_py = filemd5("${path.module}/../lambda/cleanup/cleanup.py")
    requirements_txt = filemd5("${path.module}/../lambda/cleanup/requirements.txt")
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/../lambda/build.sh"
  }
}

data "archive_file" "lambda_cleanup" {
  type        = "zip"
  source_file = "${path.module}/../lambda/cleanup/cleanup.py"
  output_path = "${path.module}/../lambda/cleanup.zip"
  depends_on  = [null_resource.lambda_build]
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "lambda_cleanup" {
  name              = "/aws/lambda/${var.project_name}-cleanup"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-lambda-cleanup-logs"
    Environment = var.environment
    Project     = var.project_name
  }
}

# Lambda function
resource "aws_lambda_function" "cleanup" {
  filename         = data.archive_file.lambda_cleanup.output_path
  function_name    = "${var.project_name}-cleanup"
  role            = aws_iam_role.lambda_cleanup.arn
  handler         = "cleanup.handler"
  runtime         = "python3.11"
  timeout         = 300  # 5 minutes
  memory_size     = 256

  source_code_hash = data.archive_file.lambda_cleanup.output_base64sha256

  environment {
    variables = {
      AWS_REGION         = var.region
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.previews.name
      ECS_CLUSTER_NAME   = aws_ecs_cluster.main.name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_cleanup,
    aws_iam_role_policy.lambda_cleanup
  ]

  tags = {
    Name        = "${var.project_name}-cleanup"
    Environment = var.environment
    Project     = var.project_name
  }
}

