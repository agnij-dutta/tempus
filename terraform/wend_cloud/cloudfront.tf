# CloudFront distribution in front of the Lambda Function URL.
#
# Why: the Function URL with AuthType=NONE returns 403 AccessDeniedException
# on this AWS account (unresolved AWS-side quirk). Putting CloudFront in
# front with Origin Access Control lets us authenticate the origin
# request via SigV4 while keeping CloudFront's edge endpoint public.
# Bonus: response streaming works end-to-end (the API Gateway path
# forces BUFFERED mode and breaks SSE).

resource "aws_cloudfront_origin_access_control" "wend_cloud_api" {
  name                              = "wend-cloud-api-oac"
  description                       = "OAC for signing CloudFront → Lambda Function URL requests"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Strip the protocol + trailing slash from the Function URL so CloudFront
# gets a bare hostname like "xyz.lambda-url.us-east-1.on.aws".
locals {
  function_url_host = replace(
    replace(aws_lambda_function_url.wend_cloud_api.function_url, "https://", ""),
    "/",
    "",
  )
}

resource "aws_cloudfront_distribution" "wend_cloud_api" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "wend-cloud public API edge"
  price_class     = "PriceClass_100" # US + EU edges; cheapest tier

  origin {
    domain_name              = local.function_url_host
    origin_id                = "lambda-function-url"
    origin_access_control_id = aws_cloudfront_origin_access_control.wend_cloud_api.id

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "lambda-function-url"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # No caching — every request is per-user, dynamic, and many are SSE
    # streams that must not be cached.
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name        = "wend-cloud-api"
    Environment = var.environment
    Project     = var.project_name
  }
}

# Allow this CloudFront distribution (and only this one) to invoke the
# Function URL via SigV4 from its OAC.
resource "aws_lambda_permission" "wend_cloud_api_cloudfront" {
  statement_id           = "AllowCloudFrontOACInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.wend_cloud_api.function_name
  principal              = "cloudfront.amazonaws.com"
  function_url_auth_type = "AWS_IAM"
}
