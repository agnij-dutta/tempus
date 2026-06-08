"""GitHub App installation-token minting. PEM lives in AWS Secrets Manager."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import boto3
import httpx
from jose import jwt

from .config import WendAgentConfig

logger = logging.getLogger(__name__)

_private_key_cache: dict[str, Any] = {"key": None, "fetched_at": 0.0}
_installation_id_cache: dict[str, int] = {}


def _load_private_key(cfg: WendAgentConfig) -> str:
    now = time.time()
    if _private_key_cache["key"] and now - _private_key_cache["fetched_at"] < 3600:
        return _private_key_cache["key"]
    secrets = boto3.client("secretsmanager", region_name=cfg.aws_region)
    resp = secrets.get_secret_value(SecretId=cfg.github_app_private_key_secret)
    pem = resp.get("SecretString") or resp["SecretBinary"].decode("utf-8")
    _private_key_cache["key"] = pem
    _private_key_cache["fetched_at"] = now
    return pem


def _app_jwt(cfg: WendAgentConfig) -> str:
    now = int(time.time())
    payload = {"iat": now - 30, "exp": now + 540, "iss": cfg.github_app_id}
    return jwt.encode(payload, _load_private_key(cfg), algorithm="RS256")


async def _installation_id(cfg: WendAgentConfig, repo: str) -> int:
    if repo in _installation_id_cache:
        return _installation_id_cache[repo]
    app_token = _app_jwt(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"https://api.github.com/repos/{repo}/installation",
            headers={
                "Authorization": f"Bearer {app_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        r.raise_for_status()
    install_id = int(r.json()["id"])
    _installation_id_cache[repo] = install_id
    return install_id


@dataclass(frozen=True)
class InstallationToken:
    token: str
    expires_at: str


async def mint_installation_token(cfg: WendAgentConfig, repo: str) -> InstallationToken:
    """Mint a short-lived installation token scoped to a single repo, contents:read."""
    owner, name = repo.split("/", 1)
    install_id = await _installation_id(cfg, repo)
    app_token = _app_jwt(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"https://api.github.com/app/installations/{install_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"repositories": [name], "permissions": {"contents": "read"}},
        )
        r.raise_for_status()
    body = r.json()
    return InstallationToken(token=body["token"], expires_at=body["expires_at"])
