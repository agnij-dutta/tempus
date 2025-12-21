import logging
from datetime import datetime
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class EventBridgeService:
    """Service for scheduling cleanup events via EventBridge."""

    def __init__(self, lambda_function_arn: str, region: str = "ap-south-1"):
        """
        Initialize EventBridge service.

        Args:
            lambda_function_arn: ARN of the cleanup Lambda function
            region: AWS region
        """
        self.lambda_function_arn = lambda_function_arn
        self.eventbridge = boto3.client("events", region_name=region)
        self.lambda_client = boto3.client("lambda", region_name=region)

    def schedule_cleanup(
        self,
        preview_id: str,
        expires_at: str,
        rule_name: Optional[str] = None
    ) -> str:
        """
        Schedule a cleanup event for a preview environment.

        Args:
            preview_id: Unique preview identifier
            expires_at: ISO format expiration timestamp
            rule_name: Optional rule name (will be generated if not provided)

        Returns:
            Rule name that was created
        """
        if not rule_name:
            rule_name = f"tempus-cleanup-{preview_id}"

        try:
            # Parse expiration time
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            
            # EventBridge Rules only support cron() and rate() expressions
            # For one-time schedules, we need to use EventBridge Scheduler
            # However, as a workaround, we can use a cron expression that matches the exact time
            # Format: cron(minute hour day month ? year)
            cron_expr = expires_dt.strftime("cron(%M %H %d %m ? %Y)")
            
            # Create EventBridge rule with cron expression
            self.eventbridge.put_rule(
                Name=rule_name,
                ScheduleExpression=cron_expr,
                State="ENABLED",
                Description=f"Cleanup rule for preview {preview_id}"
            )

            # Add Lambda as target
            self.eventbridge.put_targets(
                Rule=rule_name,
                Targets=[
                    {
                        "Id": "1",
                        "Arn": self.lambda_function_arn,
                        "Input": f'{{"preview_id": "{preview_id}"}}'
                    }
                ]
            )

            # Grant EventBridge permission to invoke Lambda
            # Note: This is handled by Terraform, but we try to add it here for dynamic rules
            try:
                session = boto3.Session()
                sts = boto3.client("sts", region_name=session.region_name)
                account_id = sts.get_caller_identity()["Account"]
                region = session.region_name or "ap-south-1"
                
                self.lambda_client.add_permission(
                    FunctionName=self.lambda_function_arn,
                    StatementId=f"eventbridge-{preview_id[:8]}",
                    Action="lambda:InvokeFunction",
                    Principal="events.amazonaws.com",
                    SourceArn=f"arn:aws:events:{region}:{account_id}:rule/{rule_name}"
                )
            except ClientError as e:
                # Permission might already exist, that's okay
                if e.response["Error"]["Code"] not in ["ResourceConflictException", "InvalidParameterValueException"]:
                    logger.warning(f"Could not add Lambda permission: {e}")

            logger.info(f"Scheduled cleanup for preview {preview_id} at {expires_at}")
            return rule_name

        except ClientError as e:
            logger.error(f"Failed to schedule cleanup for preview {preview_id}: {e}")
            raise

    def delete_rule(self, rule_name: str) -> None:
        """
        Delete an EventBridge rule.

        Args:
            rule_name: Name of the rule to delete
        """
        try:
            # Remove targets first
            targets = self.eventbridge.list_targets_by_rule(Rule=rule_name)
            if targets.get("Targets"):
                target_ids = [t["Id"] for t in targets["Targets"]]
                self.eventbridge.remove_targets(Rule=rule_name, Ids=target_ids)

            # Delete the rule
            self.eventbridge.delete_rule(Name=rule_name)
            logger.info(f"Deleted EventBridge rule {rule_name}")
        except ClientError as e:
            logger.error(f"Failed to delete EventBridge rule {rule_name}: {e}")
            # Don't raise - idempotent operation
            if e.response["Error"]["Code"] not in ["ResourceNotFoundException", "ValidationException"]:
                raise

