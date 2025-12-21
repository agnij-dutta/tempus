# Deployment Guide

## Prerequisites

1. **AWS Account** with appropriate permissions
2. **AWS CLI** installed and configured
3. **Terraform** >= 1.0 installed
4. **Docker** installed and running
5. **Python** 3.11+ (for local development)
6. **Make** (optional, for convenience commands)

## Initial Setup

### 1. Configure AWS CLI

```bash
aws configure
```

Ensure you have permissions for:
- ECS, ECR, ALB, DynamoDB, Lambda, EventBridge, IAM, CloudWatch

### 2. Set Up Terraform Backend

```bash
make setup
```

Or manually:

```bash
bash scripts/setup.sh
```

This creates:
- S3 bucket for Terraform state
- DynamoDB table for state locking

### 3. Configure Terraform Backend

Edit `terraform/main.tf` and uncomment the backend configuration:

```hcl
backend "s3" {
  bucket         = "tempus-terraform-state"
  key            = "terraform.tfstate"
  region         = "ap-south-1"
  dynamodb_table = "tempus-terraform-locks"
  encrypt        = true
}
```

Update the bucket and table names if you used different values.

## Deployment Steps

### Step 1: Build and Push Docker Image

```bash
make build
```

Or manually:

```bash
bash scripts/build_and_push.sh
```

This will:
1. Build the Docker image
2. Tag it with the ECR repository
3. Push it to ECR

**Note**: The ECR repository must exist first (created by Terraform).

### Step 2: Configure Terraform Variables

Copy the example variables file:

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars` and set:

```hcl
region = "ap-south-1"  # Your AWS region
container_image = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/tempus-backend:latest"
```

Get the container image URI from the build script output.

### Step 3: Initialize Terraform

```bash
cd terraform
terraform init
```

### Step 4: Review Changes

```bash
terraform plan
```

Review the planned changes carefully.

### Step 5: Deploy Infrastructure

```bash
terraform apply
```

Or use the deployment script:

```bash
make deploy
```

### Step 6: Configure Backend Environment Variables

After deployment, get the outputs:

```bash
terraform output
```

Update your ECS task definition or create a new deployment with environment variables:

- `ECS_CLUSTER_NAME`: ECS cluster name
- `ALB_ARN`: ALB ARN
- `ALB_LISTENER_ARN`: ALB listener ARN
- `ALB_DNS_NAME`: ALB DNS name
- `TASK_EXECUTION_ROLE_ARN`: Task execution role ARN
- `TASK_ROLE_ARN`: Task role ARN
- `ECS_SECURITY_GROUP_ID`: ECS security group ID
- `SUBNET_IDS`: Comma-separated subnet IDs
- `DYNAMODB_TABLE_NAME`: DynamoDB table name
- `LAMBDA_CLEANUP_ARN`: Lambda cleanup function ARN
- `CONTAINER_IMAGE`: Container image URI
- `LOG_GROUP_NAME`: CloudWatch log group name
- `AWS_REGION`: AWS region

## Verification

### 1. Check ECS Service

```bash
aws ecs list-services --cluster tempus-cluster
```

### 2. Check ALB

```bash
aws elbv2 describe-load-balancers --names tempus-alb
```

Get the DNS name and test:

```bash
curl http://<ALB_DNS_NAME>/health
```

### 3. Test Preview Creation

```bash
curl -X POST http://<ALB_DNS_NAME>/preview/create \
  -H "Content-Type: application/json" \
  -d '{"ttl_hours": 2}'
```

### 4. Check DynamoDB

```bash
aws dynamodb scan --table-name tempus-previews
```

### 5. Check Lambda Function

```bash
aws lambda get-function --function-name tempus-cleanup
```

## Troubleshooting

### Issue: ECR Repository Not Found

**Solution**: Deploy Terraform first to create the ECR repository, then build and push the image.

### Issue: ECS Service Fails to Start

**Check**:
1. Task definition logs in CloudWatch
2. ECS service events
3. Security group rules
4. Subnet configuration

```bash
aws ecs describe-services --cluster tempus-cluster --services <service-name>
aws logs tail /ecs/tempus --follow
```

### Issue: ALB Health Checks Failing

**Check**:
1. ECS service is running
2. Health check path is correct (`/health`)
3. Security groups allow traffic
4. Target group is registered

### Issue: Lambda Cleanup Not Triggering

**Check**:
1. EventBridge rule exists
2. Rule is enabled
3. Lambda has correct permissions
4. EventBridge can invoke Lambda

```bash
aws events list-rules --name-prefix tempus-cleanup
aws lambda get-policy --function-name tempus-cleanup
```

### Issue: Terraform State Lock

If Terraform is stuck with a state lock:

```bash
aws dynamodb delete-item \
  --table-name tempus-terraform-locks \
  --key '{"LockID":{"S":"<lock-id>"}}'
```

## Updating the Application

### 1. Build New Image

```bash
make build
```

### 2. Update Terraform Variables

Update `container_image` in `terraform.tfvars` with the new image tag.

### 3. Apply Changes

```bash
terraform apply
```

Or update the ECS service directly:

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

**Warning**: This will delete all resources including:
- ECS cluster and services
- ALB and target groups
- DynamoDB table (and all data)
- Lambda function
- EventBridge rules
- ECR repository (images will be deleted)

## Cost Estimation

Approximate monthly costs (varies by usage):

- **ECS Fargate**: ~$15/month per active preview (0.25 vCPU, 512 MB)
- **ALB**: ~$16/month base + $0.008/LCU-hour
- **DynamoDB**: Pay-per-request (minimal for metadata)
- **Lambda**: Free tier covers most usage
- **EventBridge**: Free tier covers most usage
- **CloudWatch Logs**: ~$0.50/GB ingested

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

- Set up CI/CD pipeline
- Configure monitoring and alerts
- Implement cost tracking
- Add authentication/authorization
- Set up custom domain with SSL

