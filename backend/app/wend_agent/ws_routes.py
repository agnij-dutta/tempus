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
from .subscription import get_subscription, require_cloud_dispatch_allowed
from .concurrency import assert_within_cap
from .config import WendAgentConfig
from .provisioner import provision
from .repo_resolver import resolve_repo
from .auth import _fetch_jwks  # reuse JWKS cache

# python-jose may not be importable in every environment; alias the
# decode call so test patches can intercept.
from jose import jwt as _jwt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["wend-agent-ws"])


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


@router.post("/events")
async def ws_events_entry(request: Request):
    """AWS Lambda Web Adapter forwards every API Gateway WebSocket
    invocation here. The route key is in the body's requestContext.
    We dispatch to the per-route handlers below."""
    body = await request.body()
    event = _ws_event(body)
    route_key = (event.get("requestContext") or {}).get("routeKey", "")
    if route_key == "$connect":
        return await _handle_ws_connect(event)
    if route_key == "$disconnect":
        return await _handle_ws_disconnect(event)
    if route_key == "dispatch":
        return await _handle_ws_dispatch(event)
    if route_key == "abort":
        return await _handle_ws_abort(event)
    # $default catch-all
    return {"statusCode": 400, "body": json.dumps({"error": "unknown route", "routeKey": route_key})}


async def _handle_ws_connect(event: dict):
    cfg = _cfg()
    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId") or "unknown"

    query = event.get("queryStringParameters") or {}
    token = query.get("token") or query.get("authorization")
    if not token:
        return {"statusCode": 401, "body": "missing token query parameter"}
    if token.lower().startswith("bearer "):
        token = token[len("Bearer "):]
    try:
        user_id = await _validate_token(token, cfg)
    except HTTPException as exc:
        return {"statusCode": exc.status_code, "body": str(exc.detail)}

    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    ddb.put_item(
        TableName=_cfg_table_name(),
        Item={
            "connectionId": {"S": connection_id},
            "userId": {"S": user_id},
            "connectedAt": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            "expiresAt": {"N": str(int(time.time()) + 7200)},
        },
    )
    logger.info("ws $connect ok connection=%s user=%s", connection_id, user_id)
    return {"statusCode": 200, "body": ""}


async def _handle_ws_disconnect(event: dict):
    cfg = _cfg()
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


async def _handle_ws_abort(event: dict):
    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId")
    logger.info("ws abort received from %s", connection_id)
    return {"statusCode": 200, "body": ""}


async def _handle_ws_dispatch(event: dict):
    cfg = _cfg()
    rc = event.get("requestContext", {})
    connection_id = rc.get("connectionId")
    if not connection_id:
        return {"statusCode": 400, "body": "no connectionId in request context"}

    payload_raw = event.get("body") or "{}"
    try:
        payload = json.loads(payload_raw)
    except Exception:
        return {"statusCode": 400, "body": "invalid payload JSON"}

    user_id = _user_id_for_connection(cfg, connection_id)
    if not user_id:
        _post_to_connection(cfg, event, connection_id, {
            "event": "stderr",
            "data": json.dumps("connection not authenticated"),
        })
        _post_to_connection(cfg, event, connection_id, {"event": "done", "data": "{\"code\":-1}"})
        return {"statusCode": 401, "body": "connection not authenticated"}

    prompt = (payload.get("prompt") or "").strip()
    explicit_repo = (payload.get("repo") or "").strip()
    explicit_ref = (payload.get("ref") or "").strip() or None
    note_id = payload.get("noteId") or payload.get("note_id")
    if not prompt:
        _push_error(cfg, event, connection_id, "prompt required")
        return {"statusCode": 400, "body": "prompt required"}

    try:
        sub = await get_subscription(cfg, user_id)
        require_cloud_dispatch_allowed(sub)
        assert_within_cap(cfg, user_id)
        meta = await get_user_metadata(cfg, user_id)
        require_anthropic_key(meta)
        require_github_install(meta)
    except HTTPException as exc:
        _push_error(cfg, event, connection_id, str(exc.detail))
        return {"statusCode": exc.status_code, "body": str(exc.detail)}

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
            msg = "No repos accessible to the Wend Cloud install. Open Settings → Connect GitHub and grant access to at least one repo."
            _push_error(cfg, event, connection_id, msg)
            return {"statusCode": 409, "body": msg}
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
        push_token=payload.get("pushToken") or payload.get("push_token"),
        note_title=payload.get("noteTitle") or payload.get("note_title"),
    )
    _post_to_connection(cfg, event, connection_id, _ack_frame(handle.agent_id, repo))
    return {"statusCode": 200, "body": ""}


# ---- helpers ----


def _push_error(cfg: WendAgentConfig, event: dict, connection_id: str, message: str) -> None:
    """Push a stderr+done frame pair to the connection so the phone's
    cloudDispatch consumer surfaces the error and closes the WS cleanly."""
    _post_to_connection(cfg, event, connection_id, {
        "event": "stderr", "data": json.dumps(message),
    })
    _post_to_connection(cfg, event, connection_id, {
        "event": "done", "data": "{\"code\":-1}",
    })

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
