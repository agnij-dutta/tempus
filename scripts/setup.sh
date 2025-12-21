#!/bin/bash
set -e

# Script to set up initial AWS resources for Terraform backend

REGION="${AWS_REGION:-ap-south-1}"
PROJECT_NAME="${PROJECT_NAME:-tempus}"
STATE_BUCKET="${STATE_BUCKET:-${PROJECT_NAME}-terraform-state}"
LOCK_TABLE="${LOCK_TABLE:-${PROJECT_NAME}-terraform-locks}"

echo "Setting up Terraform backend resources..."
echo "Region: $REGION"
echo "State Bucket: $STATE_BUCKET"
echo "Lock Table: $LOCK_TABLE"

# Create S3 bucket for Terraform state
if aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
    echo "S3 bucket $STATE_BUCKET already exists"
else
    echo "Creating S3 bucket $STATE_BUCKET..."
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$REGION"
    else
        aws s3api create-bucket \
            --bucket "$STATE_BUCKET" \
            --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION"
    fi
    
    # Enable versioning
    aws s3api put-bucket-versioning \
        --bucket "$STATE_BUCKET" \
        --versioning-configuration Status=Enabled
    
    # Enable encryption
    aws s3api put-bucket-encryption \
        --bucket "$STATE_BUCKET" \
        --server-side-encryption-configuration '{
            "Rules": [{
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                }
            }]
        }'
    
    echo "S3 bucket $STATE_BUCKET created successfully"
fi

# Create DynamoDB table for state locking
if aws dynamodb describe-table --table-name "$LOCK_TABLE" --region "$REGION" 2>/dev/null; then
    echo "DynamoDB table $LOCK_TABLE already exists"
else
    echo "Creating DynamoDB table $LOCK_TABLE..."
    aws dynamodb create-table \
        --table-name "$LOCK_TABLE" \
        --attribute-definitions AttributeName=LockID,AttributeType=S \
        --key-schema AttributeName=LockID,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region "$REGION"
    
    echo "Waiting for table to be active..."
    aws dynamodb wait table-exists --table-name "$LOCK_TABLE" --region "$REGION"
    
    echo "DynamoDB table $LOCK_TABLE created successfully"
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Update terraform/main.tf with your backend configuration:"
echo "   backend \"s3\" {"
echo "     bucket         = \"$STATE_BUCKET\""
echo "     key            = \"terraform.tfstate\""
echo "     region         = \"$REGION\""
echo "     dynamodb_table = \"$LOCK_TABLE\""
echo "     encrypt        = true"
echo "   }"
echo ""
echo "2. Run: terraform init"
echo "3. Run: terraform plan"
echo "4. Run: terraform apply"

