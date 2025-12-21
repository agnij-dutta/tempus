import logging
import os
import uuid
from datetime import datetime, timedelta

import boto3
from fastapi import APIRouter, HTTPException, Depends

from app.models import CreatePreviewRequest, PreviewResponse
from app.services.ecs_service import ECSService
from app.services.dynamodb_service import DynamoDBService
from app.services.eventbridge_service import EventBridgeService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/preview", tags=["preview"])


def get_ecs_service() -> ECSService:
    """Dependency to get ECS service instance."""
    return ECSService(
        cluster_name=os.getenv("ECS_CLUSTER_NAME", "tempus-cluster"),
        alb_arn=os.getenv("ALB_ARN", ""),
        alb_listener_arn=os.getenv("ALB_LISTENER_ARN", ""),
        task_execution_role_arn=os.getenv("TASK_EXECUTION_ROLE_ARN", ""),
        task_role_arn=os.getenv("TASK_ROLE_ARN", ""),
        security_group_id=os.getenv("ECS_SECURITY_GROUP_ID", ""),
        subnet_ids=os.getenv("SUBNET_IDS", "").split(",") if os.getenv("SUBNET_IDS") else [],
        container_image=os.getenv("CONTAINER_IMAGE", ""),
        region=os.getenv("AWS_REGION", "ap-south-1")
    )


def get_dynamodb_service() -> DynamoDBService:
    """Dependency to get DynamoDB service instance."""
    return DynamoDBService(
        table_name=os.getenv("DYNAMODB_TABLE_NAME", "tempus-previews"),
        region=os.getenv("AWS_REGION", "ap-south-1")
    )


def get_eventbridge_service() -> EventBridgeService:
    """Dependency to get EventBridge service instance."""
    return EventBridgeService(
        lambda_function_arn=os.getenv("LAMBDA_CLEANUP_ARN", ""),
        region=os.getenv("AWS_REGION", "ap-south-1")
    )


@router.post("/create", response_model=PreviewResponse, summary="Create Preview Environment")
async def create_preview(
    request: CreatePreviewRequest,
    ecs_service: ECSService = Depends(get_ecs_service),
    dynamodb_service: DynamoDBService = Depends(get_dynamodb_service),
    eventbridge_service: EventBridgeService = Depends(get_eventbridge_service)
):
    """
    Create a new ephemeral preview environment.
    
    This endpoint provisions a complete preview environment including:
    
    - **ECS Fargate Service**: Containerized application running on AWS
    - **Application Load Balancer**: Public URL for accessing the preview
    - **DynamoDB Metadata**: Stores preview configuration and expiration
    - **EventBridge Rule**: Schedules automatic cleanup at expiration time
    
    The preview environment will automatically be destroyed after the specified `ttl_hours`.
    
    **Example Request:**
    ```json
    {
        "ttl_hours": 2
    }
    ```
    
    **Example Response:**
    ```json
    {
        "preview_id": "550e8400-e29b-41d4-a716-446655440000",
        "preview_url": "http://alb-123456789.us-east-1.elb.amazonaws.com/preview-550e8400",
        "expires_at": "2024-01-01T14:00:00Z"
    }
    ```
    """
    preview_id = str(uuid.uuid4())
    expires_at = (datetime.utcnow() + timedelta(hours=request.ttl_hours)).isoformat() + "Z"
    
    try:
        logger.info(f"Creating preview environment {preview_id} with TTL {request.ttl_hours} hours")
        
        # Step 1: Create ECS service and target group
        service_arn, target_group_arn, listener_rule_arn = ecs_service.create_preview_service(
            preview_id=preview_id,
            log_group_name=os.getenv("LOG_GROUP_NAME", "/ecs/tempus")
        )
        
        # Step 2: Schedule cleanup event
        rule_name = f"tempus-cleanup-{preview_id}"
        eventbridge_service.schedule_cleanup(
            preview_id=preview_id,
            expires_at=expires_at,
            rule_name=rule_name
        )
        
        # Step 3: Store metadata in DynamoDB
        dynamodb_service.store_preview_metadata(
            preview_id=preview_id,
            service_arn=service_arn,
            target_group_arn=target_group_arn,
            expires_at=expires_at,
            listener_rule_arn=listener_rule_arn,
            eventbridge_rule_name=rule_name
        )
        
        # Step 4: Get preview URL
        alb_dns_name = os.getenv("ALB_DNS_NAME", "")
        preview_url = ecs_service.get_service_url(alb_dns_name, preview_id)
        
        logger.info(f"Successfully created preview environment {preview_id}")
        
        return PreviewResponse(
            preview_id=preview_id,
            preview_url=preview_url,
            expires_at=expires_at
        )
        
    except Exception as e:
        logger.error(f"Failed to create preview environment {preview_id}: {e}", exc_info=True)
        
        # Attempt cleanup on failure
        try:
            # Delete EventBridge rule if created
            try:
                eventbridge_service.delete_rule(f"tempus-cleanup-{preview_id}")
            except Exception:
                pass
            
            # Delete DynamoDB record if created
            try:
                dynamodb_service.delete_preview_metadata(preview_id)
            except Exception:
                pass
            
            # ECS service cleanup is handled by ecs_service._cleanup_on_failure
        except Exception as cleanup_error:
            logger.error(f"Cleanup after failure also failed: {cleanup_error}")
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create preview environment: {str(e)}"
        )


@router.get("/health", summary="Preview Health Check")
async def health():
    """
    Health check endpoint for preview environments.
    
    Returns a simple status check to verify the preview environment is operational.
    """
    return {"status": "ok"}

