"""Server-side Clerk Backend API client.

Reads + writes user private_metadata for per-user secrets that should
never reach the phone after upload: the Anthropic API key, the linked
GitHub installation id, the user's GitHub login.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import boto3
import httpx
from fastapi import HTTPException

from .config import WendAgentConfig

logger = logging.getLogger(__name__)

_secret_cache: dict[str, Any] = {}


def _clerk_secret_key(cfg: WendAgentConfig) -> str:
    cached = _secret_cache.get("clerk")
    if cached:
        return cached
    secret_id = os.getenv("CLERK_SECRET_KEY_SECRET", "/wend/clerk/secret-key")
    sm = boto3.client("secretsmanager", region_name=cfg.aws_region)
    resp = sm.get_secret_value(SecretId=secret_id)
    value = resp.get("SecretString") or resp["SecretBinary"].decode("utf-8")
    _secret_cache["clerk"] = value
    return value


@dataclass(frozen=True)
class UserMetadata:
    anthropic_api_key: str | None
    github_installation_id: int | None
    github_login: str | None
    claude_credentials_json: str | None  # Claude Code OAuth creds, subscription-billed


async def get_user_metadata(cfg: WendAgentConfig, user_id: str) -> UserMetadata:
    secret = _clerk_secret_key(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        r.raise_for_status()
    body = r.json()
    private = body.get("private_metadata") or {}
    return UserMetadata(
        anthropic_api_key=private.get("anthropic_api_key"),
        github_installation_id=private.get("github_installation_id"),
        github_login=private.get("github_login"),
        claude_credentials_json=private.get("claude_credentials_json"),
    )


async def patch_user_metadata(cfg: WendAgentConfig, user_id: str, patch: dict[str, Any]) -> None:
    secret = _clerk_secret_key(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.patch(
            f"https://api.clerk.com/v1/users/{user_id}/metadata",
            headers={"Authorization": f"Bearer {secret}"},
            json={"private_metadata": patch},
        )
        if r.status_code >= 400:
            logger.error("clerk patch failed %s: %s", r.status_code, r.text)
            r.raise_for_status()


def require_anthropic_key(meta: UserMetadata) -> str:
    """Backwards-compat helper used when an API key is the only auth path.
    The dispatch flow prefers Claude OAuth creds when present and only
    falls back to API key when no creds are set."""
    if not meta.anthropic_api_key:
        raise HTTPException(
            status_code=402,
            detail="Anthropic API key not set. Open Settings → Connect Anthropic on your phone to paste your key.",
        )
    return meta.anthropic_api_key


def require_billing_source(meta: UserMetadata) -> tuple[str, str | None, str | None]:
    """Return (mode, claude_creds, api_key) for the upcoming dispatch.

    Prefers Claude OAuth (subscription billing) when present; falls back
    to API key. Raises 402 if neither is configured."""
    if meta.claude_credentials_json:
        return ("claude_oauth", meta.claude_credentials_json, None)
    if meta.anthropic_api_key:
        return ("api_key", None, meta.anthropic_api_key)
    raise HTTPException(
        status_code=402,
        detail="No Anthropic billing source. Open Settings → Connect Anthropic (paste an API key) or Connect Claude (subscription via your Mac).",
    )


def require_github_install(meta: UserMetadata) -> int:
    if not meta.github_installation_id:
        raise HTTPException(
            status_code=409,
            detail="GitHub App not installed. Open Settings → Connect GitHub on your phone to install Wend Cloud on your account.",
        )
    return meta.github_installation_id
