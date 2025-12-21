terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Backend configuration - uncomment and configure after initial setup
  # backend "s3" {
  #   bucket         = "tempus-terraform-state"
  #   key            = "terraform.tfstate"
  #   region         = "ap-south-1"
  #   dynamodb_table = "tempus-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
}

