"""Clerk session JWT validation. JWKS cached in-process for 10 minutes."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request, status
from jose import jwt  # python-jose

from .config import WendAgentConfig

logger = logging.getLogger(__name__)

_jwks_cache: dict[str, Any] = {"keys": None, "expires_at": 0.0}


@dataclass(frozen=True)
class ClerkUser:
    user_id: str
    raw_claims: dict[str, Any]


async def _fetch_jwks(url: str) -> list[dict[str, Any]]:
    now = time.time()
    if _jwks_cache["keys"] is not None and now < _jwks_cache["expires_at"]:
        return _jwks_cache["keys"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        keys = r.json().get("keys", [])
    _jwks_cache["keys"] = keys
    _jwks_cache["expires_at"] = now + 600
    return keys


def _config() -> WendAgentConfig:
    return WendAgentConfig.from_env()


async def get_current_user(request: Request, cfg: WendAgentConfig = Depends(_config)) -> ClerkUser:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = auth[len("Bearer ") :].strip()
    if not cfg.clerk_jwks_url or not cfg.clerk_issuer:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Clerk not configured")
    try:
        unverified = jwt.get_unverified_header(token)
        kid = unverified.get("kid")
        keys = await _fetch_jwks(cfg.clerk_jwks_url)
        key = next((k for k in keys if k.get("kid") == kid), None)
        if key is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown signing key")
        claims = jwt.decode(
            token, key,
            algorithms=[key.get("alg", "RS256")],
            issuer=cfg.clerk_issuer,
            options={"verify_aud": False},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("clerk verify failed: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no sub in token")
    return ClerkUser(user_id=user_id, raw_claims=claims)
