#!/bin/bash
set -e

# Script to run the FastAPI application locally for testing
# This uses mocked AWS services or requires AWS credentials

echo "Starting local FastAPI server..."
echo ""
echo "Note: This requires AWS credentials configured or mocked services"
echo "The API will be available at http://localhost:8000"
echo ""

cd "$(dirname "$0")/../backend"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# Set environment variables for local testing
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export ECS_CLUSTER_NAME="tempus-cluster"
export ALB_ARN="arn:aws:elasticloadbalancing:${AWS_REGION}:123456789012:loadbalancer/app/test-alb/1234567890123456"
export ALB_LISTENER_ARN="arn:aws:elasticloadbalancing:${AWS_REGION}:123456789012:listener/app/test-alb/1234567890123456/1234567890123456"
export ALB_DNS_NAME="test-alb-1234567890.us-east-1.elb.amazonaws.com"
export TASK_EXECUTION_ROLE_ARN="arn:aws:iam::123456789012:role/tempus-ecs-task-execution"
export TASK_ROLE_ARN="arn:aws:iam::123456789012:role/tempus-ecs-task"
export ECS_SECURITY_GROUP_ID="sg-12345678"
export SUBNET_IDS="subnet-12345678,subnet-87654321"
export CONTAINER_IMAGE="123456789012.dkr.ecr.ap-south-1.amazonaws.com/tempus-backend:latest"
export DYNAMODB_TABLE_NAME="tempus-previews"
export LAMBDA_CLEANUP_ARN="arn:aws:lambda:${AWS_REGION}:123456789012:function:tempus-cleanup"
export LOG_GROUP_NAME="/ecs/tempus"

echo ""
echo "Starting server..."
echo "API Documentation: http://localhost:8000/docs"
echo "Health Check: http://localhost:8000/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

