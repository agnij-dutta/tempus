#!/usr/bin/env bash
# Manually promote/demote a Wend user during alpha (before Stripe wires
# up the real subscription lifecycle).
#
# Usage:
#   CLERK_SECRET_KEY=sk_test_... ./scripts/flip-subscription.sh <user_id> <tier>
#
# tier ∈ { free, pro, cloud_paygo }
#
# Sets:
#   private_metadata.subscription_tier
#   private_metadata.subscription_status = "active" (auto)
#   private_metadata.subscription_current_period_end = 30 days from now

set -euo pipefail

USER_ID="${1:?user_id required}"
TIER="${2:?tier required: free|pro|cloud_paygo}"

case "$TIER" in
  free|pro|cloud_paygo) ;;
  *) echo "tier must be one of: free, pro, cloud_paygo" >&2; exit 1 ;;
esac

if [[ -z "${CLERK_SECRET_KEY:-}" ]]; then
  echo "CLERK_SECRET_KEY env var required" >&2
  exit 1
fi

PERIOD_END=$(date -u -v+30d +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -d "+30 days" +"%Y-%m-%dT%H:%M:%SZ")

BODY=$(cat <<JSON
{
  "private_metadata": {
    "subscription_tier": "${TIER}",
    "subscription_status": "active",
    "subscription_current_period_end": "${PERIOD_END}"
  }
}
JSON
)

curl -sS -X PATCH "https://api.clerk.com/v1/users/${USER_ID}/metadata" \
  -H "Authorization: Bearer ${CLERK_SECRET_KEY}" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq -r '"Promoted " + .id + " to tier " + .private_metadata.subscription_tier'
