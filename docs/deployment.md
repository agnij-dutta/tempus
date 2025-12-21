# Deployment Guide - Tempus Ephemeral Preview Environment

This guide walks you through deploying the Tempus ephemeral preview environment generator to AWS.

## Quick Start

For a fully automated deployment, use the quick deploy script:

```bash
bash scripts/quick_deploy.sh
```

This script will:
1. Check prerequisites
2. Set up Terraform backend (S3 + DynamoDB)
3. Deploy infrastructure
4. Build and push Docker image
5. Update infrastructure with container image

**Manual Deployment**: Follow the step-by-step guide below for more control.

## Prerequisites Checklist

Before starting, ensure you have:

- [ ] AWS Account with appropriate permissions
- [ ] AWS CLI installed (`aws --version`)
- [ ] AWS CLI configured (`aws configure`)
- [ ] Terraform >= 1.0 installed (`terraform version`)
- [ ] Docker installed and running (`docker ps`)
- [ ] Python 3.11+ (for local development/testing)
- [ ] Make (optional, for convenience commands)

### Required AWS Permissions

Your AWS credentials need permissions for:
- ECS, ECR, ALB, DynamoDB, Lambda, EventBridge, IAM, CloudWatch, VPC, S3

## Step-by-Step Deployment

### Step 1: Configure AWS CLI

If you haven't already configured AWS CLI:

```bash
aws configure
```

Enter your:
- AWS Access Key ID
- AWS Secret Access Key
- Default region (e.g., `ap-south-1`)
- Default output format (e.g., `json`)

Verify configuration:
```bash
aws sts get-caller-identity
```

### Step 2: Set Up Terraform Backend

The backend stores Terraform state in S3 and uses DynamoDB for state locking.

```bash
make setup
```

Or manually:
```bash
bash scripts/setup.sh
```

This creates:
- S3 bucket: `tempus-terraform-state` (or custom name)
- DynamoDB table: `tempus-terraform-locks` (or custom name)

**Note**: The script uses environment variables:
- `AWS_REGION` (defaults to `ap-south-1`)
- `PROJECT_NAME` (defaults to `tempus`)

### Step 3: Configure Terraform Backend

Edit `terraform/main.tf` and uncomment the backend configuration:

```hcl
backend "s3" {
  bucket         = "tempus-terraform-state"
  key            = "terraform.tfstate"
  region         = "ap-south-1"  # Change to your region
  dynamodb_table = "tempus-terraform-locks"
  encrypt        = true
}
```

**Important**: Update the bucket name and region if you used different values in Step 2.

### Step 4: Configure Terraform Variables

Copy the example variables file:

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars`:

```hcl
region = "ap-south-1"  # Your AWS region
project_name = "tempus"
environment = "dev"

# Leave container_image empty for now - we'll set it after ECR is created
container_image = ""
```

### Step 5: Initialize Terraform

```bash
cd terraform
terraform init
```

This downloads providers and configures the backend.

### Step 6: Deploy Infrastructure (First Pass)

This creates the ECR repository and other infrastructure. We'll deploy without a container image first.

```bash
terraform plan
```

Review the planned changes. You should see:
- ECR repository creation
- ECS cluster
- ALB
- DynamoDB table
- Lambda function
- IAM roles
- Security groups

Apply the changes:

```bash
terraform apply
```

Type `yes` when prompted.

**Note**: This will create the ECR repository, which we need before we can push the Docker image.

### Step 7: Build and Push Docker Image

Now that ECR exists, build and push the Docker image:

```bash
cd ..  # Return to project root
make build
```

Or manually:
```bash
bash scripts/build_and_push.sh
```

This will:
1. Build the Docker image
2. Tag it for ECR
3. Login to ECR
4. Push the image

**Important**: Note the ECR Image URI from the output. It will look like:
```
123456789012.dkr.ecr.ap-south-1.amazonaws.com/tempus-backend:latest
```

### Step 8: Update Terraform Variables with Container Image

Edit `terraform/terraform.tfvars` and add the container image URI:

```hcl
region = "ap-south-1"
project_name = "tempus"
environment = "dev"
container_image = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/tempus-backend:latest"
```

Replace with your actual ECR image URI from Step 7.

### Step 9: Update Infrastructure with Container Image

```bash
cd terraform
terraform plan
```

You should see changes related to the container image being used in task definitions.

```bash
terraform apply
```

Type `yes` when prompted.

### Step 10: Get Deployment Outputs

After deployment completes, get the important outputs:

```bash
terraform output
```

Key outputs:
- `alb_dns_name` - The ALB URL for accessing the API
- `alb_arn` - ALB ARN (needed for backend)
- `alb_listener_arn` - ALB listener ARN (needed for backend)
- `ecs_cluster_name` - ECS cluster name
- `dynamodb_table_name` - DynamoDB table name
- `lambda_cleanup_function_arn` - Lambda function ARN (needed for backend)
- `ecr_repository_url` - ECR repository URL

### Step 11: Deploy Backend Service

**Important**: The FastAPI backend service needs to be running to handle `/preview/create` requests. You have two options:

#### Option A: Run Backend Locally (for testing)

1. Set up environment variables using the helper script:

```bash
source <(bash scripts/setup_backend_env.sh | sed 's/ap-south-1/us-east-1/')
```

Or manually export them:

```bash
# Get values from Terraform outputs
cd terraform
export AWS_REGION=$(terraform output -raw region 2>/dev/null || echo "ap-south-1")
export ECS_CLUSTER_NAME=$(terraform output -raw ecs_cluster_name)
export ALB_ARN=$(terraform output -raw alb_arn)
export ALB_LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn $(terraform output -raw alb_arn) --query 'Listeners[0].ListenerArn' --output text)
export TASK_EXECUTION_ROLE_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/tempus-ecs-task-execution"
export TASK_ROLE_ARN="arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/tempus-ecs-task"
export ECS_SECURITY_GROUP_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=tempus-ecs*" --query 'SecurityGroups[0].GroupId' --output text)
export SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=default-for-az,Values=true" --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')
export CONTAINER_IMAGE=$(terraform output -raw ecr_repository_url):latest
export DYNAMODB_TABLE_NAME=$(terraform output -raw dynamodb_table_name)
export LAMBDA_CLEANUP_ARN=$(terraform output -raw lambda_cleanup_function_arn)
export ALB_DNS_NAME=$(terraform output -raw alb_dns_name)
export LOG_GROUP_NAME="/ecs/tempus"
```

2. Install dependencies and run:
```bash
cd ../backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### Option B: Deploy Backend as ECS Service (recommended for production)

The current Terraform configuration creates infrastructure but doesn't deploy the main backend service. You'll need to:

1. Create an ECS service for the backend API (similar to how preview services are created)
2. Or use the existing infrastructure and deploy the backend separately

For now, Option A (local) is recommended for initial testing.

### Step 12: Verify Deployment

#### 12.1 Check Infrastructure

```bash
# Check ECS cluster
aws ecs describe-clusters --clusters tempus-cluster

# Check ALB
aws elbv2 describe-load-balancers --names tempus-alb

# Check DynamoDB table
aws dynamodb describe-table --table-name tempus-previews

# Check Lambda function
aws lambda get-function --function-name tempus-cleanup
```

#### 12.2 Test Backend Service

If running locally, test:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status":"ok","service":"tempus"}
```

#### 12.3 Test Preview Creation

Once the backend is running:
```bash
curl -X POST http://localhost:8000/preview/create \
  -H "Content-Type: application/json" \
  -d '{"ttl_hours": 2}'
```

Expected response:
```json
{
  "preview_id": "550e8400-e29b-41d4-a716-446655440000",
  "preview_url": "http://alb-123456789.us-east-1.elb.amazonaws.com/preview-550e8400",
  "expires_at": "2024-01-01T14:00:00Z"
}
```

#### 12.4 Check DynamoDB

```bash
aws dynamodb scan --table-name tempus-previews
```

#### 12.5 Check Lambda Function

```bash
aws lambda get-function --function-name tempus-cleanup
```

## Troubleshooting

### Issue: ECR Repository Not Found During Build

**Solution**: Deploy Terraform first (Step 6) to create the ECR repository, then build and push.

### Issue: ECS Service Fails to Start

**Check**:
1. CloudWatch logs:
   ```bash
   aws logs tail /ecs/tempus --follow
   ```

2. ECS service events:
   ```bash
   aws ecs describe-services --cluster tempus-cluster --services <service-name>
   ```

3. Security group rules - ensure ALB can reach ECS tasks

4. Task definition - verify container image URI is correct

### Issue: ALB Health Checks Failing

**Check**:
1. ECS service is running and healthy
2. Health check path is `/health`
3. Security groups allow traffic between ALB and ECS
4. Target group is registered with healthy targets

### Issue: Lambda Cleanup Not Triggering

**Check**:
1. EventBridge rules:
   ```bash
   aws events list-rules --name-prefix tempus-cleanup
   ```

2. Lambda permissions:
   ```bash
   aws lambda get-policy --function-name tempus-cleanup
   ```

3. CloudWatch logs for Lambda:
   ```bash
   aws logs tail /aws/lambda/tempus-cleanup --follow
   ```

### Issue: Terraform State Lock

If Terraform is stuck with a state lock:

```bash
# List locks
aws dynamodb scan --table-name tempus-terraform-locks

# Delete lock (use with caution!)
aws dynamodb delete-item \
  --table-name tempus-terraform-locks \
  --key '{"LockID":{"S":"<lock-id>"}}'
```

### Issue: Container Image Not Found

**Solution**: Ensure you've pushed the image to ECR and updated `terraform.tfvars` with the correct image URI.

## Updating the Application

### Update Backend Code

1. Make your code changes
2. Build and push new image:
   ```bash
   make build
   ```
3. Update `terraform/terraform.tfvars` with new image tag (if using tags)
4. Apply changes:
   ```bash
   cd terraform
   terraform apply
   ```

Or force a new deployment:
```bash
aws ecs update-service \
  --cluster tempus-cluster \
  --service <service-name> \
  --force-new-deployment
```

## Cleanup

To destroy all resources:

```bash
cd terraform
terraform destroy
```

**Warning**: This will delete:
- All ECS services and tasks
- ALB and target groups
- DynamoDB table and all data
- Lambda function
- EventBridge rules
- ECR repository (images will be deleted)
- All other infrastructure

## Cost Estimation

Approximate monthly costs (varies by usage):

- **ECS Fargate**: ~$15/month per active preview (0.25 vCPU, 512 MB)
- **ALB**: ~$16/month base + $0.008/LCU-hour
- **DynamoDB**: Pay-per-request (minimal for metadata)
- **Lambda**: Free tier covers most usage
- **EventBridge**: Free tier covers most usage
- **CloudWatch Logs**: ~$0.50/GB ingested
- **S3**: ~$0.023/GB storage (for Terraform state)

**Total**: ~$30-50/month base + usage costs

## Best Practices

1. **Use Terraform Workspaces** for multiple environments
2. **Enable CloudWatch Alarms** for monitoring
3. **Set up Cost Alerts** in AWS Budgets
4. **Regular Backups** of Terraform state
5. **Version Control** all Terraform configurations
6. **Review IAM Permissions** regularly
7. **Monitor CloudWatch Logs** for errors

## Next Steps

After successful deployment:

1. Set up CloudWatch alarms for monitoring
2. Configure AWS Budgets for cost alerts
3. Set up custom domain with SSL (optional)
4. Implement CI/CD pipeline
5. Add authentication/authorization
6. Set up cost tracking dashboard

## Quick Reference Commands

```bash
# Setup
make setup

# Build and push image
make build

# Deploy infrastructure
make deploy

# Setup backend environment variables
source <(bash scripts/setup_backend_env.sh)

# Check health
curl http://localhost:8000/health

# Create preview
curl -X POST http://localhost:8000/preview/create \
  -H "Content-Type: application/json" \
  -d '{"ttl_hours": 2}'

# View logs
aws logs tail /ecs/tempus --follow

# Destroy everything
cd terraform && terraform destroy
```
