variable "region" {
  description = "AWS region for the wend-cloud stack"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Used for tagging"
  type        = string
  default     = "wend-cloud"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "alpha"
}

variable "vpc_id" {
  description = "VPC ID (empty uses the account's default VPC)"
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "Subnet IDs (empty uses every default subnet in the default VPC)"
  type        = list(string)
  default     = []
}

variable "wend_agent_image_tag" {
  description = "ECR image tag for the wend-agent container"
  type        = string
  default     = "latest"
}

variable "wend_agent_max_concurrent_per_user" {
  description = "Max simultaneous wend-agent tasks per Clerk user; enforced via DynamoDB conditional writes in the API"
  type        = number
  default     = 2
}

variable "wend_agent_idle_timeout_sec" {
  description = "Seconds of HTTP-request inactivity before the container watchdog exits"
  type        = number
  default     = 900
}

variable "github_app_id" {
  description = "GitHub App ID (mints installation tokens for repo clones)"
  type        = string
  default     = "3994863"
}

variable "github_app_private_key_secret" {
  description = "Secrets Manager name for the GitHub App PEM"
  type        = string
  default     = "/wend/github-app/private-key"
}

variable "clerk_jwks_url" {
  description = "Clerk JWKS endpoint for token validation"
  type        = string
}

variable "clerk_issuer" {
  description = "Clerk issuer URL"
  type        = string
}

variable "clerk_secret_key" {
  description = "Clerk backend secret key for server-side API calls; stored in Secrets Manager"
  type        = string
  sensitive   = true
}
