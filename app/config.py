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

# API Keys (simple list for MVP — upgrade to DB later)
# Format: "key:tier" where tier is "free", "trader", "institutional", "admin"
API_KEYS = {
    os.getenv("FLOW_API_KEY_1", "horus-demo-key-2026"): "admin",
    os.getenv("FLOW_API_KEY_2", "horus-trader-key-2026"): "trader",
}

# RapidAPI Gateway Integration
RAPIDAPI_PROXY_SECRET = os.getenv("RAPIDAPI_PROXY_SECRET", "")

# Add any extra keys from env
for i in range(3, 20):
    key = os.getenv(f"FLOW_API_KEY_{i}")
    tier = os.getenv(f"FLOW_API_TIER_{i}", "free")
    if key:
        API_KEYS[key] = tier

# Rate limits per tier (requests per minute)
RATE_LIMITS = {
    "free": 300,
    "trader": 60,
    "institutional": 300,
    "ultra": 300,
    "mega": 600,
    "admin": 9999,
}

# Binance WebSocket
BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"

# Alpaca IEX (Equity Free Tier)
ALPACA_KEY = os.getenv("APCA_API_KEY_ID", "")
ALPACA_SECRET = os.getenv("APCA_API_SECRET_KEY", "")
ALPACA_WS_BASE = "wss://stream.data.alpaca.markets/v2/iex"

# Tracked symbols
TRACKED_SYMBOLS_CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "SUIUSDT"]
TRACKED_SYMBOLS_EQUITY = ["AAPL", "NVDA", "TSLA"]

# Redis (reuse existing)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
