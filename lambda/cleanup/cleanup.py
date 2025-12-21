import json
import logging
import os
from typing import Dict, Any

import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize AWS clients
region = os.getenv("AWS_REGION", "ap-south-1")
ecs = boto3.client("ecs", region_name=region)
elbv2 = boto3.client("elbv2", region_name=region)
events = boto3.client("events", region_name=region)
dynamodb = boto3.client("dynamodb", region_name=region)
lambda_client = boto3.client("lambda", region_name=region)

# Configuration from environment
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE_NAME", "tempus-previews")
CLUSTER_NAME = os.getenv("ECS_CLUSTER_NAME", "tempus-cluster")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler to clean up preview environment resources.
    
    Args:
        event: EventBridge event containing preview_id
        context: Lambda context
        
    Returns:
        Response dictionary
    """
    try:
        # Extract preview_id from event
        if isinstance(event, str):
            event = json.loads(event)
        
        preview_id = event.get("preview_id")
        if not preview_id:
            logger.error("No preview_id found in event")
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "preview_id is required"})
            }
        
        logger.info(f"Starting cleanup for preview {preview_id}")
        
        # Fetch metadata from DynamoDB
        metadata = get_preview_metadata(preview_id)
        if not metadata:
            logger.warning(f"No metadata found for preview {preview_id}, may already be cleaned up")
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Preview not found, may already be cleaned up"})
            }
        
        service_arn = metadata.get("service_arn")
        target_group_arn = metadata.get("target_group_arn")
        listener_rule_arn = metadata.get("listener_rule_arn")
        eventbridge_rule_name = metadata.get("eventbridge_rule_name", f"tempus-cleanup-{preview_id}")
        
        errors = []
        
        # Step 1: Delete ECS service
        if service_arn:
            try:
                delete_ecs_service(service_arn)
            except Exception as e:
                logger.error(f"Failed to delete ECS service: {e}")
                errors.append(f"ECS service deletion failed: {str(e)}")
        
        # Step 2: Delete ALB listener rule (must be deleted before target group)
        if listener_rule_arn:
            try:
                delete_listener_rule(listener_rule_arn)
            except Exception as e:
                logger.error(f"Failed to delete listener rule: {e}")
                errors.append(f"Listener rule deletion failed: {str(e)}")
        
        # Step 3: Delete target group (can only be deleted after listener rule is removed)
        if target_group_arn:
            try:
                delete_target_group(target_group_arn)
            except Exception as e:
                logger.error(f"Failed to delete target group: {e}")
                errors.append(f"Target group deletion failed: {str(e)}")
        
        # Step 4: Delete EventBridge rule
        if eventbridge_rule_name:
            try:
                delete_eventbridge_rule(eventbridge_rule_name)
            except Exception as e:
                logger.error(f"Failed to delete EventBridge rule: {e}")
                errors.append(f"EventBridge rule deletion failed: {str(e)}")
        
        # Step 5: Delete DynamoDB record
        try:
            delete_dynamodb_record(preview_id)
        except Exception as e:
            logger.error(f"Failed to delete DynamoDB record: {e}")
            errors.append(f"DynamoDB record deletion failed: {str(e)}")
        
        if errors:
            logger.warning(f"Cleanup completed with errors for preview {preview_id}: {errors}")
            return {
                "statusCode": 207,  # Multi-status
                "body": json.dumps({
                    "message": "Cleanup completed with errors",
                    "preview_id": preview_id,
                    "errors": errors
                })
            }
        
        logger.info(f"Successfully cleaned up preview {preview_id}")
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Cleanup completed successfully",
                "preview_id": preview_id
            })
        }
        
    except Exception as e:
        logger.error(f"Unexpected error during cleanup: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


def get_preview_metadata(preview_id: str) -> Dict[str, Any]:
    """Retrieve preview metadata from DynamoDB."""
    try:
        response = dynamodb.get_item(
            TableName=DYNAMODB_TABLE,
            Key={"preview_id": {"S": preview_id}}
        )
        
        if "Item" not in response:
            return {}
        
        # Convert DynamoDB item to regular dictionary
        item = {}
        for key, value in response["Item"].items():
            if "S" in value:
                item[key] = value["S"]
            elif "N" in value:
                item[key] = value["N"]
        
        return item
    except ClientError as e:
        logger.error(f"Failed to get metadata: {e}")
        raise


def delete_ecs_service(service_arn: str) -> None:
    """Delete ECS service."""
    # Extract service name from ARN
    service_name = service_arn.split("/")[-1]
    
    try:
        # Update service to 0 desired count first
        ecs.update_service(
            cluster=CLUSTER_NAME,
            service=service_name,
            desiredCount=0
        )
        
        # Wait for service to drain (simplified - in production use waiter)
        import time
        max_wait = 300  # 5 minutes
        wait_time = 0
        while wait_time < max_wait:
            response = ecs.describe_services(
                cluster=CLUSTER_NAME,
                services=[service_name]
            )
            running_count = response["services"][0]["runningCount"]
            if running_count == 0:
                break
            time.sleep(10)
            wait_time += 10
        
        # Delete the service
        ecs.delete_service(
            cluster=CLUSTER_NAME,
            service=service_name,
            force=True
        )
        logger.info(f"Deleted ECS service {service_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ServiceNotFoundException":
            logger.info(f"ECS service {service_name} not found, may already be deleted")
            return
        raise


def delete_listener_rule(rule_arn: str) -> None:
    """Delete ALB listener rule."""
    try:
        elbv2.delete_rule(RuleArn=rule_arn)
        logger.info(f"Deleted listener rule {rule_arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "RuleNotFound":
            logger.info(f"Listener rule {rule_arn} not found, may already be deleted")
            return
        raise


def delete_target_group(target_group_arn: str) -> None:
    """Delete ALB target group."""
    try:
        elbv2.delete_target_group(TargetGroupArn=target_group_arn)
        logger.info(f"Deleted target group {target_group_arn}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "TargetGroupNotFound":
            logger.info(f"Target group {target_group_arn} not found, may already be deleted")
            return
        raise


def delete_eventbridge_rule(rule_name: str) -> None:
    """Delete EventBridge rule."""
    try:
        # Remove targets first
        targets = events.list_targets_by_rule(Rule=rule_name)
        if targets.get("Targets"):
            target_ids = [t["Id"] for t in targets["Targets"]]
            events.remove_targets(Rule=rule_name, Ids=target_ids)
            
            # Remove Lambda permission
            for target in targets["Targets"]:
                if "Arn" in target and "lambda" in target["Arn"]:
                    try:
                        # Extract preview_id from rule name (format: tempus-cleanup-{preview_id})
                        preview_id_part = rule_name.split("-")[-1] if "-" in rule_name else rule_name[-8:]
                        lambda_client.remove_permission(
                            FunctionName=target["Arn"],
                            StatementId=f"eventbridge-{preview_id_part[:8]}"
                        )
                    except ClientError as e:
                        # Permission might not exist, that's okay
                        if e.response["Error"]["Code"] not in ["ResourceNotFoundException"]:
                            logger.warning(f"Could not remove Lambda permission: {e}")
        
        # Delete the rule
        events.delete_rule(Name=rule_name)
        logger.info(f"Deleted EventBridge rule {rule_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] in ["ResourceNotFoundException", "ValidationException"]:
            logger.info(f"EventBridge rule {rule_name} not found, may already be deleted")
            return
        raise


def delete_dynamodb_record(preview_id: str) -> None:
    """Delete DynamoDB record."""
    try:
        dynamodb.delete_item(
            TableName=DYNAMODB_TABLE,
            Key={"preview_id": {"S": preview_id}}
        )
        logger.info(f"Deleted DynamoDB record for preview {preview_id}")
    except ClientError as e:
        logger.error(f"Failed to delete DynamoDB record: {e}")
        # Don't raise - idempotent operation

