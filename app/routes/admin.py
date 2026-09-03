# -*- coding: utf-8 -*-
"""
Horus Flow — Admin Routes (Secure)
3-Layer Security: JWT → DB Admin Check → IP Logging
"""
import os
import csv
import io
import logging
import time
from datetime import datetime
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.database import (
    get_user_by_id, get_all_users, get_admin_stats,
    upgrade_user_tier, toggle_user_active, get_all_users_for_export,
    get_user_full_details
)
from app.routes.auth import decode_jwt

logger = logging.getLogger("Admin")

router_admin = APIRouter()

# Rate limiting for admin endpoints
_admin_rate: dict = defaultdict(list)
ADMIN_RATE_LIMIT = 60  # requests per minute

# Admin action audit log (in-memory + logged)
_audit_log: list = []

# ============ Security Layer ============

def _get_client_ip(request: Request) -> str:
    """Get real client IP, accounting for proxies."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def _rate_check_admin(ip: str):
    """Rate limit admin endpoints: 60 req/min."""
    now = time.time()
    _admin_rate[ip] = [t for t in _admin_rate[ip] if now - t < 60]
    if len(_admin_rate[ip]) >= ADMIN_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a minute.")
    _admin_rate[ip].append(now)

async def require_admin(request: Request) -> dict:
    """
    3-Layer admin authentication:
    1. JWT token must be present and valid
    2. User must exist in DB
    3. User's CURRENT tier in DB must be 'admin'
    
    We NEVER trust the JWT payload for tier — always check DB.
    """
    # Layer 1: Extract JWT
    token = request.cookies.get("horus_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")

    payload = decode_jwt(token)  # raises 401 if invalid/expired

    # Layer 2: User exists
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    # Layer 3: FRESH tier check from database (not JWT)
    if user["tier"] != "admin":
        logger.warning(f"🚫 Non-admin access attempt: {user['email']} (tier: {user['tier']}) from {_get_client_ip(request)}")
        raise HTTPException(status_code=403, detail="Admin access required.")

    # Rate limit
    _rate_check_admin(_get_client_ip(request))

    return user

def _log_action(admin_email: str, action: str, target: str, ip: str):
    """Audit log for admin actions."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "admin": admin_email,
        "action": action,
        "target": target,
        "ip": ip
    }
    _audit_log.append(entry)
    if len(_audit_log) > 500:
        _audit_log.pop(0)
    logger.info(f"🛡️ ADMIN ACTION: {admin_email} → {action} → {target} (IP: {ip})")

# ============ Models ============

class UpdateUserRequest(BaseModel):
    tier: str = ""
    is_active: bool = True

# ============ Endpoints ============

@router_admin.get("/stats")
async def admin_stats(admin: dict = Depends(require_admin)):
    """Platform-wide statistics."""
    stats = get_admin_stats()
    return stats

@router_admin.get("/users")
async def admin_users(
    request: Request,
    search: str = "",
    tier: str = "",
    page: int = 1,
    limit: int = 25,
    admin: dict = Depends(require_admin)
):
    """Paginated user list with search and filter."""
    if limit > 100:
        limit = 100
    if page < 1:
        page = 1
    result = get_all_users(search=search, tier=tier, page=page, limit=limit)
    return result

@router_admin.get("/users/{user_id}/details")
async def admin_user_details(user_id: int, admin: dict = Depends(require_admin)):
    """Get full details of a specific user including their usage log."""
    user_data = get_user_full_details(user_id)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found.")
    return user_data

@router_admin.put("/users/{user_id}")
async def admin_update_user(
    user_id: int,
    req: UpdateUserRequest,
    request: Request,
    admin: dict = Depends(require_admin)
):
    """Update a user's tier or active status."""
    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Prevent self-demotion
    if user_id == admin["id"] and req.tier and req.tier != "admin":
        raise HTTPException(status_code=400, detail="Cannot change your own admin tier.")

    ip = _get_client_ip(request)
    changes = []

    if req.tier and req.tier != target_user["tier"]:
        valid_tiers = ["free", "trader", "pro", "institutional", "admin"]
        if req.tier not in valid_tiers:
            raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {valid_tiers}")
        upgrade_user_tier(user_id, req.tier)
        changes.append(f"tier: {target_user['tier']} → {req.tier}")

    if req.is_active != bool(target_user["is_active"]):
        toggle_user_active(user_id, req.is_active)
        changes.append(f"active: {target_user['is_active']} → {req.is_active}")

    if changes:
        _log_action(admin["email"], ", ".join(changes), target_user["email"], ip)

    return {"message": f"User {target_user['email']} updated.", "changes": changes}

@router_admin.get("/users/export")
async def admin_export_csv(admin: dict = Depends(require_admin), request: Request = None):
    """Export all users as CSV download."""
    ip = _get_client_ip(request) if request else "unknown"
    _log_action(admin["email"], "CSV export", "all users", ip)

    users = get_all_users_for_export()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "email", "name", "tier", "country", "is_active",
        "stripe_sub_id", "created_at", "updated_at"
    ])
    writer.writeheader()
    writer.writerows(users)

    output.seek(0)
    filename = f"horus_users_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router_admin.get("/audit")
async def admin_audit_log(admin: dict = Depends(require_admin)):
    """View recent admin actions audit log."""
    return {"actions": list(reversed(_audit_log[-50:]))}
