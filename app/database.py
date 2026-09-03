# -*- coding: utf-8 -*-
"""
Horus Flow — SQLite Database for Subscribers & API Keys
"""
import sqlite3
import secrets
import hashlib
import time
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("DB")

DB_PATH = Path(os.getenv("HORUS_DB_PATH", "horus_subscribers.db"))

# ============ Schema ============

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name        TEXT DEFAULT '',
    tier        TEXT DEFAULT 'free',
    country     TEXT DEFAULT '',
    stripe_customer_id TEXT DEFAULT '',
    stripe_sub_id      TEXT DEFAULT '',
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    key         TEXT UNIQUE NOT NULL,
    tier        TEXT DEFAULT 'free',
    is_active   INTEGER DEFAULT 1,
    daily_limit INTEGER DEFAULT 100,
    created_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS usage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key     TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    response_time_ms INTEGER DEFAULT 0,
    client_ip   TEXT DEFAULT '',
    timestamp   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(key);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_log(api_key, timestamp);
"""

# ============ Connection ============

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    logger.info(f"📦 Database initialized: {DB_PATH}")

# ============ Password Hashing ============

def _hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _verify_password(password: str, hashed: str) -> bool:
    import bcrypt
    return bcrypt.checkpw(password.encode(), hashed.encode())

# ============ User CRUD ============

def create_user(email: str, password: str, name: str = "") -> dict:
    """Register a new user. Returns user dict or raises ValueError."""
    conn = _get_conn()
    try:
        pw_hash = _hash_password(password)
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email.lower().strip(), pw_hash, name)
        )
        user_id = cur.lastrowid

        # Auto-generate a free API key
        api_key = generate_api_key(conn, user_id, "free")

        conn.commit()
        return {"id": user_id, "email": email, "tier": "free", "api_key": api_key}
    except sqlite3.IntegrityError:
        raise ValueError("Email already registered")
    finally:
        conn.close()

def authenticate_user(email: str, password: str) -> dict:
    """Login. Returns user dict or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE email = ? AND is_active = 1",
        (email.lower().strip(),)
    ).fetchone()
    conn.close()

    if row and _verify_password(password, row["password_hash"]):
        return dict(row)
    return None

def get_user_by_id(user_id: int) -> dict:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_email(email: str) -> dict:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_password(user_id: int, new_password: str):
    """Update user's password."""
    conn = _get_conn()
    pw_hash = _hash_password(new_password)
    conn.execute(
        "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
        (pw_hash, user_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"🔒 Password updated for user {user_id}")

# ============ API Key Management ============

def generate_api_key(conn_or_none, user_id: int, tier: str = "free") -> str:
    """Generate a unique API key for a user."""
    key = f"hf_{tier}_{secrets.token_hex(16)}"
    limits = {"free": 100, "trader": 1000, "pro": 5000, "institutional": 99999, "admin": 99999}
    daily_limit = limits.get(tier, 100)

    conn = conn_or_none or _get_conn()
    conn.execute(
        "INSERT INTO api_keys (user_id, key, tier, daily_limit) VALUES (?, ?, ?, ?)",
        (user_id, key, tier, daily_limit)
    )
    if conn_or_none is None:
        conn.commit()
        conn.close()
    return key

def get_key_info(api_key: str) -> dict:
    """Look up an API key. Returns dict with tier, user_id, etc. or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT ak.*, u.email FROM api_keys ak JOIN users u ON ak.user_id = u.id WHERE ak.key = ? AND ak.is_active = 1",
        (api_key,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_keys(user_id: int) -> list:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def upgrade_user_tier(user_id: int, new_tier: str, stripe_sub_id: str = ""):
    """Upgrade user tier and update/create API key."""
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET tier = ?, stripe_sub_id = ?, updated_at = datetime('now') WHERE id = ?",
        (new_tier, stripe_sub_id, user_id)
    )
    # Update existing active key tier
    limits = {"free": 100, "trader": 1000, "pro": 5000, "institutional": 99999}
    conn.execute(
        "UPDATE api_keys SET tier = ?, daily_limit = ? WHERE user_id = ? AND is_active = 1",
        (new_tier, limits.get(new_tier, 100), user_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"⬆️ User {user_id} upgraded to {new_tier}")

def deactivate_user_keys(user_id: int):
    conn = _get_conn()
    conn.execute("UPDATE api_keys SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ============ Usage Tracking ============

def log_usage(api_key: str, endpoint: str, response_time_ms: int = 0, client_ip: str = ""):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO usage_log (api_key, endpoint, response_time_ms, client_ip) VALUES (?, ?, ?, ?)",
        (api_key, endpoint, response_time_ms, client_ip)
    )
    conn.commit()
    conn.close()

def get_daily_usage(api_key: str) -> int:
    conn = _get_conn()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM usage_log WHERE api_key = ? AND timestamp >= ?",
        (api_key, today)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0

def get_usage_stats(user_id: int) -> dict:
    conn = _get_conn()
    keys = conn.execute("SELECT key FROM api_keys WHERE user_id = ?", (user_id,)).fetchall()
    if not keys:
        conn.close()
        return {"today": 0, "this_month": 0}

    key_list = [k["key"] for k in keys]
    placeholders = ",".join("?" * len(key_list))
    today = datetime.utcnow().strftime("%Y-%m-%d")
    month_start = datetime.utcnow().strftime("%Y-%m-01")

    today_count = conn.execute(
        f"SELECT COUNT(*) as cnt FROM usage_log WHERE api_key IN ({placeholders}) AND timestamp >= ?",
        key_list + [today]
    ).fetchone()["cnt"]

    month_count = conn.execute(
        f"SELECT COUNT(*) as cnt FROM usage_log WHERE api_key IN ({placeholders}) AND timestamp >= ?",
        key_list + [month_start]
    ).fetchone()["cnt"]

    conn.close()
    return {"today": today_count, "this_month": month_count}

# ============ Admin Functions ============

def get_all_users(search: str = "", tier: str = "", page: int = 1, limit: int = 25) -> dict:
    """Paginated user list for admin panel."""
    conn = _get_conn()
    conditions = []
    params = []

    if search:
        conditions.append("(email LIKE ? OR name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if tier:
        conditions.append("tier = ?")
        params.append(tier)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM users {where}", params).fetchone()["cnt"]

    offset = (page - 1) * limit
    rows = conn.execute(
        f"SELECT id, email, name, tier, country, is_active, stripe_sub_id, created_at, updated_at FROM users {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()

    conn.close()
    return {
        "users": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit)
    }

def get_admin_stats() -> dict:
    """Aggregate platform stats for admin dashboard."""
    conn = _get_conn()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    month_start = datetime.utcnow().strftime("%Y-%m-01")

    total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
    active_users = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_active = 1").fetchone()["cnt"]

    tiers = conn.execute("SELECT tier, COUNT(*) as cnt FROM users GROUP BY tier").fetchall()
    tier_breakdown = {r["tier"]: r["cnt"] for r in tiers}

    calls_today = conn.execute("SELECT COUNT(*) as cnt FROM usage_log WHERE timestamp >= ?", (today,)).fetchone()["cnt"]
    calls_month = conn.execute("SELECT COUNT(*) as cnt FROM usage_log WHERE timestamp >= ?", (month_start,)).fetchone()["cnt"]

    avg_response = conn.execute(
        "SELECT AVG(response_time_ms) as avg_ms FROM usage_log WHERE timestamp >= ? AND response_time_ms > 0",
        (today,)
    ).fetchone()["avg_ms"] or 0

    # Top endpoints today
    top_endpoints = conn.execute(
        "SELECT endpoint, COUNT(*) as cnt FROM usage_log WHERE timestamp >= ? GROUP BY endpoint ORDER BY cnt DESC LIMIT 10",
        (today,)
    ).fetchall()

    # Top users by usage this month
    top_users = conn.execute(
        """SELECT u.email, u.tier, COUNT(*) as calls
           FROM usage_log ul
           JOIN api_keys ak ON ul.api_key = ak.key
           JOIN users u ON ak.user_id = u.id
           WHERE ul.timestamp >= ?
           GROUP BY u.id ORDER BY calls DESC LIMIT 10""",
        (month_start,)
    ).fetchall()

    # Countries breakdown
    countries = conn.execute(
        "SELECT country, COUNT(*) as cnt FROM users WHERE country != '' GROUP BY country ORDER BY cnt DESC LIMIT 15"
    ).fetchall()

    conn.close()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "tier_breakdown": tier_breakdown,
        "calls_today": calls_today,
        "calls_month": calls_month,
        "avg_response_ms": round(avg_response, 1),
        "top_endpoints": [{"endpoint": r["endpoint"], "count": r["cnt"]} for r in top_endpoints],
        "top_users": [{"email": r["email"], "tier": r["tier"], "calls": r["calls"]} for r in top_users],
        "countries": [{"country": r["country"], "count": r["cnt"]} for r in countries]
    }

def toggle_user_active(user_id: int, is_active: bool):
    """Enable or disable a user account."""
    conn = _get_conn()
    conn.execute(
        "UPDATE users SET is_active = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if is_active else 0, user_id)
    )
    if not is_active:
        conn.execute("UPDATE api_keys SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"{'✅ Enabled' if is_active else '🚫 Disabled'} user {user_id}")

def set_user_country(user_id: int, country: str):
    """Set user's country code."""
    conn = _get_conn()
    conn.execute("UPDATE users SET country = ? WHERE id = ?", (country, user_id))
    conn.commit()
    conn.close()

def get_all_users_for_export() -> list:
    """Get all users for CSV export (no password hashes)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, email, name, tier, country, is_active, stripe_sub_id, created_at, updated_at FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_full_details(user_id: int) -> dict:
    """Fetch complete user details, their API keys, and their usage log for the admin profile view."""
    conn = _get_conn()
    
    # 1. User Info
    user = conn.execute(
        "SELECT id, email, name, tier, country, is_active, stripe_sub_id, created_at, updated_at FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    
    if not user:
        conn.close()
        return None
        
    user_data = dict(user)
    
    # 2. API Keys
    keys = conn.execute(
        "SELECT id, key, tier, is_active, daily_limit, created_at, expires_at FROM api_keys WHERE user_id = ? ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    
    user_data["api_keys"] = [dict(k) for k in keys]
    
    # 3. Usage Logs (limit to last 100 for performance)
    if user_data["api_keys"]:
        key_strings = [k["key"] for k in user_data["api_keys"]]
        placeholders = ",".join("?" * len(key_strings))
        
        logs = conn.execute(
            f"SELECT endpoint, response_time_ms, client_ip, timestamp FROM usage_log WHERE api_key IN ({placeholders}) ORDER BY id DESC LIMIT 100",
            key_strings
        ).fetchall()
        user_data["usage_logs"] = [dict(l) for l in logs]
        
        # 4. Usage Stats (Today and Month)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        month_start = datetime.utcnow().strftime("%Y-%m-01")
        
        user_data["calls_today"] = conn.execute(
            f"SELECT COUNT(*) as cnt FROM usage_log WHERE api_key IN ({placeholders}) AND timestamp >= ?",
            key_strings + [today]
        ).fetchone()["cnt"]
        
        user_data["calls_month"] = conn.execute(
            f"SELECT COUNT(*) as cnt FROM usage_log WHERE api_key IN ({placeholders}) AND timestamp >= ?",
            key_strings + [month_start]
        ).fetchone()["cnt"]
    else:
        user_data["usage_logs"] = []
        user_data["calls_today"] = 0
        user_data["calls_month"] = 0
        
    conn.close()
    return user_data

# Auto-init on import
init_db()
