# wend-runs — durable per-dispatch result store.
#
# Container writes one row when claude exits, regardless of whether the
# user's phone was still connected. Phone fetches via GET /v1/runs?noteId=X
# on note open to reconcile any runs that completed while it was closed.

resource "aws_dynamodb_table" "wend_runs" {
  name         = "wend-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "noteId"
  range_key    = "createdAt"

  attribute {
    name = "noteId"
    type = "S"
  }
  attribute {
    name = "createdAt"
    type = "N"
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
    Name        = "wend-runs"
    Environment = var.environment
    Project     = var.project_name
  }
}
