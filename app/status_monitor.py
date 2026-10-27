# -*- coding: utf-8 -*-
"""
Horus Flow API — Status Monitor
Checks every data source once a minute, keeps 7 days of samples in Redis for
uptime figures, serves /v1/status, and sends Telegram alerts on outages.
"""
import asyncio
import json
import logging
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
STARTUP_GRACE_SECONDS = 300  # feeds warm up after a restart; no alerts before this
ALERTED_KEY = "horus:api:status:alerted"  # name -> epoch of the DOWN alert; survives restarts
# The trading platform's Sniper witness stops opening raw ledgers under 8 GB free disk, silently.
DISK_ALERT_GB = 12.0
DISK_RECOVER_GB = 14.0

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
    {"name": "incubator", "label": "Behavioral Court / Incubator", "max_age": None, "alert": False,
     "endpoints": ["/v1/intelligence/verdict/{symbol}", "/v1/intelligence/incubator"]},
    {"name": "alpaca_iex_stream", "label": "US equities (IEX sample via Alpaca)", "max_age": 120,
     "endpoints": ["/v1/flow/equity/{symbol}", "/v1/flow/equity/macro-blocks", "/v1/cross-asset"]},
    {"name": "us_halts_feed", "label": "US trading halts (Nasdaq Trader)", "max_age": 1200,
     "endpoints": ["/v1/equity/session", "/v1/equity/halts"]},
    {"name": "event_detector", "label": "Agent events and webhooks", "max_age": 120,
     "endpoints": ["/v1/events", "/v1/events/stream", "/v1/webhooks"]},
    {"name": "market_scanner", "label": "Market scanner (Binance perpetuals)", "max_age": 300,
     "endpoints": ["/v1/scan"]},
    {"name": "book_recorder", "label": "Order-book recorder (30 Binance spot pairs)", "max_age": 120,
     "endpoints": []},
    {"name": "track_record", "label": "Live signal track record", "max_age": 3600,
     "endpoints": ["/v1/track-record", "/v1/track-record/signals"]},
]

_latest: Dict[str, Dict[str, Any]] = {}
_down_streak: Dict[str, int] = {}
_started_at = time.time()
_uptime_cache: Dict[str, Any] = {"at": 0.0, "up24": {}, "up7": {}}
UPTIME_CACHE_S = 60  # samples are one a minute; recomputing 20k of them per /v1/status call stalled the API


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
           "book_recorder": "horus:api:book_recorder:heartbeat",
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
            async with s.post(f"https://api.telegram.org/bot{OPS_TELEGRAM_TOKEN}/sendMessage",
                              json={"chat_id": OPS_TELEGRAM_CHAT_ID, "text": text},
                              timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    logger.error(f"ops alert rejected: HTTP {r.status} {(await r.text())[:200]}")
    except Exception as e:
        logger.error(f"ops alert failed: {e!r}")


async def _alerts(sample: Dict[str, Dict[str, Any]]):
    """One message when a component goes down and one when it recovers; never repeated.
    The alerted set lives in Redis so a restart neither re-sends nor forgets it."""
    r = redis_manager.redis
    if not r:
        return
    in_grace = time.time() - _started_at < STARTUP_GRACE_SECONDS
    labels = {c["name"]: c["label"] for c in COMPONENTS}
    silent = {c["name"] for c in COMPONENTS if c.get("alert") is False}
    for name, info in sample.items():
        if name in silent:
            continue
        if info["status"] == "down":
            _down_streak[name] = _down_streak.get(name, 0) + 1
            if (not in_grace and _down_streak[name] >= ALERT_AFTER_CONSECUTIVE_DOWN
                    and not await r.hget(ALERTED_KEY, name)):
                await r.hset(ALERTED_KEY, name, str(int(time.time())))
                age = info["age_seconds"]
                await _send_telegram(f"Horus Flow API: {labels[name]} is DOWN"
                                     + (f" (last update {age}s ago)" if age is not None else "") + ".")
        else:
            _down_streak[name] = 0
            if await r.hget(ALERTED_KEY, name):
                await r.hdel(ALERTED_KEY, name)
                await _send_telegram(f"Horus Flow API: {labels[name]} recovered.")


def free_disk_gb(path: str = "/") -> float:
    return shutil.disk_usage(path).free / 1e9


async def _disk_alert(free_gb: float):
    """One message when free disk falls under DISK_ALERT_GB, one when it is back over DISK_RECOVER_GB."""
    r = redis_manager.redis
    if not r:
        return
    alerted = await r.hget(ALERTED_KEY, "disk_space")
    if free_gb < DISK_ALERT_GB and not alerted:
        await r.hset(ALERTED_KEY, "disk_space", str(int(time.time())))
        await _send_telegram(f"تنبيه: المساحة الفاضية على الخادم {free_gb:.1f} جيجا. "
                             f"شاهد الـ Sniper يتوقف عن فتح سجلات جديدة تحت 8 جيجا.")
    elif free_gb > DISK_RECOVER_GB and alerted:
        await r.hdel(ALERTED_KEY, "disk_space")
        await _send_telegram(f"المساحة الفاضية على الخادم رجعت {free_gb:.1f} جيجا.")


async def status_monitor_loop():
    await asyncio.sleep(30)
    while True:
        try:
            sample = await check_all()
            _latest.clear()
            _latest.update(sample)
            await _record(sample)
            await _alerts(sample)
            await _disk_alert(free_disk_gb())
            await _daily_rapidapi_report()
            await _monthly_book_value_test()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"status monitor error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


REPORT_HOUR_UTC = 6  # 09:00 in Egypt / 15:00 in Japan
PROJECT_DIR = Path(__file__).resolve().parent.parent
BOOK_TEST_KEY = "horus:api:bookvalue"
BOOK_LABELS = {
    ("top5_imbalance", "1m"): "ميزان أول 5 مستويات ← الدقيقة الجاية",
    ("top5_imbalance", "5m"): "ميزان أول 5 مستويات ← 5 دقايق",
    ("bid_ask_ratio", "1m"): "نسبة طلبات الشراء للبيع ← الدقيقة الجاية",
    ("buy_sell_ratio", "1m"): "نسبة الشراء العنيف ← الدقيقة الجاية",
    ("delta_30s", "1m"): "صافي الشراء آخر 30 ثانية ← الدقيقة الجاية",
    ("dir", "5m"): "حكم حورس (الاتجاه) ← 5 دقايق",
}


def book_value_text(res: Dict[str, Any], history: List[Dict[str, Any]]) -> str:
    """Arabic Telegram summary of one month of app/book_value_test.py."""
    lines = [f"اختبار قيمة دفتر الأوامر لشهر {res['month']}",
             f"العينة: {res['snapshots']:,} لقطة (واحدة في الدقيقة لكل عملة)، {res['symbols']} عملة، من {res['start']} إلى {res['end']}", ""]
    by = {(r["feature"], r["horizon"]): r for r in res.get("results", [])}
    for key, label in BOOK_LABELS.items():
        r = by.get(key)
        if r and r.get("ic_h1") is not None and r.get("ic_h2") is not None:
            lines.append(f"{label}: {r['ic_h1']:+.3f} / {r['ic_h2']:+.3f} {'✓ ثابت' if r['consistent'] else '✗ مش ثابت'}")
    n_ok = sum(r["consistent"] for r in res.get("results", []))
    lines += ["", "الأرقام: الارتباط مع الحركة اللي بعدها في نص الشهر الأول / التاني. "
                  f"ثابت = نفس الاتجاه وثقة إحصائية في النصين ({n_ok} من {len(res.get('results', []))} مقياس)."]
    past = [h for h in history if h.get("month") != res["month"]]
    if past:
        lines.append("ميزان أول 5 مستويات (الدقيقة) في الشهور اللي فاتت: "
                     + "، ".join(f"{h['month']} {'✓' if h.get('top5_1m') else '✗'}" for h in past[-6:]))
    return "\n".join(lines)


async def _monthly_book_value_test():
    """Once a month, test last month's order-book archive in a separate low-priority process and report it."""
    r = redis_manager.redis
    now = datetime.now(timezone.utc)
    if not r or TEST_INSTANCE or now.hour < REPORT_HOUR_UTC:
        return
    month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if not await r.set(f"{BOOK_TEST_KEY}:started:{month}", "1", ex=400 * 86400, nx=True):
        return
    res = {}
    # the 30-pair book recorder's archive when it covers the month, else the API's own flow history
    for folder in ("book_history", "flow_history"):
        proc = await asyncio.create_subprocess_exec(
            "nice", "-n", "19", sys.executable, "-I", str(PROJECT_DIR / "app" / "book_value_test.py"), "--month", month,
            "--dir", str(PROJECT_DIR / "calibration_data" / folder),
            cwd=str(PROJECT_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=1800)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error(f"book value test for {month} ({folder}) timed out")
            return
        if proc.returncode != 0:
            logger.error(f"book value test for {month} ({folder}) failed: {err.decode(errors='replace')[-300:]}")
            return
        res = json.loads(out)
        if res.get("snapshots"):
            res["source"] = folder
            break
    if not res.get("snapshots"):
        return  # no archive for that month
    await r.set(f"{BOOK_TEST_KEY}:{month}", json.dumps(res), ex=400 * 86400)
    top = next((x for x in res["results"] if x["feature"] == "top5_imbalance" and x["horizon"] == "1m"), {})
    await r.lpush(f"{BOOK_TEST_KEY}:history", json.dumps({"month": month, "top5_1m": top.get("consistent", False),
                                                          "consistent": sum(x["consistent"] for x in res["results"])}))
    history = [json.loads(x) for x in reversed(await r.lrange(f"{BOOK_TEST_KEY}:history", 0, 23))]
    await _send_telegram(book_value_text(res, history))


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
    text = rapidapi_stats.telegram_text(summary)
    labels = {c["name"]: c["label"] for c in COMPONENTS if c.get("alert") is not False}
    down = [labels[n] for n, info in _latest.items() if n in labels and info["status"] == "down"]
    if down:
        text += "\n\nمكونات متوقفة الآن: " + "، ".join(down)
    from app.history_archiver import archive_summary
    a = await archive_summary(redis_manager.redis)
    loc, rem = a["local"], a["remote"]
    if rem["hours"]:
        text += f"\n\nأرشيف البيانات على السحابة: {rem['hours']} ساعة، {rem['mb']} ميجا، منذ {rem['first_day']}"
    if loc["hours"]:
        text += f"\nعلى الخادم: آخر {loc['days']} يوم ({loc['mb']} ميجا)"
    text += f"\nالمساحة الفاضية على الخادم: {free_disk_gb():.1f} جيجا"
    from app.database import site_funnel
    f = await asyncio.to_thread(site_funnel, yesterday)
    checkouts = int(await redis_manager.redis.get(f"horus:api:site:{yesterday}:checkouts") or 0)
    text += (f"\n\nالموقع ليوم {yesterday}: {f['signups']} تسجيل جديد، {f['capped_keys']} مفتاح وصل لحده اليومي، "
             f"{checkouts} فتحوا صفحة الدفع. المشتركين المدفوعين الآن: {f['paying']}")
    await _send_telegram(text)


async def public_status() -> Dict[str, Any]:
    sample = _latest or await check_all()
    if time.time() - _uptime_cache["at"] > UPTIME_CACHE_S:
        _uptime_cache.update(at=time.time(), up24=await _uptime(86400), up7=await _uptime(7 * 86400))
    up24, up7 = _uptime_cache["up24"], _uptime_cache["up7"]
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
