# -*- coding: utf-8 -*-
"""
Global Volatility Ignition Publisher — Background Worker
═════════════════════════════════════════════════════════
Periodically scans Binance 24hr market telemetry across all USDT pairs,
computes per-asset micro-ignition scores and global macro regime dynamics,
and updates Redis keys in real-time:
  1. `horus:ignition_distribution` (Hash: symbol -> score)
  2. `horus:global_ignition_state` (JSON: macro regime, global score, metrics)

Runs as an autonomous asyncio background task in the FastAPI lifespan.

© 2026 HORUS TECH LTD
"""

import asyncio
import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger("API.IgnitionPublisher")

BINANCE_FUTURES_TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
BINANCE_SPOT_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"

REDIS_DIST_KEY = "horus:ignition_distribution"
REDIS_STATE_KEY = "horus:global_ignition_state"

PUBLISH_INTERVAL = 60  # Evaluate every 60 seconds


def _compute_asset_ignition(ticker: dict) -> Optional[tuple]:
    """
    Computes real-time ignition score for a single Binance ticker.
    Returns (slash_symbol, ignition_score).
    """
    sym = ticker.get("symbol", "")
    if not sym.endswith("USDT"):
        return None

    slash_sym = sym[:-4] + "/USDT"

    try:
        high = float(ticker.get("highPrice", 0.0))
        low = float(ticker.get("lowPrice", 0.0))
        last = float(ticker.get("lastPrice", 0.0))
        spread = high - low
        
        # 1. Proximity to 24h High (Testing Breakout Boundary)
        range_pos = (last - low) / spread if spread > 0 else 0.5
        range_pos = max(0.0, min(1.0, range_pos))

        # 2. Price Momentum & Directional Velocity
        change_pct = float(ticker.get("priceChangePercent", 0.0))
        change_score = max(0.0, min(1.0, (change_pct + 2.0) / 15.0))

        # 3. Microstructure Activity (Trade Count Intensity)
        trades = float(ticker.get("count", 0))
        activity_score = min(1.0, math.log10(max(10.0, trades)) / 6.0)

        # 4. Composite Ignition Score
        ign_score = (range_pos * 0.45) + (change_score * 0.35) + (activity_score * 0.20)
        ign_score = round(max(0.0, min(1.0, ign_score)), 3)

        return slash_sym, ign_score
    except Exception:
        return None


def _determine_macro_regime(score: float) -> str:
    """Classifies global market ignition regime."""
    if score < 0.40:
        return "DORMANT"
    elif score < 0.60:
        return "BUILDING"
    elif score < 0.80:
        return "IGNITING"
    else:
        return "EXPANSION"


async def _fetch_tickers(session: aiohttp.ClientSession) -> list:
    """Fetch 24hr tickers with fallback from futures to spot."""
    headers = {"User-Agent": "HorusFlow-Ignition/3.0"}
    timeout = aiohttp.ClientTimeout(total=8)

    # 1. Primary: Binance USDT-M Futures
    try:
        async with session.get(BINANCE_FUTURES_TICKER_URL, headers=headers, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.warning("Futures ticker fetch failed, attempting spot: %s", e)

    # 2. Fallback: Binance Spot Tickers
    try:
        async with session.get(BINANCE_SPOT_TICKER_URL, headers=headers, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.error("Spot ticker fetch also failed: %s", e)

    return []


async def ignition_publisher_loop(redis_manager):
    """
    Autonomous background loop that computes and publishes
    real-time ignition telemetry every 60 seconds to Redis.
    """
    logger.info("🔥 Global Ignition Publisher started (interval=%ds)", PUBLISH_INTERVAL)

    # Let Redis connection initialize
    await asyncio.sleep(4)

    prev_global_ignition = 0.0
    score_history = []

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                tickers = await _fetch_tickers(session)
                if tickers:
                    distribution = {}
                    for t in tickers:
                        res = _compute_asset_ignition(t)
                        if res:
                            sym, score = res
                            distribution[sym] = str(score)

                    if distribution:
                        total_assets = len(distribution)
                        scores = [float(v) for v in distribution.values()]

                        avg_ignition = sum(scores) / total_assets
                        pct_above_0_6 = sum(1 for s in scores if s >= 0.6) / total_assets
                        pct_above_0_8 = sum(1 for s in scores if s >= 0.8) / total_assets

                        # Weighted Global Ignition Formula
                        global_ignition = (
                            (avg_ignition * 0.40) +
                            (pct_above_0_6 * 0.40) +
                            (pct_above_0_8 * 0.20)
                        )

                        delta = global_ignition - prev_global_ignition
                        regime_bias = "RISING" if delta >= 0 else "FADING"
                        prev_global_ignition = global_ignition

                        regime = _determine_macro_regime(global_ignition)

                        # Stability tracking (last 5 cycles)
                        score_history.append(global_ignition)
                        if len(score_history) > 5:
                            score_history.pop(0)

                        stability_score = 1.0
                        if len(score_history) > 1:
                            mean = sum(score_history) / len(score_history)
                            variance = sum((x - mean) ** 2 for x in score_history) / len(score_history)
                            std_dev = variance ** 0.5
                            if std_dev > 0.15:
                                stability_score = 0.5
                            elif std_dev > 0.08:
                                stability_score = 0.8
                            else:
                                stability_score = 1.0

                        state = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "regime": regime,
                            "regime_bias": regime_bias,
                            "global_ignition": round(global_ignition, 4),
                            "delta": round(delta, 4),
                            "stability_score": round(stability_score, 2),
                            "metrics": {
                                "avg_ignition": round(avg_ignition, 4),
                                "pct_above_0_6": round(pct_above_0_6, 4),
                                "pct_above_0_8": round(pct_above_0_8, 4),
                                "total_tracked": total_assets
                            }
                        }

                        if redis_manager.redis:
                            # Atomic pipeline write
                            async with redis_manager.redis.pipeline(transaction=True) as pipe:
                                pipe.delete(REDIS_DIST_KEY)
                                pipe.hset(REDIS_DIST_KEY, mapping=distribution)
                                pipe.set(REDIS_STATE_KEY, json.dumps(state))
                                await pipe.execute()

                            top_3 = sorted(distribution.items(), key=lambda x: float(x[1]), reverse=True)[:3]
                            top_str = ", ".join([f"{k}: {v}" for k, v in top_3])
                            logger.info(
                                "🔥 Ignition Updated: %s (%s, score=%.4f) | %d assets | Top: %s",
                                regime, regime_bias, global_ignition, total_assets, top_str
                            )
                        else:
                            logger.warning("🔥 Ignition: Redis not connected, skipping publish")
                else:
                    logger.warning("🔥 Ignition: No tickers returned from Binance")

            except Exception as e:
                logger.error("🔥 Ignition Publisher error: %s", e)

            await asyncio.sleep(PUBLISH_INTERVAL)
