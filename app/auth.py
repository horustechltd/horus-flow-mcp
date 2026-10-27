# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — API key auth, tier levels and rate limits.

Access levels (one matrix for every channel):
  level 0  FREE      demo, free, mcp_public, RapidAPI BASIC
  level 1  TRADER    trader (site, Stripe), builder, RapidAPI PRO
  level 2  PRO       pro (Stripe), ultra, RapidAPI ULTRA
  level 3  INSTITUTIONAL  institutional, mega, RapidAPI MEGA
  level 99 ADMIN     internal services only (never shipped to a browser)

Routes declare the minimum level with require_tier("FREE" | "BUILDER" | "PRO"), or with
tier_or_preview(...) to give lower plans a reduced live preview instead of a 403.
Upgrade messages name the plan in the caller's channel (RapidAPI PRO/ULTRA/MEGA or direct plans).
"""
import ipaddress
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Security, Request, Header, Depends, Response
from fastapi.security import APIKeyHeader

from app.config import API_KEYS, RATE_LIMITS, RAPIDAPI_PROXY_SECRET, DEMO_DAILY_LIMIT_PER_IP

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# In-memory rate limiter (single uvicorn worker)
_request_counts: dict = defaultdict(list)
_demo_daily: dict = defaultdict(int)  # (ip, yyyy-mm-dd) -> count

TIER_LEVELS = {
    # level 0
    "DEMO": 0,
    "FREE": 0,
    "MCP_PUBLIC": 0,
    "BASIC": 0,
    "RAPIDAPI_BASIC": 0,
    # level 1
    "BUILDER": 1,
    "TRADER": 1,
    "RAPIDAPI_PRO": 1,
    "RAPIDAPI_COMMERCIAL": 1,  # RapidAPI call without a plan header
    # level 2
    "PRO": 2,
    "ULTRA": 2,
    "RAPIDAPI_ULTRA": 2,
    # level 3
    "INSTITUTIONAL": 3,
    "MEGA": 3,
    "RAPIDAPI_MEGA": 3,
    # internal
    "ADMIN": 99,
}


def tier_level(tier: str) -> int:
    return TIER_LEVELS.get(str(tier or "FREE").upper(), 0)


RAPIDAPI_PRICING_URL = "https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence/pricing"
SITE_PRICING_URL = "https://flow.horustek.pro/#pricing"
# Plan names per channel: a RapidAPI subscriber can only buy RapidAPI plans
PLAN_NAMES = {"rapidapi": {0: "BASIC", 1: "PRO", 2: "ULTRA", 3: "MEGA"},
              "direct": {0: "FREE", 1: "TRADER", 2: "PRO", 3: "INSTITUTIONAL"}}  # the site's plans


def _channel(auth_data: dict) -> str:
    return "rapidapi" if str(auth_data.get("tier", "")).upper().startswith("RAPIDAPI_") else "direct"


def plan_name(auth_data: dict, level: int) -> str:
    """Name of the plan that gives `level`, in the caller's channel."""
    return PLAN_NAMES[_channel(auth_data)].get(level, "INSTITUTIONAL")


def your_plan(auth_data: dict) -> str:
    return str(auth_data.get("tier", "FREE")).upper().removeprefix("RAPIDAPI_")


def upgrade_block(auth_data: dict, level: int, unlocks: str, limits: Optional[str] = None) -> dict:
    """What the next plan adds and where to buy it. With `limits`, the response is a preview."""
    out = {"preview": True, "limits": limits} if limits else {}
    return out | {
        "required_plan": plan_name(auth_data, level),
        "your_plan": your_plan(auth_data),
        "unlocks": unlocks,
        "subscribe": RAPIDAPI_PRICING_URL if _channel(auth_data) == "rapidapi" else SITE_PRICING_URL,
    }


def upgrade_required(auth_data: dict, level: int, message: str, unlocks: str = "") -> HTTPException:
    return HTTPException(status_code=403, detail={"error": "upgrade_required", "message": message}
                         | upgrade_block(auth_data, level, unlocks or message))


def require_tier(min_tier_name: str):
    """FastAPI dependency that blocks callers below the required level."""
    min_level = TIER_LEVELS.get(min_tier_name.upper(), 0)

    def tier_dependency(auth_data: dict = Depends(verify_api_key)):
        if tier_level(auth_data.get("tier")) < min_level:
            plan = plan_name(auth_data, min_level)
            raise upgrade_required(auth_data, min_level, f"This endpoint needs the {plan} plan or higher.",
                                   "Access to this endpoint")
        return auth_data

    return tier_dependency


def tier_or_preview(min_tier_name: str):
    """Like require_tier, but lower plans get through with auth["preview"] = True: the route serves
    a small live slice plus an upgrade block instead of a 403, so a trial shows what the plan holds."""
    min_level = TIER_LEVELS.get(min_tier_name.upper(), 0)

    def preview_dependency(request: Request, auth_data: dict = Depends(verify_api_key)):
        preview = tier_level(auth_data.get("tier")) < min_level
        if preview:
            request.state.preview = True  # counted per plan and endpoint in rapidapi_stats
        return {**auth_data, "preview": preview, "min_level": min_level}

    return preview_dependency


# Cloudflare edge ranges (https://www.cloudflare.com/ips/, checked 2026-10-23)
_CLOUDFLARE_NETS = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
    "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
    "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
    "2a06:98c0::/29", "2c0f:f248::/32",
)]


def _is_cloudflare(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _CLOUDFLARE_NETS)


def _client_ip(request: Request) -> str:
    """
    Real visitor IP.
    uvicorn already replaces the peer with the X-Forwarded-For client set by the local nginx.
    Behind Cloudflare that client is a Cloudflare edge shared by many visitors, so the
    visitor comes from CF-Connecting-IP. The header is trusted only when the connecting
    host really is Cloudflare or loopback, so a direct caller cannot spoof it.
    """
    peer = request.client.host if request.client else "unknown"
    if peer in ("127.0.0.1", "::1") or _is_cloudflare(peer):
        real = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Real-IP")
        if real:
            return real.strip()
    return peer


def _cleanup_old_requests(bucket: str):
    now = time.time()
    _request_counts[bucket] = [t for t in _request_counts[bucket] if now - t < 60]


def _enforce_rate_limit(bucket: str, tier: str):
    _cleanup_old_requests(bucket)
    limit = RATE_LIMITS.get(tier.lower(), 30)
    if len(_request_counts[bucket]) >= limit:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit_exceeded", "limit": f"{limit} requests/minute", "tier": tier},
        )
    _request_counts[bucket].append(time.time())
    return limit


def _daily_quota_exceeded(tier: str, daily_limit: int) -> HTTPException:
    """The moment a subscriber needs more than the plan gives: say what happened, when it resets, and what is next."""
    from app.database import DAILY_LIMITS
    now = datetime.now(timezone.utc)
    reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    wait = int((reset - now).total_seconds())
    level = min(tier_level(tier) + 1, 3)
    plan = PLAN_NAMES["direct"][level]
    nxt = DAILY_LIMITS.get(plan.lower(), 0)
    detail = {
        "error": "daily_quota_exceeded",
        "message": (f"Your {tier.upper()} plan allows {daily_limit:,} calls a day and today's are used. "
                    f"The quota resets at 00:00 UTC, in {wait // 3600} h {wait % 3600 // 60} min. "
                    f"The {plan} plan allows {nxt:,} calls a day."),
        "daily_limit": daily_limit,
        "resets_at_utc": reset.isoformat(),
        "retry_after_seconds": wait,
    } | upgrade_block({"tier": tier}, level, f"{nxt:,} calls a day" + (
        ", flow history, the full market scanner, the event feed, climate, ignitions and US equity flow" if level == 1 else ""))
    return HTTPException(status_code=429, detail=detail,
                         headers={"Retry-After": str(wait), "X-RateLimit-Limit": str(daily_limit), "X-RateLimit-Remaining": "0"})


async def verify_api_key(
    request: Request,
    response: Response,
    api_key: str = Security(api_key_header),
    x_rapidapi_proxy_secret: Optional[str] = Header(None),
) -> dict:
    """
    Verify the caller and enforce rate limits.
    Order: RapidAPI gateway -> X-API-Key header -> ?key= param -> cookie.
    Returns {"key": str, "tier": str}.
    """
    # 1. RapidAPI gateway (RapidAPI handles billing and quotas)
    if RAPIDAPI_PROXY_SECRET and x_rapidapi_proxy_secret == RAPIDAPI_PROXY_SECRET:
        subscriber = request.headers.get("x-rapidapi-user", "rapidapi-subscriber")
        plan = request.headers.get("x-rapidapi-subscription", "").upper()
        tier = f"RAPIDAPI_{plan}" if plan else "RAPIDAPI_COMMERCIAL"
        if tier not in TIER_LEVELS:
            tier = "RAPIDAPI_BASIC"
        # Read by the usage middleware (app/rapidapi_stats.py). The raw plan name is kept so
        # custom RapidAPI plan names show up in the counters even if they map to BASIC.
        request.state.rapidapi = {"plan": plan or "NONE", "tier": tier, "user": subscriber}
        return {"key": f"rapidapi:{subscriber}", "tier": tier}

    if not api_key:
        api_key = request.query_params.get("key", "")
    if not api_key:
        api_key = request.cookies.get("horus_api_key", "")
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={"error": "missing_api_key", "hint": "Send the X-API-Key header or ?key= parameter"},
        )

    # 2. Static keys from the environment, then subscriber keys from the database
    tier = API_KEYS.get(api_key)
    key_info = None
    if not tier:
        from app.database import get_key_info
        key_info = get_key_info(api_key)
        if key_info:
            tier = key_info["tier"]
    if not tier:
        raise HTTPException(status_code=403, detail={"error": "invalid_api_key"})

    tier = str(tier).lower()

    # 3. Public demo key: limited per client IP (per minute and per day)
    if tier == "demo":
        ip = _client_ip(request)
        limit = _enforce_rate_limit(f"demo:{ip}", tier)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _demo_daily[(ip, day)] += 1
        if _demo_daily[(ip, day)] > DEMO_DAILY_LIMIT_PER_IP:
            raise HTTPException(status_code=429, detail={"error": "demo_daily_quota_exceeded"})
        if len(_demo_daily) > 50000:  # keep memory bounded
            for k in [k for k in _demo_daily if k[1] != day]:
                _demo_daily.pop(k, None)
        response.headers["X-RateLimit-Limit"] = str(limit)
        return {"key": f"demo:{ip}", "tier": "DEMO"}

    # 4. Per-key rate limit
    limit = _enforce_rate_limit(api_key, tier)

    # 5. Daily quota for subscriber keys
    if key_info:
        from app.database import get_daily_usage
        daily_limit = key_info.get("daily_limit", 100)
        usage_today = get_daily_usage(api_key)
        if usage_today >= daily_limit:
            raise _daily_quota_exceeded(tier, daily_limit)
        request.state.api_key = api_key
        response.headers["X-RateLimit-Limit"] = str(daily_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, daily_limit - usage_today - 1))
    else:
        response.headers["X-RateLimit-Limit"] = f"{limit}/min"

    return {"key": api_key, "tier": tier.upper()}
