"""Resolve a target repo for a cloud dispatch.

Server-side mirror of the Mac daemon's project indexer: given the
prompt and the user's accessible repos (via their GitHub App
installation), pick the repo this dispatch should target.

Heuristic (alpha):
  1. List repos the installation can see, sorted by pushed_at desc.
  2. Score each repo name (and its bare project segment) against the
     prompt text. Whole-word case-insensitive hits add weight.
  3. Highest scorer wins. Ties broken by recency.
  4. Zero hits → most-recently-pushed repo.

Returns (repo_full_name, source) where source is "auto" for a content
hit, "fallback" for the recency default.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import WendAgentConfig
from .github_app import _app_jwt

logger = logging.getLogger(__name__)

_repos_cache: dict[int, dict[str, Any]] = {}
_REPOS_TTL_SEC = 60


@dataclass(frozen=True)
class ResolvedRepo:
    full_name: str
    default_branch: str
    source: str  # "auto" | "fallback"
    confidence: float


async def _list_installation_repos(cfg: WendAgentConfig, installation_id: int) -> list[dict[str, Any]]:
    cached = _repos_cache.get(installation_id)
    now = time.time()
    if cached and now - cached["fetched_at"] < _REPOS_TTL_SEC:
        return cached["repos"]

    # Mint a fresh installation token to call /installation/repositories.
    # We don't reuse the dispatch-time token because that one is scoped to a
    # single repo; this listing needs the full installation scope.
    app_token = _app_jwt(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"permissions": {"contents": "read", "metadata": "read"}},
        )
        r.raise_for_status()
        install_token = r.json()["token"]

        rr = await client.get(
            "https://api.github.com/installation/repositories",
            headers={
                "Authorization": f"token {install_token}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 100},
        )
        rr.raise_for_status()
    repos = rr.json().get("repositories", [])
    repos.sort(key=lambda r: r.get("pushed_at", ""), reverse=True)
    _repos_cache[installation_id] = {"fetched_at": now, "repos": repos}
    return repos


_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _score(prompt: str, repo: dict[str, Any]) -> float:
    text = prompt.lower()
    full = str(repo.get("full_name", "")).lower()
    name = str(repo.get("name", "")).lower()
    tokens = {t.lower() for t in _WORD_RE.findall(name) if len(t) >= 3}
    tokens.add(name)
    tokens.add(full)
    score = 0.0
    for tok in tokens:
        if not tok:
            continue
        # Whole-word match adds 2, substring match adds 0.5.
        if re.search(rf"\b{re.escape(tok)}\b", text):
            score += 2.0
        elif tok in text:
            score += 0.5
    return score


async def resolve_repo(
    cfg: WendAgentConfig,
    installation_id: int,
    prompt: str,
) -> ResolvedRepo | None:
    """Returns None if the installation can't see any repos at all."""
    repos = await _list_installation_repos(cfg, installation_id)
    if not repos:
        return None

    best: tuple[float, dict[str, Any]] = (0.0, repos[0])
    for r in repos:
        s = _score(prompt, r)
        if s > best[0]:
            best = (s, r)

    score, picked = best
    if score > 0:
        return ResolvedRepo(
            full_name=picked["full_name"],
            default_branch=picked.get("default_branch", "main"),
            source="auto",
            confidence=min(1.0, score / 4.0),
        )
    # No textual hit — fall back to most recently pushed.
    return ResolvedRepo(
        full_name=repos[0]["full_name"],
        default_branch=repos[0].get("default_branch", "main"),
        source="fallback",
        confidence=0.0,
    )
