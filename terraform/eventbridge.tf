# EventBridge permission for Lambda
# Note: Rules are created dynamically by the backend service
# This resource grants EventBridge permission to invoke the Lambda function

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cleanup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = "arn:aws:events:${var.region}:${var.aws_account_id}:rule/${var.project_name}-*"
}

