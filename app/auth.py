# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — Simple API Key Auth
"""
import time
from collections import defaultdict
from fastapi import HTTPException, Security, Request, Header, Depends, Response
from typing import Optional
from fastapi.security import APIKeyHeader
from app.config import API_KEYS, RATE_LIMITS, RAPIDAPI_PROXY_SECRET

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Simple in-memory rate limiter (MVP — upgrade to Redis later)
_request_counts: dict = defaultdict(list)

# Tier Hierarchy
TIER_LEVELS = {
    "FREE": 0,
    "BASIC": 1,
    "TRADER": 1,
    "PRO": 2,
    "ULTRA": 3,
    "MEGA": 4,
    "INSTITUTIONAL": 5,
    "ADMIN": 99,
    "RAPIDAPI_COMMERCIAL": 4 # Fallback if header missing
}

def require_tier(min_tier_name: str):
    """FastAPI Dependency to block users on lower subscription tiers."""
    def tier_dependency(auth_data: dict = Depends(verify_api_key)):
        user_tier = str(auth_data.get("tier", "FREE")).upper()
        user_level = TIER_LEVELS.get(user_tier, 0)
        min_level = TIER_LEVELS.get(min_tier_name.upper(), 0)
        
        if user_level < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"Upgrade Required: This endpoint requires a '{min_tier_name}' subscription or higher. Your current plan is '{user_tier}'."
            )
        return auth_data
    return tier_dependency



def _cleanup_old_requests(key: str):
    """Remove requests older than 60 seconds"""
    now = time.time()
    _request_counts[key] = [t for t in _request_counts[key] if now - t < 60]


async def verify_api_key(
    request: Request,
    response: Response,
    api_key: str = Security(api_key_header),
    x_rapidapi_proxy_secret: Optional[str] = Header(None)
) -> dict:
    """
    Verify API key and enforce rate limits. Handles RapidAPI commercial traffic bypassing internal rate-limits.
    Also supports key via query param (?key=xxx) or cookie for dashboard access through Cloudflare.
    Returns: {"key": str, "tier": str}
    """
    
    # 1. RapidAPI Commercial Gateway (V.I.P Lane)
    if RAPIDAPI_PROXY_SECRET and x_rapidapi_proxy_secret == RAPIDAPI_PROXY_SECRET:
        # RapidAPI already handled billing and rate-limiting! Bypass internal rate limits.
        subscriber = request.headers.get("x-rapidapi-user", "rapidapi-subscriber")
        # Read the exact RapidAPI Subscription Plan name (BASIC, PRO, ULTRA, MEGA)
        # Fallback to BASIC if the header is somehow missing to restrict premium endpoints
        sub_tier = request.headers.get("x-rapidapi-subscription", "BASIC").upper()
        return {"key": subscriber, "tier": sub_tier}

    # 2. Fallback: check query param or cookie if header is missing (Cloudflare dashboard fix)
    if not api_key:
        api_key = request.query_params.get("key", "")
    if not api_key:
        api_key = request.cookies.get("horus_api_key", "")

    # 3. Local/Direct Edge Proof Dashboard (Standard Flow)
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={"error": "Missing API key or Proxy Secret", "hint": "Add X-API-Key header or ?key= param"}
        )

    tier = API_KEYS.get(api_key)
    key_info = None
    
    # Database lookup for subscriber-generated keys (hf_xxx)
    if not tier:
        from app.database import get_key_info
        key_info = get_key_info(api_key)
        if key_info:
            tier = key_info["tier"]

    # Marketing Gate Trick: If the user pastes a RapidAPI-like key (50 chars) in the dashboard,
    # we don't have it in our local DB, but we allow it as a "free" tier to unlock the dashboard UI.
    if not tier and len(api_key) >= 40 and "sh" in api_key:
        tier = "free"
        
    if not tier:
        raise HTTPException(
            status_code=403,
            detail={"error": "Invalid API key"}
        )

    # Rate limiting (Per Minute)
    _cleanup_old_requests(api_key)
    limit = RATE_LIMITS.get(tier, 10)

    if len(_request_counts[api_key]) >= limit:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": f"{limit} requests/minute",
                "tier": tier,
                "upgrade_hint": "Contact us for higher limits"
            }
        )

    _request_counts[api_key].append(time.time())

    # Daily Limits and DB Logging
    daily_limit = 100
    if key_info:
        daily_limit = key_info.get("daily_limit", 100)
        from app.database import get_daily_usage, log_usage
        usage_today = get_daily_usage(api_key)
        if usage_today >= daily_limit:
            raise HTTPException(
                status_code=429,
                detail={"error": "Daily quota exceeded. Please upgrade your plan."}
            )
        request.state.api_key = api_key
        remaining = max(0, daily_limit - usage_today - 1)
        response.headers["X-RateLimit-Limit"] = str(daily_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
    else:
        # For statically defined API keys in config
        response.headers["X-RateLimit-Limit"] = str(9999)
        response.headers["X-RateLimit-Remaining"] = str(9999)

    return {"key": api_key, "tier": tier}
