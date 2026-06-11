"""GET /v1/subscription/status — phone polls this on launch to mirror
subscription state into its local store."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .auth import ClerkUser, get_current_user
from .config import WendAgentConfig
from .subscription import (
    PRO_CLOUD_QUOTA,
    PAYGO_OVERAGE_USD_PER_DISPATCH,
    get_subscription,
)

router = APIRouter(prefix="/v1/subscription", tags=["wend-subscription"])


def _cfg() -> WendAgentConfig:
    return WendAgentConfig.from_env()


@router.get("/status")
async def status(
    user: ClerkUser = Depends(get_current_user),
    cfg: WendAgentConfig = Depends(_cfg),
):
    sub = await get_subscription(cfg, user.user_id)
    return {
        "tier": sub.tier,
        "status": sub.status,
        "current_period_end": sub.current_period_end,
        "cloud_used_this_month": sub.cloud_used_this_month,
        "cloud_quota_total": PRO_CLOUD_QUOTA if sub.tier == "pro" else 0,
        "cloud_quota_remaining": sub.cloud_quota_remaining,
        "can_pair_mac": sub.can_pair_mac,
        "overage_usd_per_dispatch": PAYGO_OVERAGE_USD_PER_DISPATCH,
    }
