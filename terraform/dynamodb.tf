resource "aws_dynamodb_table" "previews" {
  name         = "${var.project_name}-previews"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "preview_id"

  attribute {
    name = "preview_id"
    type = "S"
  }

  attribute {
    name = "expires_at"
    type = "S"
  }

  # Global Secondary Index for querying by expiration time
  global_secondary_index {
    name            = "expires_at-index"
    hash_key        = "expires_at"
    projection_type = "ALL"
  }

  # Enable TTL for automatic cleanup (optional, we use EventBridge)
  ttl {
    attribute_name = "expires_at"
    enabled        = false  # Disabled since we use EventBridge for cleanup
  }

  # Point-in-time recovery for data protection
  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name        = "${var.project_name}-previews"
    Environment = var.environment
    Project     = var.project_name
  }
}

