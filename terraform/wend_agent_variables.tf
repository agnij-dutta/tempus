variable "wend_agent_image_tag" {
  description = "ECR image tag for the wend-agent container"
  type        = string
  default     = "latest"
}

variable "wend_agent_max_concurrent_per_user" {
  description = "Max simultaneous wend-agent tasks per Clerk user; enforced via DynamoDB conditional writes in the FastAPI provisioner"
  type        = number
  default     = 2
}

variable "wend_agent_idle_timeout_sec" {
  description = "Seconds of HTTP-request inactivity before the container watchdog exits; mirrors the mobile UI session idle threshold"
  type        = number
  default     = 900
}
