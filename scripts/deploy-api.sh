#!/usr/bin/env bash
#
# Build the wend-cloud-api Lambda container image, push to ECR, and
# point the Lambda function at the new image. Run after every backend
# change.
#
# Requires:
#   - AWS CLI configured for the same account terraform deployed into
#   - Docker daemon running
#   - terraform/wend_cloud/ already applied (provides the ECR repo)

set -euo pipefail

cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-us-east-1}"
TAG="${WEND_API_TAG:-latest}"

echo "→ resolving ECR repo URL from terraform output"
ECR_URL=$(terraform -chdir=terraform/wend_cloud output -raw api_ecr_repository_url)
ACCOUNT_ID=$(echo "$ECR_URL" | cut -d. -f1)

echo "→ logging in to ECR ($ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com)"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

echo "→ building image"
docker build --provenance=false --platform linux/amd64 -t "wend-cloud-api:$TAG" -f backend/Dockerfile.lambda backend/

echo "→ tagging and pushing"
docker tag "wend-cloud-api:$TAG" "$ECR_URL:$TAG"
docker push "$ECR_URL:$TAG"

echo "→ updating Lambda function code"
aws lambda update-function-code \
  --function-name wend-cloud-api \
  --image-uri "$ECR_URL:$TAG" \
  --region "$REGION" \
  --no-cli-pager > /dev/null

aws lambda wait function-updated --function-name wend-cloud-api --region "$REGION"

URL=$(terraform -chdir=terraform/wend_cloud output -raw api_function_url)
echo "✓ deployed. API URL: $URL"
