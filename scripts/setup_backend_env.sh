#!/bin/bash
# Script to set up environment variables for running the backend service locally

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/../terraform"

if [ ! -d "$TERRAFORM_DIR" ]; then
    echo "Error: terraform directory not found"
    exit 1
fi

cd "$TERRAFORM_DIR"

# Check if terraform has been initialized
if [ ! -f "terraform.tfstate" ] && [ ! -f ".terraform/terraform.tfstate" ]; then
    echo "Error: Terraform state not found. Please deploy infrastructure first."
    exit 1
fi

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(terraform output -raw region 2>/dev/null || echo "ap-south-1")

echo "# Backend Environment Variables"
echo "# Copy these to your shell or save to a .env file"
echo ""
echo "export AWS_REGION=\"${AWS_REGION}\""
echo "export ECS_CLUSTER_NAME=\"$(terraform output -raw ecs_cluster_name)\""
echo "export ALB_ARN=\"$(terraform output -raw alb_arn)\""

# Get ALB listener ARN
ALB_ARN=$(terraform output -raw alb_arn)
ALB_LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" --query 'Listeners[0].ListenerArn' --output text 2>/dev/null)
if [ -n "$ALB_LISTENER_ARN" ] && [ "$ALB_LISTENER_ARN" != "None" ]; then
    echo "export ALB_LISTENER_ARN=\"${ALB_LISTENER_ARN}\""
else
    echo "# ALB_LISTENER_ARN - Get manually: aws elbv2 describe-listeners --load-balancer-arn <alb-arn>"
fi

echo "export TASK_EXECUTION_ROLE_ARN=\"arn:aws:iam::${AWS_ACCOUNT_ID}:role/tempus-ecs-task-execution\""
echo "export TASK_ROLE_ARN=\"arn:aws:iam::${AWS_ACCOUNT_ID}:role/tempus-ecs-task\""

# Get ECS security group
ECS_SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=tempus-ecs*" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
if [ -n "$ECS_SG" ] && [ "$ECS_SG" != "None" ]; then
    echo "export ECS_SECURITY_GROUP_ID=\"${ECS_SG}\""
else
    echo "# ECS_SECURITY_GROUP_ID - Get manually: aws ec2 describe-security-groups --filters 'Name=group-name,Values=tempus-ecs*'"
fi

# Get subnet IDs
SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=default-for-az,Values=true" --query 'Subnets[*].SubnetId' --output text 2>/dev/null | tr '\t' ',')
if [ -n "$SUBNET_IDS" ] && [ "$SUBNET_IDS" != "None" ]; then
    echo "export SUBNET_IDS=\"${SUBNET_IDS}\""
else
    echo "# SUBNET_IDS - Get manually: aws ec2 describe-subnets --filters 'Name=default-for-az,Values=true'"
fi

# Get ECR repository URL
ECR_REPO=$(terraform output -raw ecr_repository_url 2>/dev/null)
if [ -n "$ECR_REPO" ]; then
    echo "export CONTAINER_IMAGE=\"${ECR_REPO}:latest\""
else
    echo "# CONTAINER_IMAGE - Set to your ECR image URI"
fi

echo "export DYNAMODB_TABLE_NAME=\"$(terraform output -raw dynamodb_table_name)\""
echo "export LAMBDA_CLEANUP_ARN=\"$(terraform output -raw lambda_cleanup_function_arn)\""
echo "export ALB_DNS_NAME=\"$(terraform output -raw alb_dns_name)\""
echo "export LOG_GROUP_NAME=\"/ecs/tempus\""
echo ""
echo "# To use these variables, run:"
echo "#   source <(bash scripts/setup_backend_env.sh)"
echo "# Or save to a file:"
echo "#   bash scripts/setup_backend_env.sh > .env"
echo "#   source .env"

