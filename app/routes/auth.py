# -*- coding: utf-8 -*-
"""
Horus Flow — Auth Routes (Register, Login, Me, Logout)
"""
import os
import jwt
import time
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from collections import defaultdict

import httpx

from app.database import (
    create_user, authenticate_user, get_user_by_id,
    get_user_keys, get_usage_stats, get_user_by_email, update_password,
    set_user_country
)

logger = logging.getLogger("Auth")

router_auth = APIRouter()

JWT_SECRET = os.getenv("JWT_SECRET", "horus-jwt-secret-change-in-production-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72  # 3 days

# Rate limiting for login attempts
_login_attempts: dict = defaultdict(list)

# ============ Models ============

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""

class LoginRequest(BaseModel):
    email: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

# ============ JWT Helpers ============

def create_jwt(user_id: int, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired. Please login again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")

def get_current_user(request: Request) -> dict:
    """Extract user from JWT cookie or Authorization header."""
    token = request.cookies.get("horus_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Please login.")
    
    payload = decode_jwt(token)
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user

# ============ Rate Limiting ============

def _check_login_rate(ip: str):
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 300]  # 5 min window
    if len(_login_attempts[ip]) >= 10:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 5 minutes.")
    _login_attempts[ip].append(now)

# ============ GeoIP Helper ============

async def _detect_country(ip: str, user_id: int):
    """Background task: detect country from IP via free API."""
    if not ip or ip in ("127.0.0.1", "localhost", "unknown"):
        return
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"http://ip-api.com/json/{ip}?fields=countryCode")
            if r.status_code == 200:
                data = r.json()
                cc = data.get("countryCode", "")
                if cc:
                    set_user_country(user_id, cc)
                    logger.info(f"🌍 User {user_id} → {cc}")
    except Exception:
        pass  # Non-critical, fail silently

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

# ============ Endpoints ============

@router_auth.post("/register")
async def register(req: RegisterRequest, request: Request):
    """Create a new account. Returns JWT token + API key."""
    email = req.email.strip().lower()
    
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    
    try:
        user = create_user(email, req.password, req.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    
    token = create_jwt(user["id"], email)
    
    # Detect country in background
    import asyncio
    asyncio.create_task(_detect_country(_get_client_ip(request), user["id"]))
    
    response = JSONResponse({
        "message": "Account created successfully!",
        "user": {
            "id": user["id"],
            "email": email,
            "tier": "free",
            "api_key": user["api_key"]
        }
    })
    response.set_cookie(
        key="horus_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=JWT_EXPIRE_HOURS * 3600
    )
    
    logger.info(f"🆕 New user registered: {email}")
    return response

@router_auth.post("/login")
async def login(req: LoginRequest, request: Request):
    """Login with email + password. Returns JWT token."""
    ip = request.client.host
    _check_login_rate(ip)
    
    user = authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    
    token = create_jwt(user["id"], user["email"])
    
    # Detect country if not set
    if not user.get("country"):
        import asyncio
        asyncio.create_task(_detect_country(_get_client_ip(request), user["id"]))
    
    response = JSONResponse({
        "message": "Login successful!",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "tier": user["tier"],
            "name": user["name"]
        }
    })
    response.set_cookie(
        key="horus_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=JWT_EXPIRE_HOURS * 3600
    )
    
    logger.info(f"🔑 User logged in: {user['email']}")
    return response

@router_auth.get("/me")
async def get_me(request: Request):
    """Get current user info + API keys + usage stats."""
    user = get_current_user(request)
    keys = get_user_keys(user["id"])
    usage = get_usage_stats(user["id"])
    
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "tier": user["tier"],
            "created_at": user["created_at"]
        },
        "api_keys": [
            {
                "key": k["key"],
                "tier": k["tier"],
                "is_active": bool(k["is_active"]),
                "daily_limit": k["daily_limit"],
                "created_at": k["created_at"]
            }
            for k in keys
        ],
        "usage": usage
    }

import asyncio

@router_auth.post("/logout")
async def logout():
    """Clear the JWT cookie."""
    response = JSONResponse({"message": "Logged out."})
    # Delete standard
    response.delete_cookie(key="horus_token", path="/", httponly=True, secure=True, samesite="lax")
    # Overwrite value with expiration in 1970 to bypass clock skew issues
    response.set_cookie("horus_token", value="", max_age=-1, expires="Thu, 01 Jan 1970 00:00:00 GMT", path="/", httponly=True, secure=True, samesite="lax")
    response.set_cookie("horus_token", value="", max_age=-1, expires="Thu, 01 Jan 1970 00:00:00 GMT", path="/", httponly=True, secure=True, samesite="lax")
    response.set_cookie("horus_token", value="", max_age=-1, expires="Thu, 01 Jan 1970 00:00:00 GMT", path="/", domain="flow.horustek.pro", httponly=True, secure=True, samesite="lax")
    response.set_cookie("horus_token", value="", max_age=-1, expires="Thu, 01 Jan 1970 00:00:00 GMT", path="/", domain=".flow.horustek.pro", httponly=True, secure=True, samesite="lax")
    response.set_cookie("horus_token", value="", max_age=-1, expires="Thu, 01 Jan 1970 00:00:00 GMT", path="/", domain="horustek.pro", httponly=True, secure=True, samesite="lax")
    response.set_cookie("horus_token", value="", max_age=-1, expires="Thu, 01 Jan 1970 00:00:00 GMT", path="/", domain=".horustek.pro", httponly=True, secure=True, samesite="lax")
    
    # Sleep to force the frontend to wait, mitigating race conditions in cached HTML
    await asyncio.sleep(0.5)
    
    return response

# ============ Password Reset ============

RESET_JWT_EXPIRE_MINUTES = 30

def _create_reset_token(user_id: int, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "purpose": "password_reset",
        "exp": datetime.utcnow() + timedelta(minutes=RESET_JWT_EXPIRE_MINUTES),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

@router_auth.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    """Generate a password reset link. Returns the link directly (no email sending)."""
    email = req.email.strip().lower()
    user = get_user_by_email(email)
    
    if not user:
        # Don't reveal if email exists or not
        return {"message": "If that email is registered, a reset link has been generated.", "reset_url": None}
    
    token = _create_reset_token(user["id"], user["email"])
    site_url = os.getenv("SITE_URL", "https://flow.horustek.pro")
    reset_url = f"{site_url}/reset-password.html?token={token}"
    
    logger.info(f"🔑 Password reset requested for: {email}")
    
    return {
        "message": "If that email is registered, a reset link has been generated.",
        "reset_url": reset_url
    }

@router_auth.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    """Reset password using a valid reset token."""
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    
    try:
        payload = jwt.decode(req.token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid reset link.")
    
    if payload.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid token type.")
    
    user_id = payload["sub"]
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    
    update_password(user_id, req.password)
    
    logger.info(f"✅ Password reset completed for user {user_id}")
    return {"message": "Password has been reset successfully. You can now login."}
