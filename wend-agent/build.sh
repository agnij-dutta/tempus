#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

TAG="${WEND_AGENT_TAG:-dev}"
docker build -t "wend-agent:${TAG}" .

if [[ -n "${AWS_ACCOUNT_ID:-}" && -n "${AWS_REGION:-}" ]]; then
  REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/wend-agent"
  aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin "${REPO}"
  docker tag "wend-agent:${TAG}" "${REPO}:${TAG}"
  docker push "${REPO}:${TAG}"
  echo "pushed ${REPO}:${TAG}"
else
  echo "set AWS_ACCOUNT_ID and AWS_REGION to push to ECR"
fi
