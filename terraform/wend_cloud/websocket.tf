# WebSocket API for real-time cloud-dispatch streaming.
#
# Why: API Gateway HTTP API does not forward Lambda response streaming
# (forces BUFFERED), and Function URLs with response streaming return
# 403 on this account. WebSocket gives genuine bidirectional streaming
# with no Function URL dependency.
#
# Wire model: phone opens a WS connection, authenticates via Clerk JWT
# in the connect query string, sends a `dispatch` message; the Lambda
# provisions the ECS agent with the connectionId in env; the container
# pushes each SSE event back via ApiGatewayManagementApi.PostToConnection
# to that same connection. Phone receives messages and parses them
# identically to SSE frames.

resource "aws_apigatewayv2_api" "wend_cloud_ws" {
  name                       = "wend-cloud-ws"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
  description                = "Real-time streaming for Wend cloud-agent dispatches"
}

resource "aws_apigatewayv2_integration" "wend_cloud_ws_default" {
  api_id                    = aws_apigatewayv2_api.wend_cloud_ws.id
  integration_type          = "AWS_PROXY"
  integration_uri           = aws_lambda_function.wend_cloud_api.invoke_arn
  integration_method        = "POST"
  content_handling_strategy = "CONVERT_TO_TEXT"
  passthrough_behavior      = "WHEN_NO_MATCH"
}

resource "aws_apigatewayv2_route" "ws_connect" {
  api_id    = aws_apigatewayv2_api.wend_cloud_ws.id
  route_key = "$connect"
  target    = "integrations/${aws_apigatewayv2_integration.wend_cloud_ws_default.id}"
}

resource "aws_apigatewayv2_route" "ws_disconnect" {
  api_id    = aws_apigatewayv2_api.wend_cloud_ws.id
  route_key = "$disconnect"
  target    = "integrations/${aws_apigatewayv2_integration.wend_cloud_ws_default.id}"
}

resource "aws_apigatewayv2_route" "ws_default" {
  api_id    = aws_apigatewayv2_api.wend_cloud_ws.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.wend_cloud_ws_default.id}"
}

resource "aws_apigatewayv2_route" "ws_dispatch" {
  api_id    = aws_apigatewayv2_api.wend_cloud_ws.id
  route_key = "dispatch"
  target    = "integrations/${aws_apigatewayv2_integration.wend_cloud_ws_default.id}"
}

resource "aws_apigatewayv2_route" "ws_abort" {
  api_id    = aws_apigatewayv2_api.wend_cloud_ws.id
  route_key = "abort"
  target    = "integrations/${aws_apigatewayv2_integration.wend_cloud_ws_default.id}"
}

resource "aws_apigatewayv2_stage" "wend_cloud_ws" {
  api_id      = aws_apigatewayv2_api.wend_cloud_ws.id
  name        = "prod"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 100
  }
}

resource "aws_lambda_permission" "wend_cloud_api_ws" {
  statement_id  = "AllowWebSocketAPIInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.wend_cloud_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.wend_cloud_ws.execution_arn}/*/*"
}

# DynamoDB table mapping connectionId → userId (+ created_at for TTL).
# Lives separately from wend-agents because the lifecycle is different
# (connection survives across dispatches; agent rows tie to one dispatch).
resource "aws_dynamodb_table" "wend_ws_connections" {
  name         = "wend-ws-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
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
    Name        = "wend-ws-connections"
    Environment = var.environment
    Project     = var.project_name
  }
}
