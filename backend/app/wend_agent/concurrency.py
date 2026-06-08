"""Per-user concurrency cap via DynamoDB GSI count."""
from __future__ import annotations

import boto3
from fastapi import HTTPException, status

from .config import WendAgentConfig


def assert_within_cap(cfg: WendAgentConfig, user_id: str) -> None:
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    resp = ddb.query(
        TableName=cfg.table_name,
        IndexName="byUserId",
        KeyConditionExpression="userId = :u",
        FilterExpression="#s IN (:provisioning, :starting, :ready, :streaming)",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":u": {"S": user_id},
            ":provisioning": {"S": "PROVISIONING"},
            ":starting": {"S": "STARTING"},
            ":ready": {"S": "READY"},
            ":streaming": {"S": "STREAMING"},
        },
        Select="COUNT",
    )
    active = int(resp.get("Count", 0))
    if active >= cfg.max_concurrent_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Concurrent cloud-agent cap reached ({active}/{cfg.max_concurrent_per_user})",
            headers={"Retry-After": "60"},
        )
