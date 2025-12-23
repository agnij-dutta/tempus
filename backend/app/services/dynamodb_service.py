import logging
from datetime import datetime
from typing import Optional, Dict, Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class DynamoDBService:
    """Service for managing preview metadata in DynamoDB."""

    def __init__(self, table_name: str, region: str = "ap-south-1"):
        """
        Initialize DynamoDB service.

        Args:
            table_name: Name of the DynamoDB table
            region: AWS region
        """
        self.table_name = table_name
        self.dynamodb = boto3.client("dynamodb", region_name=region)

    def store_preview_metadata(
        self,
        preview_id: str,
        service_arn: str,
        target_group_arn: str,
        expires_at: str,
        listener_rule_arn: str,
        eventbridge_rule_name: Optional[str] = None
    ) -> None:
        """
        Store preview metadata in DynamoDB.

        Args:
            preview_id: Unique preview identifier
            service_arn: ECS service ARN
            target_group_arn: ALB target group ARN
            expires_at: ISO format expiration timestamp
            eventbridge_rule_name: Optional EventBridge rule name
        """
        try:
            item = {
                "preview_id": {"S": preview_id},
                "service_arn": {"S": service_arn},
                "target_group_arn": {"S": target_group_arn},
                "listener_rule_arn": {"S": listener_rule_arn},
                "expires_at": {"S": expires_at},
                "created_at": {"S": datetime.utcnow().isoformat()},
            }

            if eventbridge_rule_name:
                item["eventbridge_rule_name"] = {"S": eventbridge_rule_name}

            self.dynamodb.put_item(
                TableName=self.table_name,
                Item=item
            )
            logger.info(f"Stored metadata for preview {preview_id}")
        except ClientError as e:
            logger.error(f"Failed to store metadata for preview {preview_id}: {e}")
            raise

    def get_preview_metadata(self, preview_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve preview metadata from DynamoDB.

        Args:
            preview_id: Unique preview identifier

        Returns:
            Dictionary containing preview metadata or None if not found
        """
        try:
            response = self.dynamodb.get_item(
                TableName=self.table_name,
                Key={"preview_id": {"S": preview_id}}
            )

            if "Item" not in response:
                return None

            # Convert DynamoDB item to regular dictionary
            item = {}
            for key, value in response["Item"].items():
                if "S" in value:
                    item[key] = value["S"]
                elif "N" in value:
                    item[key] = value["N"]

            return item
        except ClientError as e:
            logger.error(f"Failed to get metadata for preview {preview_id}: {e}")
            raise

    def delete_preview_metadata(self, preview_id: str) -> None:
        """
        Delete preview metadata from DynamoDB.

        Args:
            preview_id: Unique preview identifier
        """
        try:
            self.dynamodb.delete_item(
                TableName=self.table_name,
                Key={"preview_id": {"S": preview_id}}
            )
            logger.info(f"Deleted metadata for preview {preview_id}")
        except ClientError as e:
            logger.error(f"Failed to delete metadata for preview {preview_id}: {e}")
            # Don't raise - idempotent operation, might already be deleted
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise

    def list_previews(self) -> list[Dict[str, Any]]:
        """List all preview metadata items."""
        try:
            response = self.dynamodb.scan(TableName=self.table_name)
            items = []
            for raw in response.get("Items", []):
                item = {}
                for key, value in raw.items():
                    if "S" in value:
                        item[key] = value["S"]
                    elif "N" in value:
                        item[key] = value["N"]
                items.append(item)
            return items
        except ClientError as e:
            logger.error(f"Failed to list previews: {e}")
            raise

    def update_expires_at(self, preview_id: str, expires_at: str) -> None:
        """Update the expiration timestamp for a preview."""
        try:
            self.dynamodb.update_item(
                TableName=self.table_name,
                Key={"preview_id": {"S": preview_id}},
                UpdateExpression="SET expires_at = :expires",
                ExpressionAttributeValues={":expires": {"S": expires_at}}
            )
            logger.info(f"Updated expires_at for preview {preview_id} to {expires_at}")
        except ClientError as e:
            logger.error(f"Failed to update expires_at for preview {preview_id}: {e}")
            raise

