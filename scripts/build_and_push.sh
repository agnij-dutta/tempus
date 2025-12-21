#!/bin/bash
set -e

# Script to build Docker image and push to ECR

REGION="${AWS_REGION:-ap-south-1}"
PROJECT_NAME="${PROJECT_NAME:-tempus}"
ECR_REPO="${ECR_REPO:-${PROJECT_NAME}-backend}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"

echo "Building Docker image..."
echo "Region: $REGION"
echo "ECR Repository: $ECR_REPO"
echo "Image Tag: $IMAGE_TAG"
echo "ECR URI: $ECR_URI"

# Build Docker image
cd "$(dirname "$0")/../backend"
docker build -t "${ECR_REPO}:${IMAGE_TAG}" .
docker tag "${ECR_REPO}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"

# Login to ECR
echo "Logging in to ECR..."
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

# Push image
echo "Pushing image to ECR..."
docker push "${ECR_URI}:${IMAGE_TAG}"

echo ""
echo "Image pushed successfully!"
echo "ECR Image URI: ${ECR_URI}:${IMAGE_TAG}"
echo ""
echo "Update terraform/terraform.tfvars with:"
echo "  container_image = \"${ECR_URI}:${IMAGE_TAG}\""

