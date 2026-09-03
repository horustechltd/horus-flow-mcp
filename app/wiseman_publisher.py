# -*- coding: utf-8 -*-
"""
WiseMan Climate Publisher — Background worker
═══════════════════════════════════════════════
Periodically fetches BTC OHLCV data from Binance public API,
computes the WiseMan climate assessment, and publishes to Redis.

This solves the stale-data problem where the WiseMan climate
was only computed in-memory by wise_man.py but never written to Redis,
causing the /climate endpoint to serve stale data.

Runs as an asyncio background task in the FastAPI lifespan.

© 2026 HORUS TECH LTD
"""

import json
import time
import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger("API.WiseManPublisher")

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
REDIS_KEY = "hta:state:wiseman_climate"
PUBLISH_INTERVAL = 300  # 5 minutes
REDIS_TTL = 600  # 10 minutes (2x publish interval, auto-expire if worker dies)


async def _fetch_klines(session: aiohttp.ClientSession, symbol: str, interval: str, limit: int) -> list:
    """Fetch OHLCV klines from Binance public API."""
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        async with session.get(BINANCE_KLINES_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.warning(f"Binance klines fetch failed ({symbol} {interval}): {e}")
    return []


def _compute_wiseman_climate(daily_klines: list, m15_klines: list) -> dict:
    """
    Pure WiseMan climate computation — mirrors WiseManGate.assess_btc_climate()
    but operates on raw kline arrays instead of DataFrames.
    
    Uses only basic math — no pandas/ta dependency needed.
    """
    if len(daily_klines) < 50 or len(m15_klines) < 20:
        return {
            "market_mode": "UNKNOWN",
            "health": "UNKNOWN",
            "confidence": 0.0,
            "reason": "Insufficient BTC data",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_epoch": time.time(),
        }

    # Extract closes
    daily_closes = [float(k[4]) for k in daily_klines]
    m15_closes = [float(k[4]) for k in m15_klines]
    m15_highs = [float(k[2]) for k in m15_klines]
    m15_lows = [float(k[3]) for k in m15_klines]
    m15_volumes = [float(k[5]) for k in m15_klines]

    price = m15_closes[-1]

    # === EMA50 from daily ===
    ema50 = _ema(daily_closes, 50)
    ema50_prev5 = _ema(daily_closes[:-5], 50) if len(daily_closes) > 55 else ema50
    ema50_slope = (ema50 - ema50_prev5) / ema50_prev5 * 100 if ema50_prev5 > 0 else 0

    # === RSI from 15m ===
    rsi = _rsi(m15_closes, 14)

    # === ATR from 15m ===
    atr_vals = _atr(m15_highs, m15_lows, m15_closes, 14)
    atr_val = atr_vals[-1] if atr_vals else 0
    atr_avg = sum(atr_vals[-20:]) / len(atr_vals[-20:]) if len(atr_vals) >= 20 else atr_val
    atr_ratio = atr_val / atr_avg if atr_avg > 0 else 1.0

    # === Volume ratio from 15m ===
    vol_avg = sum(m15_volumes[-20:]) / 20 if len(m15_volumes) >= 20 else m15_volumes[-1]
    vol_ratio = m15_volumes[-1] / vol_avg if vol_avg > 0 else 1.0

    # === Direction changes (chop detection from 15m) ===
    recent = m15_closes[-10:]
    direction_changes = sum(
        1 for i in range(1, len(recent) - 1)
        if (recent[i] - recent[i - 1]) * (recent[i + 1] - recent[i]) < 0
    )

    # === MARKET MODE ===
    if abs(ema50_slope) > 0.3 and direction_changes <= 3 and price > ema50:
        market_mode = "TREND"
    elif direction_changes >= 6:
        market_mode = "CHOP"
    elif abs(ema50_slope) < 0.1 and direction_changes <= 5:
        market_mode = "RANGE"
    else:
        market_mode = "RANGE"

    # === HEALTH ===
    health_score = 0
    if 40 <= rsi <= 65:
        health_score += 2
    elif 30 <= rsi <= 70:
        health_score += 1

    if vol_ratio > 0.8:
        health_score += 1
    if atr_ratio < 1.5:
        health_score += 1

    if health_score >= 3:
        health = "HEALTHY"
    elif health_score >= 1:
        health = "DECAYING"
    else:
        health = "FRAGILE"

    # === CONFIDENCE ===
    confidence = min(1.0, max(0.0, health_score / 4.0))
    if market_mode == "TREND":
        confidence = min(1.0, confidence + 0.15)
    elif market_mode == "CHOP":
        confidence = max(0.0, confidence - 0.2)

    # === NO_TRADE ===
    if market_mode == "CHOP" and health == "FRAGILE" and confidence < 0.35:
        market_mode = "NO_TRADE"
        confidence = max(0.0, confidence - 0.1)

    reason_parts = [
        f"EMA50 slope: {ema50_slope:+.2f}%",
        f"RSI: {rsi:.0f}",
        f"ATR ratio: {atr_ratio:.2f}",
        f"Vol ratio: {vol_ratio:.2f}",
        f"Dir changes: {direction_changes}/8",
    ]

    return {
        "market_mode": market_mode,
        "health": health,
        "confidence": round(confidence, 2),
        "reason": " | ".join(reason_parts),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timestamp_epoch": time.time(),
        "target": "GLOBAL_BTC_MACRO",
    }


# ═══════════════════════════════════════════════
# Pure math helpers (no pandas/ta dependencies)
# ═══════════════════════════════════════════════

def _ema(data: list, period: int) -> float:
    """Calculate Exponential Moving Average."""
    if len(data) < period:
        return data[-1] if data else 0
    k = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for val in data[period:]:
        ema = val * k + ema * (1 - k)
    return ema


def _rsi(closes: list, period: int = 14) -> float:
    """Calculate RSI."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _atr(highs: list, lows: list, closes: list, period: int = 14) -> list:
    """Calculate ATR series."""
    if len(highs) < 2:
        return [0]
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    if len(trs) < period:
        return trs

    atrs = [sum(trs[:period]) / period]
    for i in range(period, len(trs)):
        atrs.append((atrs[-1] * (period - 1) + trs[i]) / period)
    return atrs


# ═══════════════════════════════════════════════
# Background Publisher Loop
# ═══════════════════════════════════════════════

async def wiseman_publisher_loop(redis_manager):
    """
    Background loop that computes WiseMan climate every 5 minutes
    and publishes to Redis for the /climate endpoint to read.
    """
    logger.info("🦅 WiseMan Climate Publisher started (interval=%ds)", PUBLISH_INTERVAL)
    
    # Wait for Redis to be ready
    await asyncio.sleep(5)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # Fetch BTC OHLCV data
                daily_klines = await _fetch_klines(session, "BTCUSDT", "1d", 100)
                m15_klines = await _fetch_klines(session, "BTCUSDT", "15m", 100)

                if daily_klines and m15_klines:
                    climate = _compute_wiseman_climate(daily_klines, m15_klines)

                    # Publish to Redis with TTL
                    if redis_manager.redis:
                        payload = json.dumps(climate)
                        await redis_manager.redis.setex(REDIS_KEY, REDIS_TTL, payload)
                        logger.info(
                            "🦅 WiseMan Published: %s/%s (conf=%.0f%%) | %s",
                            climate["market_mode"],
                            climate["health"],
                            climate["confidence"] * 100,
                            climate["reason"],
                        )
                    else:
                        logger.warning("🦅 WiseMan: Redis not connected, skipping publish")
                else:
                    logger.warning("🦅 WiseMan: Failed to fetch BTC klines, skipping this cycle")

            except Exception as e:
                logger.error("🦅 WiseMan Publisher error: %s", e)

            await asyncio.sleep(PUBLISH_INTERVAL)
