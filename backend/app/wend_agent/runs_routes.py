"""GET /v1/runs?noteId=X — catch-up endpoint.

Phone calls this on note open to discover any cloud runs that finished
while it was offline. Returns the last N runs for the note, ordered
newest first. Auth: Clerk JWT; result filtered to the requesting user.
"""
from __future__ import annotations

import json
import os
from typing import Any

import boto3
from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import ClerkUser, get_current_user
from .config import WendAgentConfig

router = APIRouter(prefix="/v1/runs", tags=["wend-agent-runs"])


def _cfg() -> WendAgentConfig:
    return WendAgentConfig.from_env()


def _table_name() -> str:
    return os.getenv("WEND_RUNS_TABLE", "wend-runs")


def _decode_item(item: dict[str, Any]) -> dict[str, Any]:
    """Project the DDB shape down to the PersistedRun shape the mobile
    notes-storage layer expects."""
    def get_s(k: str) -> str: return item.get(k, {}).get("S", "")
    def get_n(k: str, default: float = 0) -> float:
        try: return float(item.get(k, {}).get("N", str(default)))
        except Exception: return default
    def get_ss(k: str) -> list[str]:
        raw = item.get(k, {}).get("SS", []) or []
        return [v for v in raw if v != "__none__"]

    tool_uses = get_ss("toolUses")

    tool_calls: list[Any] = []
    tool_calls_json = item.get("toolCallsJson", {}).get("S", "")
    if tool_calls_json:
        try:
            parsed = json.loads(tool_calls_json)
            if isinstance(parsed, list):
                tool_calls = parsed
        except Exception:
            tool_calls = []

    return {
        "runId": get_s("runId"),
        "noteId": get_s("noteId"),
        "createdAt": int(get_n("createdAt")),
        "response": get_s("response"),
        "sessionId": get_s("sessionId"),
        "status": get_s("status"),
        "durationMs": int(get_n("durationMs")),
        "costUsd": get_n("costUsd"),
        "toolUses": tool_uses,
        "toolCalls": tool_calls,
        "links": get_ss("links"),
        "filesChanged": get_ss("filesChanged"),
        "repo": get_s("repo"),
        "agentId": get_s("agentId"),
    }


@router.get("")
async def list_runs_for_note(
    noteId: str = Query(..., min_length=1, max_length=200),
    since: int | None = Query(default=None, description="ms epoch — return runs created after this"),
    limit: int = Query(default=20, ge=1, le=100),
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    expr_attrs = {":nid": {"S": noteId}, ":uid": {"S": user.user_id}}
    filter_expr = "userId = :uid"
    key_expr = "noteId = :nid"
    if since is not None:
        key_expr += " AND createdAt > :since"
        expr_attrs[":since"] = {"N": str(int(since))}

    try:
        resp = ddb.query(
            TableName=_table_name(),
            KeyConditionExpression=key_expr,
            FilterExpression=filter_expr,
            ExpressionAttributeValues=expr_attrs,
            ScanIndexForward=False,  # newest first
            Limit=limit,
        )
    except Exception as exc:
        raise HTTPException(500, f"runs query failed: {exc}")

    runs = [_decode_item(item) for item in resp.get("Items", [])]
    return {"runs": runs}
