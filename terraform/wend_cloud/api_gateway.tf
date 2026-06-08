# API Gateway HTTP API in front of the Lambda. Replaces the Lambda
# Function URL which is returning 403 on this account despite a correct
# public resource policy. HTTP APIs are cheaper than REST APIs ($1 per
# million requests) and support response streaming via Lambda payload
# format 2.0. Still $0 idle.

resource "aws_apigatewayv2_api" "wend_cloud" {
  name          = "wend-cloud"
  protocol_type = "HTTP"
  description   = "Public ingress for the Wend cloud-agent FastAPI Lambda"

  cors_configuration {
    allow_origins  = ["*"]
    allow_methods  = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_headers  = ["authorization", "content-type"]
    expose_headers = ["content-type"]
    max_age        = 600
  }
}

resource "aws_apigatewayv2_integration" "wend_cloud_api" {
  api_id                 = aws_apigatewayv2_api.wend_cloud.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.wend_cloud_api.arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "any" {
  api_id    = aws_apigatewayv2_api.wend_cloud.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.wend_cloud_api.id}"
}

resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.wend_cloud.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.wend_cloud_api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.wend_cloud.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 100
  }
}

resource "aws_lambda_permission" "wend_cloud_api_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.wend_cloud_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.wend_cloud.execution_arn}/*/*"
}
