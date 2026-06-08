"""POST /v1/cloud-dispatch — spin up a wend-agent and stream its SSE back."""
from __future__ import annotations

import logging
from typing import Optional

import boto3
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .auth import ClerkUser, get_current_user
from .clerk_client import get_user_metadata, require_anthropic_key, require_github_install
from .concurrency import assert_within_cap
from .config import WendAgentConfig
from .provisioner import provision
from .proxy import proxy_dispatch

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/cloud-dispatch", tags=["wend-agent"])


class CloudDispatchRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=32_000)
    repo: str = Field(..., pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    ref: str = Field(default="main", max_length=200)
    sessionId: Optional[str] = None
    noteId: Optional[str] = None


def _cfg() -> WendAgentConfig:
    return WendAgentConfig.from_env()


@router.post("")
async def cloud_dispatch(
    request: Request,
    body: CloudDispatchRequest,
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    assert_within_cap(cfg, user.user_id)
    meta = await get_user_metadata(cfg, user.user_id)
    require_anthropic_key(meta)
    require_github_install(meta)
    handle = await provision(
        cfg,
        user_id=user.user_id,
        user_meta=meta,
        repo=body.repo,
        ref=body.ref,
        note_id=body.noteId,
    )
    forwarded = {"prompt": body.prompt, "sessionId": body.sessionId}
    return await proxy_dispatch(request, handle.tunnel_url, forwarded)


@router.post("/{agent_id}/abort", status_code=status.HTTP_202_ACCEPTED)
async def abort(
    agent_id: str,
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    item = ddb.get_item(TableName=cfg.table_name, Key={"agentId": {"S": agent_id}}).get("Item", {})
    if not item:
        raise HTTPException(404, "agent not found")
    if item.get("userId", {}).get("S") != user.user_id:
        raise HTTPException(403, "not your agent")
    task_arn = item.get("taskArn", {}).get("S")
    if not task_arn:
        return {"ok": True, "state": "not-started"}
    ecs = boto3.client("ecs", region_name=cfg.aws_region)
    ecs.stop_task(cluster=cfg.cluster_name, task=task_arn, reason="user abort")
    ddb.update_item(
        TableName=cfg.table_name,
        Key={"agentId": {"S": agent_id}},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": {"S": "TEARDOWN"}},
    )
    return {"ok": True}


@router.get("/{agent_id}/status")
async def get_status(
    agent_id: str,
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    item = ddb.get_item(TableName=cfg.table_name, Key={"agentId": {"S": agent_id}}).get("Item", {})
    if not item:
        raise HTTPException(404, "agent not found")
    if item.get("userId", {}).get("S") != user.user_id:
        raise HTTPException(403, "not your agent")
    return {
        "agentId": agent_id,
        "status": item.get("status", {}).get("S"),
        "tunnelUrl": item.get("tunnelUrl", {}).get("S"),
        "expiresAt": int(item.get("expiresAt", {}).get("N", "0")),
    }
