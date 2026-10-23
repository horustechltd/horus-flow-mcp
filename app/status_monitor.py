# -*- coding: utf-8 -*-
"""
Horus Flow API — Status Monitor
Checks every data source once a minute, keeps 7 days of samples in Redis for
uptime figures, serves /v1/status, and sends Telegram alerts on outages.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import aiohttp

from app.config import OPS_TELEGRAM_TOKEN, OPS_TELEGRAM_CHAT_ID, TEST_INSTANCE
from app.derivatives_publisher import KEY_PUBLISHER_HEARTBEAT
from app.feeds.alpaca_ws import alpaca_ws_manager
from app.feeds.binance_ws import ws_manager
from app.redis_client import redis_manager

logger = logging.getLogger("API.StatusMonitor")

CHECK_INTERVAL = 60
SAMPLES_KEY = "horus:api:status:samples"
SAMPLES_RETENTION = 7 * 86400
ALERT_AFTER_CONSECUTIVE_DOWN = 2
ALERT_REPEAT_SECONDS = 1800

COMPONENTS: List[Dict[str, Any]] = [
    {"name": "binance_spot_stream", "label": "Binance spot order book and trades", "max_age": 30,
     "endpoints": ["/v1/flow/crypto/{symbol}", "/v1/flow/crypto/{symbol}/history"]},
    {"name": "derivatives_publisher", "label": "Binance futures derivatives (OI, funding, positioning)", "max_age": 180,
     "endpoints": ["/v1/intelligence/cross-exchange-flow", "/v1/intelligence/liquidation-heatmap",
                   "/v1/intelligence/composite", "/v1/intelligence/market-intelligence"]},
    {"name": "wiseman_climate", "label": "WiseMan BTC climate", "max_age": 900,
     "endpoints": ["/v1/intelligence/climate"]},
    {"name": "ignition_scanner", "label": "Ignition scanner", "max_age": 600,
     "endpoints": ["/v1/intelligence/ignitions"]},
    {"name": "cortex", "label": "Horus Cortex", "max_age": 600,
     "endpoints": ["/v1/intelligence/cortex"]},
    {"name": "incubator", "label": "Behavioral Court / Incubator", "max_age": None,
     "endpoints": ["/v1/intelligence/verdict/{symbol}", "/v1/intelligence/incubator"]},
    {"name": "alpaca_iex_stream", "label": "US equities (IEX sample via Alpaca)", "max_age": 120,
     "endpoints": ["/v1/flow/equity/{symbol}", "/v1/flow/equity/macro-blocks", "/v1/cross-asset"]},
    {"name": "us_halts_feed", "label": "US trading halts (Nasdaq Trader)", "max_age": 1200,
     "endpoints": ["/v1/equity/session", "/v1/equity/halts"]},
    {"name": "event_detector", "label": "Agent events and webhooks", "max_age": 120,
     "endpoints": ["/v1/events", "/v1/events/stream", "/v1/webhooks"]},
    {"name": "market_scanner", "label": "Market scanner (Binance perpetuals)", "max_age": 300,
     "endpoints": ["/v1/scan"]},
    {"name": "track_record", "label": "Live signal track record", "max_age": 3600,
     "endpoints": ["/v1/track-record", "/v1/track-record/signals"]},
]

_latest: Dict[str, Dict[str, Any]] = {}
_down_streak: Dict[str, int] = {}
_last_alert: Dict[str, float] = {}
_alerted_down: Dict[str, bool] = {}


def _ts_of(doc: Optional[Dict[str, Any]]) -> Optional[float]:
    if not doc:
        return None
    for field in ("timestamp_epoch", "timestamp", "market_clock_iso"):
        v = doc.get(field)
        if isinstance(v, (int, float)) and v > 1e9:
            return float(v)
        if isinstance(v, str) and v[:2] == "20":
            try:
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


async def _redis_doc(key: str) -> Optional[Dict[str, Any]]:
    if not redis_manager.redis:
        return None
    raw = await redis_manager.redis.get(key)
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


def us_market_open(now: Optional[datetime] = None) -> bool:
    ny = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    if ny.weekday() >= 5:
        return False
    minutes = ny.hour * 60 + ny.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


async def _age(name: str) -> Optional[float]:
    now = time.time()
    if name == "binance_spot_stream":
        return now - ws_manager._last_msg_time
    if name == "alpaca_iex_stream":
        return now - alpaca_ws_manager.last_msg_time if alpaca_ws_manager.last_msg_time else None
    if name == "us_halts_feed":
        from app import us_market
        t = us_market._halts.get("fetched_at") or 0
        return now - t if t else None
    if name == "track_record":
        from app import track_record
        t = track_record._cache.get("computed_at") or 0
        return now - t if t else None
    key = {"derivatives_publisher": KEY_PUBLISHER_HEARTBEAT,
           "event_detector": "horus:api:events:heartbeat",
           "market_scanner": "horus:api:scanner:heartbeat",
           "wiseman_climate": "hta:state:wiseman_climate",
           "ignition_scanner": "horus:global_ignition_state",
           "cortex": "horus:maestro:state"}.get(name)
    if key:
        ts = _ts_of(await _redis_doc(key))
        return None if ts is None else max(0.0, now - ts)
    return None


async def check_all() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in COMPONENTS:
        name = c["name"]
        status, age = "down", None
        try:
            if name == "incubator":
                online = False
                if redis_manager.redis:
                    async for _ in redis_manager.redis.scan_iter("incubator:*", count=500):
                        online = True
                        break
                status = "ok" if online else "down"
            elif name == "alpaca_iex_stream" and not us_market_open():
                status = "closed"
                age = await _age(name)
            else:
                age = await _age(name)
                status = "ok" if age is not None and age <= c["max_age"] else "down"
        except Exception as e:
            logger.error(f"status check failed for {name}: {e}")
        out[name] = {"status": status, "age_seconds": None if age is None else int(age)}
    return out


async def _record(sample: Dict[str, Dict[str, Any]]):
    if not redis_manager.redis:
        return
    now = time.time()
    member = json.dumps({"ts": now, "s": {k: v["status"] for k, v in sample.items()}})
    await redis_manager.redis.zadd(SAMPLES_KEY, {member: now})
    await redis_manager.redis.zremrangebyscore(SAMPLES_KEY, 0, now - SAMPLES_RETENTION)


async def _uptime(window_s: int) -> Dict[str, Optional[float]]:
    if not redis_manager.redis:
        return {}
    rows = await redis_manager.redis.zrangebyscore(SAMPLES_KEY, time.time() - window_s, "+inf")
    ok: Dict[str, int] = {}
    total: Dict[str, int] = {}
    for r in rows:
        try:
            s = json.loads(r)["s"]
        except Exception:
            continue
        for name, st in s.items():
            if st == "closed":
                continue
            total[name] = total.get(name, 0) + 1
            ok[name] = ok.get(name, 0) + (1 if st == "ok" else 0)
    return {n: round(ok.get(n, 0) / total[n] * 100, 2) for n in total}


async def _send_telegram(text: str):
    if TEST_INSTANCE or not (OPS_TELEGRAM_TOKEN and OPS_TELEGRAM_CHAT_ID):
        return
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(f"https://api.telegram.org/bot{OPS_TELEGRAM_TOKEN}/sendMessage",
                         json={"chat_id": OPS_TELEGRAM_CHAT_ID, "text": text},
                         timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logger.error(f"ops alert failed: {e}")


async def _alerts(sample: Dict[str, Dict[str, Any]]):
    now = time.time()
    labels = {c["name"]: c["label"] for c in COMPONENTS}
    for name, info in sample.items():
        if info["status"] == "down":
            _down_streak[name] = _down_streak.get(name, 0) + 1
            if _down_streak[name] >= ALERT_AFTER_CONSECUTIVE_DOWN and now - _last_alert.get(name, 0) > ALERT_REPEAT_SECONDS:
                _last_alert[name] = now
                _alerted_down[name] = True
                age = info["age_seconds"]
                await _send_telegram(f"Horus Flow API: {labels[name]} is DOWN"
                                     + (f" (last update {age}s ago)" if age is not None else "") + ".")
        else:
            if _alerted_down.get(name):
                await _send_telegram(f"Horus Flow API: {labels[name]} recovered.")
            _alerted_down[name] = False
            _down_streak[name] = 0


async def status_monitor_loop():
    await asyncio.sleep(30)
    while True:
        try:
            sample = await check_all()
            _latest.clear()
            _latest.update(sample)
            await _record(sample)
            await _alerts(sample)
            await _daily_rapidapi_report()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"status monitor error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


REPORT_HOUR_UTC = 6  # 09:00 in Egypt / 15:00 in Japan


async def _daily_rapidapi_report():
    """Once a day, send yesterday's RapidAPI usage to the owner's Telegram (Arabic)."""
    now = datetime.now(timezone.utc)
    if now.hour < REPORT_HOUR_UTC or not redis_manager.redis:
        return
    from app import rapidapi_stats
    from datetime import timedelta
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    flag = f"{rapidapi_stats.PREFIX}:report_sent:{yesterday}"
    if not await redis_manager.redis.set(flag, "1", ex=3 * 86400, nx=True):
        return  # already sent
    summary = await rapidapi_stats.day_summary(redis_manager.redis, yesterday)
    await _send_telegram(rapidapi_stats.telegram_text(summary))


async def public_status() -> Dict[str, Any]:
    sample = _latest or await check_all()
    up24 = await _uptime(86400)
    up7 = await _uptime(7 * 86400)
    comps = []
    for c in COMPONENTS:
        info = sample.get(c["name"], {"status": "unknown", "age_seconds": None})
        comps.append({
            "name": c["name"],
            "label": c["label"],
            "status": info["status"],
            "age_seconds": info["age_seconds"],
            "max_age_seconds": c["max_age"],
            "uptime_24h_pct": up24.get(c["name"]),
            "uptime_7d_pct": up7.get(c["name"]),
            "endpoints": c["endpoints"],
        })
    statuses = [x["status"] for x in comps]
    overall = "operational" if all(s in ("ok", "closed") for s in statuses) else "degraded"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "components": comps,
        "stream_reconnects_since_start": {"binance_spot": ws_manager.reconnects,
                                          "alpaca_iex": alpaca_ws_manager.reconnects},
        "note": "Uptime counts one sample per minute. Equity samples outside US market hours are excluded.",
    }
