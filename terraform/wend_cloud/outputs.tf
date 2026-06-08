output "api_function_url" {
  description = "Lambda Function URL (kept as fallback; the canonical public ingress is api_url)"
  value       = aws_lambda_function_url.wend_cloud_api.function_url
}

output "api_url" {
  description = "Public API Gateway HTTP API URL — fallback ingress (BUFFERED responses, no SSE streaming)"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_cdn_url" {
  description = "Public CloudFront URL — canonical ingress with SSE streaming"
  value       = "https://${aws_cloudfront_distribution.wend_cloud_api.domain_name}"
}

output "ws_url" {
  description = "WebSocket URL for real-time cloud-dispatch streaming"
  value       = "wss://${aws_apigatewayv2_api.wend_cloud_ws.id}.execute-api.${var.region}.amazonaws.com/${aws_apigatewayv2_stage.wend_cloud_ws.name}"
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
