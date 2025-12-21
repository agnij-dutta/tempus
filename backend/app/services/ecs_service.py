import logging
import os
from typing import Tuple, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ECSService:
    """Service for managing ECS services and related resources."""

    def __init__(
        self,
        cluster_name: str,
        alb_arn: str,
        alb_listener_arn: str,
        task_execution_role_arn: str,
        task_role_arn: str,
        security_group_id: str,
        subnet_ids: list,
        container_image: str,
        region: str = "ap-south-1"
    ):
        """
        Initialize ECS service.

        Args:
            cluster_name: Name of the ECS cluster
            alb_arn: ARN of the Application Load Balancer
            alb_listener_arn: ARN of the ALB listener
            task_execution_role_arn: ARN of the task execution role
            task_role_arn: ARN of the task role
            security_group_id: Security group ID for ECS tasks
            subnet_ids: List of subnet IDs for ECS tasks
            container_image: ECR image URL
            region: AWS region
        """
        self.cluster_name = cluster_name
        self.alb_arn = alb_arn
        self.alb_listener_arn = alb_listener_arn
        self.task_execution_role_arn = task_execution_role_arn
        self.task_role_arn = task_role_arn
        self.security_group_id = security_group_id
        self.subnet_ids = subnet_ids
        self.container_image = container_image
        self.ecs = boto3.client("ecs", region_name=region)
        self.elbv2 = boto3.client("elbv2", region_name=region)

    def create_preview_service(
        self,
        preview_id: str,
        log_group_name: str
    ) -> Tuple[str, str, str]:
        """
        Create an ECS service for a preview environment.

        Args:
            preview_id: Unique preview identifier
            log_group_name: CloudWatch log group name

        Returns:
            Tuple of (service_arn, target_group_arn, listener_rule_arn)
        """
        service_name = f"preview-{preview_id}"
        task_family = f"preview-{preview_id}"

        try:
            # Create target group
            target_group_arn = self._create_target_group(preview_id)

            # Create task definition
            task_definition_arn = self._create_task_definition(
                task_family,
                log_group_name
            )

            # Create ECS service
            service_arn = self._create_ecs_service(
                service_name,
                task_definition_arn,
                target_group_arn
            )

            # Register target group with ALB listener
            listener_rule_arn = self._add_listener_rule(preview_id, target_group_arn)

            logger.info(f"Created ECS service {service_name} for preview {preview_id}")
            return service_arn, target_group_arn, listener_rule_arn

        except Exception as e:
            logger.error(f"Failed to create preview service for {preview_id}: {e}")
            # Attempt cleanup on failure
            try:
                listener_rule_arn_local = listener_rule_arn if 'listener_rule_arn' in locals() else None
                target_group_arn_local = target_group_arn if 'target_group_arn' in locals() else None
                self._cleanup_on_failure(preview_id, target_group_arn_local, listener_rule_arn_local)
            except Exception as cleanup_error:
                logger.error(f"Cleanup on failure also failed: {cleanup_error}")
            raise

    def _create_target_group(self, preview_id: str) -> str:
        """Create an ALB target group for the preview."""
        try:
            # Get VPC ID from ALB
            alb_response = self.elbv2.describe_load_balancers(LoadBalancerArns=[self.alb_arn])
            vpc_id = alb_response["LoadBalancers"][0]["VpcId"]
            
            response = self.elbv2.create_target_group(
                Name=f"preview-{preview_id[:24]}",  # Target group names have 32 char limit (8 char prefix + 24 chars)
                Protocol="HTTP",
                Port=8000,
                VpcId=vpc_id,
                TargetType="ip",
                HealthCheckPath="/health",
                HealthCheckProtocol="HTTP",
                HealthCheckIntervalSeconds=30,
                HealthCheckTimeoutSeconds=5,
                HealthyThresholdCount=2,
                UnhealthyThresholdCount=2,
                Matcher={"HttpCode": "200"}
            )
            return response["TargetGroups"][0]["TargetGroupArn"]
        except ClientError as e:
            logger.error(f"Failed to create target group: {e}")
            raise

    def _create_task_definition(
        self,
        task_family: str,
        log_group_name: str
    ) -> str:
        """Create an ECS task definition."""
        try:
            response = self.ecs.register_task_definition(
                family=task_family,
                networkMode="awsvpc",
                requiresCompatibilities=["FARGATE"],
                cpu="256",
                memory="512",
                executionRoleArn=self.task_execution_role_arn,
                taskRoleArn=self.task_role_arn,
                containerDefinitions=[
                    {
                        "name": "backend",
                        "image": self.container_image,
                        "essential": True,
                        "portMappings": [
                            {
                                "containerPort": 8000,
                                "protocol": "tcp"
                            }
                        ],
                        "logConfiguration": {
                            "logDriver": "awslogs",
                            "options": {
                                "awslogs-group": log_group_name,
                                "awslogs-region": os.getenv("AWS_REGION", "ap-south-1"),
                                "awslogs-stream-prefix": "ecs"
                            }
                        },
                        "environment": [
                            {
                                "name": "AWS_REGION",
                                "value": os.getenv("AWS_REGION", "ap-south-1")
                            }
                        ]
                    }
                ]
            )
            return response["TaskDefinition"]["TaskDefinitionArn"]
        except ClientError as e:
            logger.error(f"Failed to create task definition: {e}")
            raise

    def _create_ecs_service(
        self,
        service_name: str,
        task_definition_arn: str,
        target_group_arn: str
    ) -> str:
        """Create an ECS service."""
        try:
            response = self.ecs.create_service(
                cluster=self.cluster_name,
                serviceName=service_name,
                taskDefinition=task_definition_arn,
                desiredCount=1,
                launchType="FARGATE",
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": self.subnet_ids,
                        "securityGroups": [self.security_group_id],
                        "assignPublicIp": "ENABLED"
                    }
                },
                loadBalancers=[
                    {
                        "targetGroupArn": target_group_arn,
                        "containerName": "backend",
                        "containerPort": 8000
                    }
                ],
                healthCheckGracePeriodSeconds=60
            )
            return response["Service"]["ServiceArn"]
        except ClientError as e:
            logger.error(f"Failed to create ECS service: {e}")
            raise

    def _add_listener_rule(self, preview_id: str, target_group_arn: str) -> str:
        """Add a listener rule to route traffic to the target group.
        
        Returns:
            Rule ARN for later cleanup
        """
        try:
            # Generate a unique priority (ALB supports 1-50000 inclusive)
            # Use hash to ensure consistency but add offset to avoid conflicts
            priority = abs(hash(preview_id)) % 49000 + 1000  # Generate priority between 1000-50000 (inclusive)

            # Check if rule with this priority exists and retry if needed
            max_retries = 10
            rule_arn = None
            for attempt in range(max_retries):
                try:
                    response = self.elbv2.create_rule(
                        ListenerArn=self.alb_listener_arn,
                        Priority=priority,
                        Conditions=[
                            {
                                "Field": "path-pattern",
                                "Values": [f"/preview-{preview_id}/*"]
                            }
                        ],
                        Actions=[
                            {
                                "Type": "forward",
                                "TargetGroupArn": target_group_arn
                            }
                        ]
                    )
                    rule_arn = response["Rules"][0]["RuleArn"]
                    break  # Success
                except ClientError as e:
                    if e.response["Error"]["Code"] == "PriorityInUse" and attempt < max_retries - 1:
                        # Try a different priority
                        priority = (priority + 1) % 49000 + 1000
                        continue
                    raise
            
            if not rule_arn:
                raise Exception("Failed to create listener rule after retries")
            
            return rule_arn
        except ClientError as e:
            logger.error(f"Failed to add listener rule: {e}")
            raise

    def _cleanup_on_failure(
        self,
        preview_id: str,
        target_group_arn: Optional[str],
        listener_rule_arn: Optional[str] = None
    ) -> None:
        """Clean up resources if creation fails."""
        service_name = f"preview-{preview_id}"

        # Delete listener rule first (must be deleted before target group)
        if listener_rule_arn:
            try:
                self.elbv2.delete_rule(RuleArn=listener_rule_arn)
            except ClientError:
                pass  # Rule might not exist

        # Delete service if it exists
        try:
            self.ecs.update_service(
                cluster=self.cluster_name,
                service=service_name,
                desiredCount=0
            )
            self.ecs.delete_service(
                cluster=self.cluster_name,
                service=service_name,
                force=True
            )
        except ClientError:
            pass  # Service might not exist

        # Delete target group if it exists
        if target_group_arn:
            try:
                self.elbv2.delete_target_group(TargetGroupArn=target_group_arn)
            except ClientError:
                pass  # Target group might not exist

    def get_service_url(self, alb_dns_name: str, preview_id: str) -> str:
        """
        Get the preview service URL.

        Args:
            alb_dns_name: DNS name of the ALB
            preview_id: Unique preview identifier

        Returns:
            Preview service URL
        """
        return f"http://{alb_dns_name}/preview-{preview_id}"

