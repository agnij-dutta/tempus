"""Wend subscription tier + usage tracking.

Single source of truth: Clerk private_metadata.
  - subscription_tier: "free" | "pro" | "cloud_paygo"
  - subscription_current_period_end: ISO timestamp (set by Stripe webhook
    later; manually set during alpha)
  - subscription_status: "active" | "past_due" | "canceled"

Free tier: no Mac pair, no cloud dispatch. Editor only.
Pro tier: Mac pairing unlocked, unlimited Mac-route, 50 cloud dispatches
  bundled per calendar month, then $0.30 overage.
Cloud paygo: no Mac pair, every cloud dispatch is billed individually.

Usage tracking happens against the existing wend-runs table (counts rows
in the current calendar month for the requesting user via the byUserId
GSI). This avoids a second counter table at the cost of one Query per
dispatch decision.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Literal

import boto3
from fastapi import HTTPException

from .config import WendAgentConfig
from .clerk_client import _clerk_secret_key
import httpx


def paywalls_disabled() -> bool:
    """When True, the server treats every authenticated user as Pro and
    skips quota / gating checks. Used for the closed alpha while Stripe
    is being wired and for any future "free week" promotions."""
    return os.getenv("WEND_PAYWALLS_DISABLED", "").lower() in ("1", "true", "yes")

logger = logging.getLogger(__name__)

Tier = Literal["free", "pro", "cloud_paygo"]

PRO_CLOUD_QUOTA = 50  # included per calendar month
PAYGO_OVERAGE_USD_PER_DISPATCH = 0.30


@dataclass(frozen=True)
class Subscription:
    tier: Tier
    status: str  # "active" | "past_due" | "canceled" | "none"
    current_period_end: str | None
    cloud_used_this_month: int

    @property
    def is_paying(self) -> bool:
        return self.tier in ("pro", "cloud_paygo") and self.status == "active"

    @property
    def can_pair_mac(self) -> bool:
        return self.tier == "pro" and self.status == "active"

    @property
    def cloud_quota_remaining(self) -> int:
        if self.tier == "pro" and self.status == "active":
            return max(0, PRO_CLOUD_QUOTA - self.cloud_used_this_month)
        return 0  # paygo charges per-dispatch directly; free has none


async def _read_clerk_subscription(cfg: WendAgentConfig, user_id: str) -> dict:
    secret = _clerk_secret_key(cfg)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"https://api.clerk.com/v1/users/{user_id}",
            headers={"Authorization": f"Bearer {secret}"},
        )
        r.raise_for_status()
    return r.json().get("private_metadata") or {}


def _month_start_ms() -> int:
    now = time.gmtime()
    return int(time.mktime((now.tm_year, now.tm_mon, 1, 0, 0, 0, 0, 0, 0))) * 1000


def _count_cloud_runs_this_month(cfg: WendAgentConfig, user_id: str) -> int:
    """Count wend-runs rows for this user since the 1st of the current
    UTC month. Hits the byUserId GSI to avoid a full scan."""
    import os
    table = os.getenv("WEND_RUNS_TABLE", "wend-runs")
    ddb = boto3.client("dynamodb", region_name=cfg.aws_region)
    since_ms = _month_start_ms()
    try:
        resp = ddb.query(
            TableName=table,
            IndexName="byUserId",
            KeyConditionExpression="userId = :u",
            FilterExpression="createdAt >= :since",
            ExpressionAttributeValues={
                ":u": {"S": user_id},
                ":since": {"N": str(since_ms)},
            },
            Select="COUNT",
        )
        return int(resp.get("Count", 0))
    except Exception as exc:
        logger.warning("usage count query failed: %s", exc)
        return 0


async def get_subscription(cfg: WendAgentConfig, user_id: str) -> Subscription:
    if paywalls_disabled():
        used = _count_cloud_runs_this_month(cfg, user_id)
        return Subscription(
            tier="pro",
            status="active",
            current_period_end=None,
            cloud_used_this_month=used,
        )
    meta = await _read_clerk_subscription(cfg, user_id)
    tier: Tier = meta.get("subscription_tier") or "free"
    status = meta.get("subscription_status") or ("active" if tier == "free" else "none")
    cur_end = meta.get("subscription_current_period_end")
    used = _count_cloud_runs_this_month(cfg, user_id) if tier in ("pro", "cloud_paygo") else 0
    return Subscription(
        tier=tier,
        status=status,
        current_period_end=cur_end,
        cloud_used_this_month=used,
    )


def require_mac_pair_allowed(sub: Subscription) -> None:
    if paywalls_disabled():
        return
    if not sub.can_pair_mac:
        raise HTTPException(
            status_code=402,
            detail=(
                "Mac pairing is a Pro feature. Upgrade in Settings → Subscription "
                "to unlock unlimited Mac-route dispatches."
            ),
        )


def require_cloud_dispatch_allowed(sub: Subscription) -> None:
    if paywalls_disabled():
        return
    if sub.tier == "free":
        raise HTTPException(
            status_code=402,
            detail=(
                "Cloud dispatches require a Wend subscription. Open Settings → "
                "Subscription to upgrade to Pro (Mac + 50 cloud/mo included) or "
                "Cloud Pay-As-You-Go ($0.30 per dispatch)."
            ),
        )
    if sub.status != "active":
        raise HTTPException(
            status_code=402,
            detail="Your Wend subscription is not active. Update billing to continue dispatching.",
        )
    # Pro: 50 included, anything beyond is fine but tracked as overage.
    # We allow the dispatch and rely on monthly invoicing to bill overage.
    # Hard caps come later if abuse appears.
