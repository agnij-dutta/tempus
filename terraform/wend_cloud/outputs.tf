output "api_function_url" {
  description = "Public Lambda Function URL for the wend-cloud API"
  value       = aws_lambda_function_url.wend_cloud_api.function_url
}

output "api_ecr_repository_url" {
  description = "ECR repo for the wend-cloud-api Lambda container image"
  value       = aws_ecr_repository.wend_cloud_api.repository_url
}

output "wend_agent_ecr_repository_url" {
  description = "ECR repo for the wend-agent container image"
  value       = aws_ecr_repository.wend_agent.repository_url
}

output "wend_agent_task_definition_arn" {
  description = "ECS task definition ARN to RunTask against"
  value       = aws_ecs_task_definition.wend_agent.arn
}

output "wend_agent_table_name" {
  description = "DynamoDB table name for per-agent metadata"
  value       = aws_dynamodb_table.wend_agents.name
}

output "wend_agent_security_group_id" {
  description = "Security group with allowlisted egress for wend-agent tasks"
  value       = aws_security_group.wend_agent.id
}

output "wend_agent_log_group_name" {
  description = "CloudWatch log group for wend-agent container output"
  value       = aws_cloudwatch_log_group.wend_agent.name
}

output "subnet_ids" {
  description = "Subnets the wend-agent tasks are launched into"
  value       = local.effective_subnet_ids
}
