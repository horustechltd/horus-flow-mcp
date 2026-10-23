# -*- coding: utf-8 -*-
"""
Horus Flow API — Events for AI agents (push instead of poll)
=============================================================
A detector runs every 15 seconds and publishes events when something changes:

  liquidation_cascade   forced liquidations above threshold on Binance futures
  strong_flow_signal    strong buy/sell pressure or cascade signal on BTC/ETH/SOL (with track record)
  composite_change      composite verdict or direction changed for a symbol
  cortex_regime_change  Horus Cortex regime changed
  climate_change        WiseMan BTC climate mode or health changed
  ignition_alert        new assets crossed ignition score 0.8
  us_session_change     US equity session phase changed (pre-market, regular, after-hours, closed)
  trading_halt          a new US trading halt was published by Nasdaq Trader

Delivery: GET /v1/events (since_id), GET /v1/events/stream (Server-Sent Events),
and signed webhooks (POST /v1/webhooks).
"""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import aiohttp

from app.redis_client import redis_manager

logger = logging.getLogger("API.Events")

EVENT_TYPES = ("liquidation_cascade", "strong_flow_signal", "composite_change", "cortex_regime_change",
               "climate_change", "ignition_alert", "us_session_change", "trading_halt")
EVENTS_KEY = "horus:api:events"
EVENTS_SEQ = "horus:api:events:seq"
EVENTS_KEEP = 2000
WEBHOOKS_KEY = "horus:api:webhooks"
HEARTBEAT_KEY = "horus:api:events:heartbeat"
DETECT_INTERVAL = 15
DEDUP_SECONDS = 300
MAX_WEBHOOKS_PER_OWNER = 5
WEBHOOK_DISABLE_AFTER = 50
STRONG_SIGNALS = {"STRONG_BUY_PRESSURE", "STRONG_SELL_PRESSURE", "LIQUIDATION_CASCADE", "SHORT_SQUEEZE", "EMERGENCY_DUMP"}

_subscribers: Set[asyncio.Queue] = set()
_webhook_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=5000)


# ─────────────────────────── publishing ───────────────────────────
def owner_id(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:24]


async def publish(etype: str, data: Dict[str, Any], symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
    r = redis_manager.redis
    if not r:
        return None
    eid = await r.incr(EVENTS_SEQ)
    event = {"id": int(eid), "type": etype, "symbol": symbol,
             "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": data}
    await r.lpush(EVENTS_KEY, json.dumps(event))
    await r.ltrim(EVENTS_KEY, 0, EVENTS_KEEP - 1)
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
    try:
        _webhook_queue.put_nowait(event)
    except asyncio.QueueFull:
        logger.warning("webhook queue full; dropping delivery")
    return event


async def recent(since_id: int = 0, types: Optional[Set[str]] = None, limit: int = 100) -> List[Dict[str, Any]]:
    r = redis_manager.redis
    if not r:
        return []
    raw = await r.lrange(EVENTS_KEY, 0, EVENTS_KEEP - 1)
    out = []
    for item in raw:  # newest first
        e = json.loads(item)
        if e["id"] <= since_id:
            break
        if types and e["type"] not in types:
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return list(reversed(out))


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)


# ─────────────────────────── detector ───────────────────────────
class Detector:
    def __init__(self):
        self.initialized = False
        self.last_emit: Dict[str, float] = {}
        self.prev: Dict[str, Any] = {}
        self.seen_ignitions: Dict[str, float] = {}
        self.seen_halts: Set[str] = set()

    def _dedup(self, key: str) -> bool:
        now = time.time()
        if now - self.last_emit.get(key, 0) < DEDUP_SECONDS:
            return False
        self.last_emit[key] = now
        return True

    async def _json(self, key: str) -> Optional[Dict[str, Any]]:
        raw = await redis_manager.redis.get(key)
        try:
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _changed(self, key: str, value: Any) -> Optional[Any]:
        """Return the previous value when it changed (None on first sight or no change)."""
        old = self.prev.get(key, "__unset__")
        self.prev[key] = value
        if old == "__unset__" or old == value or value is None:
            return None
        return old

    async def tick(self) -> List[Dict[str, Any]]:
        from app.derivatives_publisher import SYMBOLS as DERIV_SYMBOLS, KEY_COMPOSITE
        from app.engines.derivatives_engine import derivatives_engine
        from app import us_market
        emit = self.initialized
        out: List[Dict[str, Any]] = []

        async def fire(etype, data, symbol=None):
            if emit:
                e = await publish(etype, data, symbol)
                if e:
                    out.append(e)

        # liquidation cascades
        for sym in DERIV_SYMBOLS:
            st = derivatives_engine.get_derivatives_state(sym) or {}
            sig = st.get("liquidation_signal", "NONE")
            if sig in ("CASCADE_LONG", "CASCADE_SHORT") and self._dedup(f"liq:{sym}:{sig}"):
                await fire("liquidation_cascade", {
                    "side": "longs_liquidated" if sig == "CASCADE_LONG" else "shorts_liquidated",
                    "long_liquidated_usd_60s": st.get("liq_long_usd_60s"),
                    "short_liquidated_usd_60s": st.get("liq_short_usd_60s"),
                    "count_60s": st.get("liq_count_60s"), "venue": "Binance USD-M futures"}, sym)

        # strong flow signals with their track record
        try:
            from app.routes.flow import build_flow_response
            for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
                try:
                    doc = await build_flow_response(sym, update_oscillation=False)
                except Exception:
                    continue
                if doc["signal"] in STRONG_SIGNALS and self._dedup(f"flow:{sym}:{doc['signal']}"):
                    rel = doc.get("reliability") or {}
                    await fire("strong_flow_signal", {
                        "signal": doc["signal"], "direction_bias": doc["direction_bias"],
                        "confidence": doc["confidence"], "price": doc["metrics"].get("price"),
                        "delta_30s_usd": doc["metrics"].get("delta_30s"),
                        "hit_rate_5m": (rel.get("hit_rate") or {}).get("5m"),
                        "reliability": rel.get("interpretation")}, sym)
        except Exception as e:
            logger.debug(f"flow events skipped: {e}")

        # composite verdict / direction
        for sym in DERIV_SYMBOLS:
            c = await self._json(KEY_COMPOSITE.format(sym))
            if not c:
                continue
            val = (c.get("verdict"), c.get("direction"))
            old = await self._changed(f"comp:{sym}", val)
            if old:
                await fire("composite_change", {"from": {"verdict": old[0], "direction": old[1]},
                                                "to": {"verdict": val[0], "direction": val[1]},
                                                "composite_score": c.get("composite_score"), "one_liner": c.get("one_liner")}, sym)

        # cortex regime
        m = await self._json("horus:maestro:state")
        if m:
            old = await self._changed("cortex", m.get("state"))
            if old:
                await fire("cortex_regime_change", {"from": old, "to": m.get("state"), "trust_score": m.get("trust_score")})

        # climate
        cl = await self._json("hta:state:wiseman_climate")
        if cl:
            val = (cl.get("market_mode"), cl.get("health"))
            old = await self._changed("climate", val)
            if old:
                await fire("climate_change", {"from": {"mode": old[0], "health": old[1]},
                                              "to": {"mode": val[0], "health": val[1]}, "confidence": cl.get("confidence")})

        # ignitions >= 0.8 (new in the last 30 minutes)
        try:
            dist = await redis_manager.redis.hgetall("horus:ignition_distribution")
            now = time.time()
            hot = {s: float(v) for s, v in dist.items() if _float(v) >= 0.8}
            fresh = [s for s in hot if now - self.seen_ignitions.get(s, 0) > 1800]
            for s in hot:
                self.seen_ignitions[s] = now
            if fresh:
                top = sorted(fresh, key=lambda s: -hot[s])[:15]
                await fire("ignition_alert", {"assets": [{"symbol": s, "ignition_score": round(hot[s], 3)} for s in top],
                                              "count": len(fresh)})
        except Exception as e:
            logger.debug(f"ignition events skipped: {e}")

        # US session phase
        phase = us_market.session()["phase"]
        old = await self._changed("us_phase", phase)
        if old:
            await fire("us_session_change", {"from": old, "to": phase})

        # new US trading halts
        halts = us_market._halts.get("items") or []
        keys = {f"{h['symbol']}|{h['halt_date']}|{h['halt_time_et']}": h for h in halts}
        new = [h for k, h in keys.items() if k not in self.seen_halts]
        self.seen_halts.update(keys)
        if self.initialized:
            for h in new[:20]:
                await fire("trading_halt", h, h["symbol"])

        self.initialized = True
        await redis_manager.redis.set(HEARTBEAT_KEY, json.dumps({"timestamp": time.time()}), ex=300)
        return out


def _float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


_detector = Detector()


async def detector_loop():
    await asyncio.sleep(45)
    while True:
        try:
            if redis_manager.redis:
                await _detector.tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"event detector error: {e}")
        await asyncio.sleep(DETECT_INTERVAL)


# ─────────────────────────── webhooks ───────────────────────────
def validate_webhook_url(url: str) -> str:
    """https only, no credentials, and the host must resolve to public addresses only (SSRF guard)."""
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("Webhook URL must be https://host/path without credentials.")
    if p.port not in (None, 443, 8443):
        raise ValueError("Webhook URL must use port 443 or 8443.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Webhook host does not resolve.")
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise ValueError("Webhook host must resolve to a public IP address.")
    return url


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


async def create_webhook(api_key: str, url: str, types: List[str]) -> Dict[str, Any]:
    r = redis_manager.redis
    owner = owner_id(api_key)
    mine = [h for h in await list_webhooks(api_key, reveal=True)]
    if len(mine) >= MAX_WEBHOOKS_PER_OWNER:
        raise ValueError(f"Limit of {MAX_WEBHOOKS_PER_OWNER} webhooks per key reached.")
    bad = [t for t in types if t not in EVENT_TYPES]
    if bad:
        raise ValueError(f"Unknown event types: {bad}. Valid: {list(EVENT_TYPES)}")
    validate_webhook_url(url)
    hook = {"id": "wh_" + secrets.token_hex(8), "owner": owner, "url": url, "types": types or list(EVENT_TYPES),
            "secret": "whsec_" + secrets.token_hex(24), "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "consecutive_failures": 0, "disabled": False}
    await r.hset(WEBHOOKS_KEY, hook["id"], json.dumps(hook))
    return hook


async def list_webhooks(api_key: str, reveal: bool = False) -> List[Dict[str, Any]]:
    owner = owner_id(api_key)
    out = []
    for _, raw in (await redis_manager.redis.hgetall(WEBHOOKS_KEY)).items():
        h = json.loads(raw)
        if h["owner"] == owner:
            if not reveal:
                h = {k: v for k, v in h.items() if k not in ("secret", "owner")}
            out.append(h)
    return out


async def delete_webhook(api_key: str, hook_id: str) -> bool:
    raw = await redis_manager.redis.hget(WEBHOOKS_KEY, hook_id)
    if not raw or json.loads(raw)["owner"] != owner_id(api_key):
        return False
    await redis_manager.redis.hdel(WEBHOOKS_KEY, hook_id)
    return True


async def deliver(session: aiohttp.ClientSession, hook: Dict[str, Any], event: Dict[str, Any]) -> bool:
    body = json.dumps(event).encode()
    ts = str(int(time.time()))
    headers = {"Content-Type": "application/json", "User-Agent": "HorusFlow-Webhooks/1.0",
               "X-Horus-Event": event["type"], "X-Horus-Event-Id": str(event["id"]),
               "X-Horus-Timestamp": ts, "X-Horus-Signature": sign(hook["secret"], ts, body)}
    for attempt, delay in enumerate((0, 2, 6)):
        if delay:
            await asyncio.sleep(delay)
        try:
            validate_webhook_url(hook["url"])  # re-check at send time (DNS rebinding)
            async with session.post(hook["url"], data=body, headers=headers, allow_redirects=False,
                                    timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            continue
    return False


async def _record_result(hook_id: str, ok: bool):
    r = redis_manager.redis
    raw = await r.hget(WEBHOOKS_KEY, hook_id)
    if not raw:
        return
    h = json.loads(raw)
    h["consecutive_failures"] = 0 if ok else h.get("consecutive_failures", 0) + 1
    h["last_delivery_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    h["last_delivery_ok"] = ok
    if h["consecutive_failures"] >= WEBHOOK_DISABLE_AFTER:
        h["disabled"] = True
    await r.hset(WEBHOOKS_KEY, hook_id, json.dumps(h))


async def webhook_loop():
    async with aiohttp.ClientSession() as session:
        while True:
            event = await _webhook_queue.get()
            try:
                hooks = [json.loads(v) for v in (await redis_manager.redis.hgetall(WEBHOOKS_KEY)).values()]
                targets = [h for h in hooks if not h.get("disabled") and event["type"] in h["types"]]
                results = await asyncio.gather(*[deliver(session, h, event) for h in targets], return_exceptions=True)
                for h, res in zip(targets, results):
                    await _record_result(h["id"], res is True)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"webhook dispatch error: {e}")
