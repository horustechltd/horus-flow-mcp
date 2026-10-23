# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Server
HOST = os.getenv("FLOW_HOST", "0.0.0.0")
PORT = int(os.getenv("FLOW_PORT", "8010"))

# API Keys — loaded ONLY from the environment (.env). No defaults: a missing slot
# simply does not exist. Each slot declares its own tier:
#   FLOW_API_KEY_<n>=<key>
#   FLOW_API_TIER_<n>=demo|free|mcp_public|builder|trader|pro|ultra|institutional|mega|admin
API_KEYS = {}
for i in range(1, 30):
    key = os.getenv(f"FLOW_API_KEY_{i}")
    if key:
        API_KEYS[key] = os.getenv(f"FLOW_API_TIER_{i}", "free").strip().lower()

# RapidAPI Gateway Integration
RAPIDAPI_PROXY_SECRET = os.getenv("RAPIDAPI_PROXY_SECRET", "")

# Rate limits per tier (requests per minute). Lower tiers get LOWER limits.
# The demo tier is limited per client IP, not per key (the demo key is public).
RATE_LIMITS = {
    "demo": 20,
    "free": 30,
    "mcp_public": 120,
    "builder": 120,
    "trader": 120,
    "pro": 300,
    "ultra": 300,
    "institutional": 600,
    "mega": 600,
    "admin": 100000,
}

# Daily request cap for the public demo tier, per client IP
DEMO_DAILY_LIMIT_PER_IP = 500

# Symbols available on the free/demo tiers (other USDT pairs need a paid plan)
FREE_TIER_SYMBOLS = {"BTCUSDT", "ETHUSDT"}

# Max number of crypto symbols tracked live at once (protects the WS connection)
MAX_TRACKED_CRYPTO_SYMBOLS = 80

# Test instance flag: disables publishers that write Redis keys shared with the
# trading platform, the Alpaca WS (single-connection plan) and ops alerts.
TEST_INSTANCE = os.getenv("HORUS_TEST_INSTANCE", "") == "1"

# Ops alerts (Telegram). Alerts are sent only when both are set.
OPS_TELEGRAM_TOKEN = os.getenv("OPS_TELEGRAM_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", ""))
OPS_TELEGRAM_CHAT_ID = os.getenv("OPS_TELEGRAM_CHAT_ID", "")

# Binance WebSocket
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"

# Alpaca IEX (Equity Free Tier)
ALPACA_KEY = os.getenv("APCA_API_KEY_ID", "")
ALPACA_SECRET = os.getenv("APCA_API_SECRET_KEY", "")
ALPACA_WS_BASE = "wss://stream.data.alpaca.markets/v2/iex"

# Tracked symbols
TRACKED_SYMBOLS_CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT"]
TRACKED_SYMBOLS_EQUITY = ["AAPL", "NVDA", "TSLA", "QQQ", "COIN", "MSTR", "IBIT"]

# Redis (reuse existing)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
