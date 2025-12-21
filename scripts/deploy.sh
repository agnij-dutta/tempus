#!/bin/bash
set -e

# Script to deploy infrastructure with Terraform

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/../terraform"

cd "$TERRAFORM_DIR"

echo "Initializing Terraform..."
terraform init

echo ""
echo "Planning Terraform changes..."
terraform plan

echo ""
read -p "Do you want to apply these changes? (yes/no): " -r
if [[ $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Applying Terraform changes..."
    terraform apply
    
    echo ""
    echo "Deployment complete!"
    echo ""
    echo "Outputs:"
    terraform output
else
    echo "Deployment cancelled."
fi

