# -*- coding: utf-8 -*-
"""
Horus Flow API — History Recorder
Records a flow snapshot every 15 seconds for every tracked crypto symbol,
so /v1/flow/crypto/{symbol}/history has numbers (not only labels) and does
not depend on someone polling the live endpoint.
"""
import asyncio
import logging

from fastapi import HTTPException

from app.feeds.binance_ws import ws_manager
from app.redis_client import redis_manager

logger = logging.getLogger("API.HistoryRecorder")

RECORD_INTERVAL = 15
METRIC_FIELDS = ("price", "delta_5s", "delta_30s", "delta_5m", "buy_sell_ratio", "bid_ask_ratio",
                 "top5_imbalance", "spread_pct", "large_sell_count", "large_trade_threshold_usd",
                 "bid_depth_change_pct", "ask_depth_change_pct", "delta_accel")


async def history_recorder_loop():
    from app.routes.flow import build_flow_response  # late import: routes import feeds
    await asyncio.sleep(20)
    while True:
        for sym in sorted(ws_manager.symbols):
            try:
                doc = await build_flow_response(sym, update_oscillation=False)
            except HTTPException:
                continue
            except Exception as e:
                logger.debug(f"history snapshot failed for {sym}: {e}")
                continue
            m = doc.get("metrics", {})
            snap = {
                "signal": doc.get("signal"),
                "action": doc.get("action"),
                "direction_bias": doc.get("direction_bias"),
                "confidence": doc.get("confidence"),
                "market_state": doc.get("market_state"),
                "risk": doc.get("risk"),
            }
            snap.update({k: m.get(k) for k in METRIC_FIELDS})
            await redis_manager.push_history(sym, snap)
        await asyncio.sleep(RECORD_INTERVAL)
