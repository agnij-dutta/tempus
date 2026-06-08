"""API Gateway WebSocket route handlers.

API Gateway invokes the Lambda once per WS event ($connect, $disconnect,
dispatch, abort). Events arrive as HTTP POSTs with the routing data
under requestContext. We expose them as FastAPI routes the LWA adapter
will dispatch into based on the path mapping API Gateway uses.

API Gateway WebSocket integration sends every route to the same Lambda
backend at a path matching the route key (after the $ replaced). The
LWA adapter forwards the incoming POST body to the Lambda. We sniff
the requestContext to figure out which route fired.

Auth: Clerk JWT comes in the connect URL query string. We validate it
once at $connect, store connectionId → userId. Subsequent dispatch
messages on the same connection inherit that user.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import boto3
from fastapi import APIRouter, HTTPException, Request

from .clerk_client import get_user_metadata, require_anthropic_key, require_github_install
from .concurrency import assert_within_cap
from .config import WendAgentConfig
from .provisioner import provision
from .repo_resolver import resolve_repo
from .auth import _fetch_jwks  # reuse JWKS cache

# python-jose may not be importable in every environment; alias the
# decode call so test patches can intercept.
from jose import jwt as _jwt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["wend-agent-ws"])


def _cfg() -> WendAgentConfig:
    return WendAgentConfig.from_env()


def _ws_event(request_body: bytes) -> dict[str, Any]:
    try:
        return json.loads(request_body or b"{}")
    except Exception:
        return {}


async def _validate_token(token: str, cfg: WendAgentConfig) -> str:
    if not cfg.clerk_jwks_url or not cfg.clerk_issuer:
        raise HTTPException(500, "Clerk not configured")
    try:
        header = _jwt.get_unverified_header(token)
    except Exception:
        raise HTTPException(401, "invalid token header")
    keys = await _fetch_jwks(cfg.clerk_jwks_url)
    key = next((k for k in keys if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise HTTPException(401, "unknown signing key")
    try:
        claims = _jwt.decode(
            token, key,
            algorithms=[key.get("alg", "RS256")],
            issuer=cfg.clerk_issuer,
            options={"verify_aud": False},
        )
    except Exception:
        raise HTTPException(401, "invalid token")
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "no sub")
    return user_id


@router.post("/connect")
async def ws_connect(request: Request):
    """$connect handler. The Lambda receives the API Gateway event with the
    Clerk token in the query string. We register connectionId → userId."""
    cfg = _cfg()
    body = await request.body()
    event = _ws_event(body)
    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId")
    if not connection_id:
        connection_id = request.headers.get("x-apigw-connection-id")

    query = event.get("queryStringParameters") or {}
    token = query.get("token") or query.get("authorization")
    if not token:
        raise HTTPException(401, "missing token query parameter")
    if token.lower().startswith("bearer "):
        token = token[len("Bearer "):]
    user_id = await _validate_token(token, cfg)

    table = _cfg_table_name()
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    ddb.put_item(
        TableName=table,
        Item={
            "connectionId": {"S": connection_id or "unknown"},
            "userId": {"S": user_id},
            "connectedAt": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            "expiresAt": {"N": str(int(time.time()) + 7200)},
        },
    )
    return {"statusCode": 200, "body": ""}


@router.post("/disconnect")
async def ws_disconnect(request: Request):
    cfg = _cfg()
    body = await request.body()
    event = _ws_event(body)
    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId")
    if not connection_id:
        return {"statusCode": 200, "body": ""}
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    try:
        ddb.delete_item(
            TableName=_cfg_table_name(),
            Key={"connectionId": {"S": connection_id}},
        )
    except Exception as exc:
        logger.warning("ws disconnect cleanup failed: %s", exc)
    return {"statusCode": 200, "body": ""}


@router.post("/dispatch")
async def ws_dispatch(request: Request):
    """Dispatch route: spawn a wend-agent and let the container stream
    events back to the connection."""
    cfg = _cfg()
    body = await request.body()
    event = _ws_event(body)
    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId")
    if not connection_id:
        raise HTTPException(400, "no connectionId in request context")

    # The user payload is in event['body'] for WS routes (string, JSON-encoded).
    payload_raw = event.get("body") or "{}"
    try:
        payload = json.loads(payload_raw)
    except Exception:
        raise HTTPException(400, "invalid payload JSON")

    user_id = _user_id_for_connection(cfg, connection_id)
    if not user_id:
        raise HTTPException(401, "connection not authenticated")

    prompt = (payload.get("prompt") or "").strip()
    explicit_repo = (payload.get("repo") or "").strip()
    explicit_ref = (payload.get("ref") or "").strip() or None
    note_id = payload.get("noteId") or payload.get("note_id")
    if not prompt:
        raise HTTPException(400, "prompt required")

    assert_within_cap(cfg, user_id)
    meta = await get_user_metadata(cfg, user_id)
    require_anthropic_key(meta)
    require_github_install(meta)

    if explicit_repo:
        # Caller pinned a specific repo on this note (e.g. via long-press
        # send). Honor it as-is.
        repo = explicit_repo
        ref = explicit_ref or "main"
        route_source = "pinned"
        route_conf = 1.0
    else:
        # Server-side resolution against the installation's visible repos.
        resolved = await resolve_repo(cfg, meta.github_installation_id or 0, prompt)
        if resolved is None:
            raise HTTPException(409, "No repos accessible to the Wend Cloud install. Open Settings → Connect GitHub and grant access to at least one repo.")
        repo = resolved.full_name
        ref = explicit_ref or resolved.default_branch
        route_source = resolved.source  # "auto" | "fallback"
        route_conf = resolved.confidence

    # Emit a route event over the WS so the phone can render its project
    # chip before the container even starts. Mirrors the Mac daemon's
    # SSE behaviour. Container will re-emit its own route event when it
    # boots; the phone takes whichever lands first.
    _post_to_connection(cfg, event, connection_id, {
        "event": "route",
        "data": json.dumps({
            "name": repo.split("/")[-1],
            "cwd": f"/workspace ({repo})",
            "source": route_source,
            "confidence": route_conf,
        }),
    })

    handle = await provision(
        cfg,
        user_id=user_id,
        user_meta=meta,
        repo=repo,
        ref=ref,
        note_id=note_id,
        ws_connection_id=connection_id,
        ws_callback_url=_ws_callback_url(event),
        prompt=prompt,
        session_id=payload.get("sessionId") or payload.get("session_id"),
    )
    _post_to_connection(cfg, event, connection_id, _ack_frame(handle.agent_id, repo))
    return {"statusCode": 200, "body": ""}


@router.post("/default")
async def ws_default(request: Request):
    """Catch-all for unhandled action values."""
    return {"statusCode": 400, "body": "unknown action"}


# ---- helpers ----

def _cfg_table_name() -> str:
    import os
    return os.getenv("WEND_WS_CONNECTIONS_TABLE", "wend-ws-connections")


def _user_id_for_connection(cfg: WendAgentConfig, connection_id: str) -> str | None:
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    item = ddb.get_item(
        TableName=_cfg_table_name(),
        Key={"connectionId": {"S": connection_id}},
    ).get("Item", {})
    return item.get("userId", {}).get("S")


def _ws_callback_url(event: dict[str, Any]) -> str:
    rc = event.get("requestContext", {})
    domain = rc.get("domainName", "")
    stage = rc.get("stage", "prod")
    if not domain:
        import os
        api_id = os.getenv("WEND_WS_API_ID", "")
        region = os.getenv("AWS_REGION_OVERRIDE", "us-east-1")
        domain = f"{api_id}.execute-api.{region}.amazonaws.com"
    return f"https://{domain}/{stage}"


def _post_to_connection(cfg: WendAgentConfig, event: dict[str, Any], connection_id: str, body: dict[str, Any]) -> None:
    url = _ws_callback_url(event)
    apigw = boto3.client("apigatewaymanagementapi", region_name=cfg.aws_region, endpoint_url=url)
    try:
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(body).encode("utf-8"),
        )
    except Exception as exc:
        logger.warning("post_to_connection failed: %s", exc)


def _ack_frame(agent_id: str, repo: str) -> dict[str, Any]:
    return {
        "event": "ack",
        "agentId": agent_id,
        "repo": repo,
        "ts": int(time.time()),
    }
