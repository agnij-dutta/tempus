#!/bin/bash
set -e

# Quick deployment script for Tempus
# This script automates the deployment process

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Tempus Deployment Script${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

command -v aws >/dev/null 2>&1 || { echo -e "${RED}AWS CLI is required but not installed.${NC}" >&2; exit 1; }
command -v terraform >/dev/null 2>&1 || { echo -e "${RED}Terraform is required but not installed.${NC}" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo -e "${RED}Docker is required but not installed.${NC}" >&2; exit 1; }

# Check AWS credentials
if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo -e "${RED}AWS credentials not configured. Run 'aws configure' first.${NC}" >&2
    exit 1
fi

echo -e "${GREEN}✓ Prerequisites check passed${NC}"
echo ""

# Get AWS account ID and region
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="${AWS_REGION:-ap-south-1}"
PROJECT_NAME="${PROJECT_NAME:-tempus}"

echo "AWS Account ID: $AWS_ACCOUNT_ID"
echo "AWS Region: $AWS_REGION"
echo "Project Name: $PROJECT_NAME"
echo ""

# Step 1: Setup Terraform backend
echo -e "${YELLOW}Step 1: Setting up Terraform backend...${NC}"
cd "$PROJECT_ROOT"
bash scripts/setup.sh
echo ""

# Step 2: Configure Terraform backend
echo -e "${YELLOW}Step 2: Configuring Terraform backend...${NC}"
TERRAFORM_MAIN="$PROJECT_ROOT/terraform/main.tf"
if grep -q "# backend \"s3\"" "$TERRAFORM_MAIN"; then
    echo -e "${YELLOW}Please uncomment and configure the backend in terraform/main.tf${NC}"
    echo "Backend configuration should be:"
    echo "  bucket         = \"${PROJECT_NAME}-terraform-state\""
    echo "  key            = \"terraform.tfstate\""
    echo "  region         = \"${AWS_REGION}\""
    echo "  dynamodb_table = \"${PROJECT_NAME}-terraform-locks\""
    echo ""
    read -p "Press Enter after you've updated terraform/main.tf..."
else
    echo -e "${GREEN}✓ Backend configuration found${NC}"
fi
echo ""

# Step 3: Configure Terraform variables
echo -e "${YELLOW}Step 3: Configuring Terraform variables...${NC}"
TFVARS="$PROJECT_ROOT/terraform/terraform.tfvars"
if [ ! -f "$TFVARS" ]; then
    cp "$PROJECT_ROOT/terraform/terraform.tfvars.example" "$TFVARS"
    echo -e "${GREEN}✓ Created terraform.tfvars from example${NC}"
else
    echo -e "${GREEN}✓ terraform.tfvars already exists${NC}"
fi

# Update region if needed
sed -i.bak "s/^region = .*/region = \"${AWS_REGION}\"/" "$TFVARS" 2>/dev/null || \
sed -i "s/^region = .*/region = \"${AWS_REGION}\"/" "$TFVARS"
rm -f "${TFVARS}.bak" 2>/dev/null || true

echo ""

# Step 4: Initialize Terraform
echo -e "${YELLOW}Step 4: Initializing Terraform...${NC}"
cd "$PROJECT_ROOT/terraform"
terraform init
echo ""

# Step 5: Deploy infrastructure (first pass - creates ECR)
echo -e "${YELLOW}Step 5: Deploying infrastructure (creating ECR repository)...${NC}"
echo "This will create the ECR repository and other infrastructure."
read -p "Do you want to proceed? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Deployment cancelled."
    exit 0
fi

terraform plan
read -p "Review the plan above. Apply changes? (yes/no): " -r
if [[ $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    terraform apply -auto-approve
    echo -e "${GREEN}✓ Infrastructure deployed${NC}"
else
    echo "Deployment cancelled."
    exit 0
fi
echo ""

# Step 6: Build and push Docker image
echo -e "${YELLOW}Step 6: Building and pushing Docker image...${NC}"
cd "$PROJECT_ROOT"
export AWS_REGION
export PROJECT_NAME
bash scripts/build_and_push.sh

# Extract ECR URI from output
ECR_URI=$(bash scripts/build_and_push.sh 2>&1 | grep "ECR Image URI:" | awk '{print $4}' || echo "")
if [ -z "$ECR_URI" ]; then
    # Try alternative method
    ECR_REPO="${PROJECT_NAME}-backend"
    ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:latest"
fi

echo ""
echo -e "${GREEN}✓ Docker image pushed${NC}"
echo "ECR Image URI: $ECR_URI"
echo ""

# Step 7: Update Terraform variables with container image
echo -e "${YELLOW}Step 7: Updating Terraform variables with container image...${NC}"
if [ -n "$ECR_URI" ]; then
    # Update terraform.tfvars
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|^container_image = .*|container_image = \"${ECR_URI}\"|" "$TFVARS"
    else
        # Linux
        sed -i "s|^container_image = .*|container_image = \"${ECR_URI}\"|" "$TFVARS"
    fi
    echo -e "${GREEN}✓ Updated terraform.tfvars with container image${NC}"
else
    echo -e "${YELLOW}⚠ Could not extract ECR URI. Please update terraform.tfvars manually:${NC}"
    echo "  container_image = \"<your-ecr-uri>\""
    read -p "Press Enter after updating terraform.tfvars..."
fi
echo ""

# Step 8: Update infrastructure with container image
echo -e "${YELLOW}Step 8: Updating infrastructure with container image...${NC}"
cd "$PROJECT_ROOT/terraform"
terraform plan
read -p "Review the plan above. Apply changes? (yes/no): " -r
if [[ $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    terraform apply -auto-approve
    echo -e "${GREEN}✓ Infrastructure updated with container image${NC}"
else
    echo "Update cancelled. You can run 'terraform apply' later."
fi
echo ""

# Step 9: Display outputs
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Terraform outputs:"
terraform output
echo ""

# Get ALB DNS name
ALB_DNS=$(terraform output -raw alb_dns_name 2>/dev/null || echo "")
if [ -n "$ALB_DNS" ]; then
    echo ""
    echo -e "${GREEN}Test the deployment:${NC}"
    echo "  Health check: curl http://${ALB_DNS}/health"
    echo "  Create preview: curl -X POST http://${ALB_DNS}/preview/create \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -d '{\"ttl_hours\": 2}'"
    echo ""
fi

echo -e "${YELLOW}Note:${NC} The backend service needs to be deployed separately."
echo "The backend service requires these environment variables:"
echo "  - ECS_CLUSTER_NAME"
echo "  - ALB_ARN"
echo "  - ALB_LISTENER_ARN"
echo "  - TASK_EXECUTION_ROLE_ARN"
echo "  - TASK_ROLE_ARN"
echo "  - ECS_SECURITY_GROUP_ID"
echo "  - SUBNET_IDS"
echo "  - CONTAINER_IMAGE"
echo "  - DYNAMODB_TABLE_NAME"
echo "  - LAMBDA_CLEANUP_ARN"
echo "  - ALB_DNS_NAME"
echo "  - LOG_GROUP_NAME"
echo "  - AWS_REGION"
echo ""
echo "You can get these values from 'terraform output' and AWS console."

