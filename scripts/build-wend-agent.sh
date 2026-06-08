#!/usr/bin/env bash
# Build and push the wend-agent container image used by ephemeral ECS
# tasks. Run once after the first terraform apply, then again on every
# wend-agent/ change.
set -euo pipefail

cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-us-east-1}"
TAG="${WEND_AGENT_TAG:-latest}"

ECR_URL=$(terraform -chdir=terraform/wend_cloud output -raw wend_agent_ecr_repository_url)
ACCOUNT_ID=$(echo "$ECR_URL" | cut -d. -f1)

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"

docker build --platform linux/amd64 -t "wend-agent:$TAG" wend-agent/
docker tag "wend-agent:$TAG" "$ECR_URL:$TAG"
docker push "$ECR_URL:$TAG"

echo "✓ pushed $ECR_URL:$TAG"
