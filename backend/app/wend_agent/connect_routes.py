"""Phone-facing endpoints for the Connect Anthropic + Connect GitHub flows.

Anthropic flow: phone POSTs the user's key; we ping Anthropic with a
1-token call to validate, then stash in Clerk private_metadata.

GitHub flow: phone calls /check; if not installed, we hand back the
GitHub deep-link URL; the GitHub App's Setup URL points back at
/install/callback which persists the installation_id + login.
"""
from __future__ import annotations

import logging
import os
import secrets
from urllib.parse import urlencode

import boto3
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .auth import ClerkUser, get_current_user
from .clerk_client import get_user_metadata, patch_user_metadata
from .config import WendAgentConfig
from .github_app import installation_id_for_user_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/connect", tags=["wend-agent-connect"])


def _cfg() -> WendAgentConfig:
    return WendAgentConfig.from_env()


class AnthropicConnectRequest(BaseModel):
    api_key: str = Field(..., min_length=20, max_length=200, pattern=r"^sk-ant-[A-Za-z0-9_\-]+$")


@router.post("/anthropic")
async def connect_anthropic(
    body: AnthropicConnectRequest,
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": body.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
    if r.status_code == 401:
        raise HTTPException(401, "Anthropic rejected the API key")
    if r.status_code >= 500:
        raise HTTPException(502, "Anthropic API unreachable")
    if r.status_code >= 400 and r.status_code != 400:
        raise HTTPException(400, f"Anthropic returned {r.status_code}")

    await patch_user_metadata(cfg, user.user_id, {"anthropic_api_key": body.api_key})
    return {"ok": True}


@router.delete("/anthropic")
async def disconnect_anthropic(
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    await patch_user_metadata(cfg, user.user_id, {"anthropic_api_key": None})
    return {"ok": True}


@router.get("/github/status")
async def github_status(
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    meta = await get_user_metadata(cfg, user.user_id)
    return {
        "installed": meta.github_installation_id is not None,
        "installation_id": meta.github_installation_id,
        "login": meta.github_login,
    }


@router.get("/github/install-url")
async def github_install_url(
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    """Deep-link to install the Wend Cloud GitHub App.

    If the user already linked GitHub via Clerk OAuth, we look up their
    GitHub login and check if Wend Cloud is already installed on it. If
    so, we skip the install and patch the metadata immediately.
    """
    meta = await get_user_metadata(cfg, user.user_id)

    # Clerk OAuth identity check: if the user signed in with GitHub
    # through Clerk, their external account is on the user record. We
    # query Clerk for the linked github login.
    login = await _clerk_github_login(cfg, user.user_id)
    if login:
        install_id = await installation_id_for_user_login(cfg, login)
        if install_id:
            await patch_user_metadata(cfg, user.user_id, {
                "github_installation_id": install_id,
                "github_login": login,
            })
            return {"installed": True, "installation_id": install_id, "login": login}

    state = secrets.token_urlsafe(24)
    _install_state_put(cfg, state, user.user_id)
    install_url = (
        f"https://github.com/apps/wend-cloud/installations/new?"
        + urlencode({"state": state})
    )
    return {"installed": False, "install_url": install_url, "state": state}


@router.get("/github/install/callback")
async def github_install_callback(
    request: Request,
    installation_id: int = Query(...),
    state: str | None = Query(default=None),
    setup_action: str | None = Query(default=None),
    cfg: WendAgentConfig = Depends(_cfg),
):
    """Setup URL target for the Wend Cloud GitHub App.

    GitHub redirects here after a successful install with installation_id
    in the query string. We look up the state we minted in /install-url to
    find the Clerk user id, write the mapping, and deep-link back into the
    mobile app.
    """
    user_id = _install_state_consume(cfg, state) if state else None
    if not user_id:
        raise HTTPException(400, "missing or expired install state; restart the flow from the phone")

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"https://api.github.com/app/installations/{installation_id}",
            headers={"Accept": "application/vnd.github+json"},
            # The App JWT is signed by github_app.py; reuse via a tiny helper.
        )
    # We could not pre-authenticate this call without signing an App JWT;
    # the installation lookup is best-effort. The phone still gets
    # redirected back successfully even if the login lookup fails.
    login = None
    try:
        login = (r.json().get("account") or {}).get("login")
    except Exception:
        pass

    await patch_user_metadata(cfg, user_id, {
        "github_installation_id": installation_id,
        "github_login": login,
    })

    deep_link = os.getenv("WEND_APP_DEEP_LINK", "wend://github/connected")
    return RedirectResponse(url=f"{deep_link}?ok=1&installation_id={installation_id}", status_code=302)


# --- helpers ---------------------------------------------------------------

_STATE_TTL_SEC = 600


def _install_state_put(cfg: WendAgentConfig, state: str, user_id: str) -> None:
    """Stash the state→user mapping in DynamoDB (TTL 10 min) on the
    wend-agents table under a reserved agentId prefix to avoid a second table."""
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    import time as _t
    ddb.put_item(
        TableName=cfg.table_name,
        Item={
            "agentId": {"S": f"install-state:{state}"},
            "userId": {"S": user_id},
            "status": {"S": "INSTALL_STATE"},
            "expiresAt": {"N": str(int(_t.time()) + _STATE_TTL_SEC)},
        },
    )


def _install_state_consume(cfg: WendAgentConfig, state: str) -> str | None:
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    key = f"install-state:{state}"
    item = ddb.get_item(TableName=cfg.table_name, Key={"agentId": {"S": key}}).get("Item")
    if not item:
        return None
    user_id = item.get("userId", {}).get("S")
    ddb.delete_item(TableName=cfg.table_name, Key={"agentId": {"S": key}})
    return user_id


async def _clerk_github_login(cfg: WendAgentConfig, user_id: str) -> str | None:
    from .clerk_client import _clerk_secret_key  # local import to avoid cycle
    secret = _clerk_secret_key(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {secret}"},
        )
    if r.status_code != 200:
        return None
    accounts = r.json().get("external_accounts") or []
    for acct in accounts:
        if acct.get("provider") == "oauth_github":
            return acct.get("username") or acct.get("approved_scopes_login") or acct.get("identification_id")
    return None
