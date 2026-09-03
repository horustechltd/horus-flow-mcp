# -*- coding: utf-8 -*-
"""
Horus Flow — OAuth2 Routes (Google + GitHub)
Enterprise-grade social login for institutional platform.
"""
import os
import secrets
import logging
import httpx
from urllib.parse import urlencode
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from app.database import (
    create_user, get_user_by_email, get_user_by_id,
    get_user_keys, generate_api_key, _get_conn
)
from app.routes.auth import create_jwt, JWT_EXPIRE_HOURS

logger = logging.getLogger("OAuth")

router_oauth = APIRouter()

# ============ Configuration ============

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

# Auto-detect base URL from environment or default
SITE_URL = os.getenv("SITE_URL", "https://flow.horustek.pro")

# OAuth state storage (in-memory, short-lived)
_oauth_states: dict = {}

# ============ Google OAuth2 ============

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@router_oauth.get("/google")
async def google_login():
    """Redirect to Google's consent screen."""
    if not GOOGLE_CLIENT_ID:
        return RedirectResponse(f"{SITE_URL}/login.html?error=oauth_not_configured")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = "google"

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{SITE_URL}/api/oauth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router_oauth.get("/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    """Handle Google OAuth callback."""
    if error:
        return RedirectResponse(f"{SITE_URL}/login.html?error=google_denied")

    if state not in _oauth_states:
        return RedirectResponse(f"{SITE_URL}/login.html?error=invalid_state")

    del _oauth_states[state]

    try:
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_res = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{SITE_URL}/api/oauth/google/callback",
                "grant_type": "authorization_code",
            })
            tokens = token_res.json()

            if "access_token" not in tokens:
                logger.error(f"Google token exchange failed: {tokens}")
                return RedirectResponse(f"{SITE_URL}/login.html?error=google_token_fail")

            # Get user info
            user_res = await client.get(GOOGLE_USERINFO_URL, headers={
                "Authorization": f"Bearer {tokens['access_token']}"
            })
            user_info = user_res.json()

        email = user_info.get("email", "").lower()
        name = user_info.get("name", "")

        if not email:
            return RedirectResponse(f"{SITE_URL}/login.html?error=no_email")

        # Create or login user
        response = _oauth_login_or_register(email, name, "google")
        logger.info(f"🔑 Google OAuth: {email}")
        return response

    except Exception as e:
        logger.error(f"Google OAuth error: {e}")
        return RedirectResponse(f"{SITE_URL}/login.html?error=google_error")


# ============ GitHub OAuth2 ============

GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


@router_oauth.get("/github")
async def github_login():
    """Redirect to GitHub's authorization page."""
    if not GITHUB_CLIENT_ID:
        return RedirectResponse(f"{SITE_URL}/login.html?error=oauth_not_configured")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = "github"

    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": f"{SITE_URL}/api/oauth/github/callback",
        "scope": "user:email read:user",
        "state": state,
    }
    return RedirectResponse(f"{GITHUB_AUTH_URL}?{urlencode(params)}")


@router_oauth.get("/github/callback")
async def github_callback(code: str = "", state: str = "", error: str = ""):
    """Handle GitHub OAuth callback."""
    if error:
        return RedirectResponse(f"{SITE_URL}/login.html?error=github_denied")

    if state not in _oauth_states:
        return RedirectResponse(f"{SITE_URL}/login.html?error=invalid_state")

    del _oauth_states[state]

    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for access token
            token_res = await client.post(GITHUB_TOKEN_URL, data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": f"{SITE_URL}/api/oauth/github/callback",
            }, headers={"Accept": "application/json"})
            tokens = token_res.json()

            if "access_token" not in tokens:
                logger.error(f"GitHub token exchange failed: {tokens}")
                return RedirectResponse(f"{SITE_URL}/login.html?error=github_token_fail")

            access_token = tokens["access_token"]
            headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

            # Get user profile
            user_res = await client.get(GITHUB_USER_URL, headers=headers)
            user_info = user_res.json()

            name = user_info.get("name") or user_info.get("login", "")
            email = user_info.get("email", "")

            # GitHub may not return email in profile — fetch from emails endpoint
            if not email:
                emails_res = await client.get(GITHUB_EMAILS_URL, headers=headers)
                emails = emails_res.json()
                for e in emails:
                    if e.get("primary") and e.get("verified"):
                        email = e["email"]
                        break
                if not email and emails:
                    email = emails[0].get("email", "")

        if not email:
            return RedirectResponse(f"{SITE_URL}/login.html?error=no_email")

        email = email.lower()
        response = _oauth_login_or_register(email, name, "github")
        logger.info(f"🔑 GitHub OAuth: {email}")
        return response

    except Exception as e:
        logger.error(f"GitHub OAuth error: {e}")
        return RedirectResponse(f"{SITE_URL}/login.html?error=github_error")


# ============ Shared Helper ============

def _oauth_login_or_register(email: str, name: str, provider: str) -> RedirectResponse:
    """Login existing user or create new account via OAuth."""
    user = get_user_by_email(email)

    if user:
        # Existing user — just login
        token = create_jwt(user["id"], user["email"])
    else:
        # New user — register with random password (OAuth-only account)
        random_pw = secrets.token_urlsafe(32)
        try:
            new_user = create_user(email, random_pw, name)
            # Mark as OAuth user in DB
            conn = _get_conn()
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (f"__oauth_{provider}__", new_user["id"])
            )
            conn.commit()
            conn.close()
            token = create_jwt(new_user["id"], email)
        except ValueError:
            # Race condition — user was created between check and insert
            user = get_user_by_email(email)
            token = create_jwt(user["id"], user["email"])

    response = RedirectResponse(f"{SITE_URL}/account.html", status_code=302)
    response.set_cookie(
        key="horus_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=JWT_EXPIRE_HOURS * 3600
    )
    return response
