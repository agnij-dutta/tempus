.PHONY: help setup build push deploy clean test lint test-local test-api

help:
	@echo "Available commands:"
	@echo "  make setup      - Set up initial AWS resources (S3 bucket, DynamoDB table)"
	@echo "  make build      - Build Docker image"
	@echo "  make push       - Push Docker image to ECR"
	@echo "  make deploy     - Deploy infrastructure with Terraform"
	@echo "  make test-local - Run FastAPI server locally for testing"
	@echo "  make test-api   - Test API endpoints (requires server running)"
	@echo "  make clean      - Clean up local build artifacts"
	@echo "  make test       - Run tests (placeholder)"
	@echo "  make lint       - Run linters (placeholder)"

setup:
	@bash scripts/setup.sh

build:
	@bash scripts/build_and_push.sh

push: build

deploy:
	@bash scripts/deploy.sh

clean:
	@echo "Cleaning up local artifacts..."
	@rm -f lambda/cleanup.zip
	@rm -rf backend/__pycache__
	@rm -rf backend/app/__pycache__
	@rm -rf backend/app/services/__pycache__
	@rm -rf backend/app/routes/__pycache__
	@find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleanup complete"

test-local:
	@bash scripts/test_local.sh

test-api:
	@bash scripts/test_api.sh

test:
	@echo "Tests not yet implemented"

lint:
	@echo "Linters not yet configured"

