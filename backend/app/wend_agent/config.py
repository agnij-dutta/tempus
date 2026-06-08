"""Runtime config sourced from environment; populated by Terraform outputs at deploy."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WendAgentConfig:
    aws_region: str
    cluster_name: str
    task_definition_arn: str
    table_name: str
    security_group_id: str
    subnet_ids: list[str]
    max_concurrent_per_user: int
    idle_timeout_sec: int
    github_app_id: str
    github_app_private_key_secret: str
    anthropic_key_secret: str
    clerk_jwks_url: str
    clerk_issuer: str

    @classmethod
    def from_env(cls) -> "WendAgentConfig":
        return cls(
            aws_region=os.getenv("AWS_REGION", "ap-south-1"),
            cluster_name=os.getenv("ECS_CLUSTER_NAME", "tempus-cluster"),
            task_definition_arn=os.getenv("WEND_AGENT_TASK_DEF", ""),
            table_name=os.getenv("WEND_AGENT_TABLE", "wend-agents"),
            security_group_id=os.getenv("WEND_AGENT_SG", ""),
            subnet_ids=[s for s in os.getenv("SUBNET_IDS", "").split(",") if s],
            max_concurrent_per_user=int(os.getenv("WEND_AGENT_MAX_CONCURRENT", "2")),
            idle_timeout_sec=int(os.getenv("WEND_AGENT_IDLE_TIMEOUT_SEC", "900")),
            github_app_id=os.getenv("GITHUB_APP_ID", ""),
            github_app_private_key_secret=os.getenv("GITHUB_APP_PRIVATE_KEY_SECRET", "/wend/github-app/private-key"),
            anthropic_key_secret=os.getenv("ANTHROPIC_KEY_SECRET", "/wend/anthropic/api-key"),
            clerk_jwks_url=os.getenv("CLERK_JWKS_URL", ""),
            clerk_issuer=os.getenv("CLERK_ISSUER", ""),
        )
