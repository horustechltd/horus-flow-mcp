# -*- coding: utf-8 -*-
"""
Horus Flow API — endpoints built for AI agents.

  GET  /v1/track-record                 public   live hit rates of every signal
  GET  /v1/track-record/signals         BUILDER  point-in-time signal ledger with outcomes
  GET  /v1/events                       BUILDER  recent events since an id
  GET  /v1/events/stream                BUILDER  Server-Sent Events stream
  POST /v1/webhooks                     PRO      register a signed webhook
  GET  /v1/webhooks                     PRO      list your webhooks
  DELETE /v1/webhooks/{id}              PRO      delete a webhook
  POST /v1/webhooks/{id}/test           PRO      send a test event
  GET  /v1/equity/session               public   US session phase, holidays, next open/close, active halts
  GET  /v1/equity/halts                 public   all US trading halts published today
  GET  /v1/cross-asset                  BUILDER  BTC order flow next to US equities flow (IEX sample)
"""
import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app import events, track_record, us_market
from app.auth import require_tier

router_agents = APIRouter()
_streams_per_key: Dict[str, int] = defaultdict(int)
MAX_STREAMS_PER_KEY = 3
MAX_STREAMS_TOTAL = 500


def _ts(value: Optional[str], default: float) -> float:
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        raise HTTPException(status_code=400, detail={"error": "bad_time", "message": f"Cannot parse time '{value}'. Use ISO 8601 or epoch seconds."})


# ─────────────────────────── track record ───────────────────────────
@router_agents.get("/track-record", tags=["Agents"])
async def get_track_record(window: str = Query("30d", pattern="^(30d|all)$"),
                           detail: bool = Query(False, description="Include per signal and symbol breakdown")):
    """Live, public hit rates of every directional signal at 1/5/15/30 minutes. No key required."""
    stats = track_record.current_stats()
    if not stats:
        raise HTTPException(status_code=503, detail={"error": "data_unavailable", "message": "Track record is loading."})
    w = stats["windows"][window]
    out = {
        "generated_at": stats["generated_at"],
        "window": window,
        "ledger": stats["ledger"],
        "method": stats["method"],
        "coin_flip": 0.5,
        "overall": w["overall"],
        "by_signal": w["by_signal"],
        "by_confidence": w["by_confidence"],
        "point_in_time_ledger": "/v1/track-record/signals?symbol=BTCUSDT&start=2026-10-01&end=2026-10-08",
    }
    if detail:
        out["by_signal_and_symbol"] = w["by_signal_and_symbol"]
    return out


@router_agents.get("/track-record/signals", tags=["Agents"])
async def get_signal_ledger(symbol: str = Query("BTCUSDT"),
                            start: Optional[str] = Query(None, description="ISO 8601 or epoch seconds; default 24h ago"),
                            end: Optional[str] = Query(None, description="ISO 8601 or epoch seconds; default now"),
                            limit: int = Query(1000, ge=1, le=5000),
                            auth: dict = Depends(require_tier("BUILDER"))):
    """What Horus said, when, at what price, and what the market did 1/5/15/30 minutes later. Use it to backtest."""
    sym = symbol.upper()
    if sym not in track_record.TRACKED_SYMBOLS:
        raise HTTPException(status_code=404, detail={"error": "not_tracked", "tracked": list(track_record.TRACKED_SYMBOLS)})
    now = time.time()
    t1 = _ts(end, now)
    t0 = _ts(start, t1 - 86400)
    if t1 <= t0 or t1 - t0 > 31 * 86400:
        raise HTTPException(status_code=400, detail={"error": "bad_range", "message": "end must be after start, at most 31 days apart."})
    rows = await asyncio.to_thread(track_record.query_signals, sym, t0, t1, limit)
    return {"symbol": sym, "start_utc": datetime.fromtimestamp(t0, timezone.utc).isoformat(),
            "end_utc": datetime.fromtimestamp(t1, timezone.utc).isoformat(), "count": len(rows),
            "truncated": len(rows) >= limit, "method": track_record.METHOD, "signals": rows}


# ─────────────────────────── events ───────────────────────────
def _types(param: Optional[str]):
    if not param:
        return None
    t = {x.strip() for x in param.split(",") if x.strip()}
    bad = t - set(events.EVENT_TYPES)
    if bad:
        raise HTTPException(status_code=400, detail={"error": "unknown_event_type", "unknown": sorted(bad), "valid": list(events.EVENT_TYPES)})
    return t


@router_agents.get("/events", tags=["Agents"])
async def get_events(since_id: int = Query(0, ge=0), types: Optional[str] = Query(None, description="Comma-separated event types"),
                     limit: int = Query(100, ge=1, le=500), auth: dict = Depends(require_tier("BUILDER"))):
    """Events newer than since_id, oldest first. Poll with the last id you received."""
    ev = await events.recent(since_id, _types(types), limit)
    return {"count": len(ev), "last_id": ev[-1]["id"] if ev else since_id, "event_types": list(events.EVENT_TYPES), "events": ev}


@router_agents.get("/events/stream", tags=["Agents"])
async def stream_events(request: Request, since_id: int = Query(0, ge=0), types: Optional[str] = Query(None),
                        auth: dict = Depends(require_tier("BUILDER"))):
    """Server-Sent Events. Sends missed events since since_id, then live events, with a keep-alive every 15s."""
    wanted = _types(types)
    key = auth["key"]
    if _streams_per_key[key] >= MAX_STREAMS_PER_KEY or sum(_streams_per_key.values()) >= MAX_STREAMS_TOTAL:
        raise HTTPException(status_code=429, detail={"error": "too_many_streams", "max_per_key": MAX_STREAMS_PER_KEY})
    _streams_per_key[key] += 1
    q = events.subscribe()

    async def gen():
        try:
            yield "retry: 5000\n\n"
            for e in await events.recent(since_id, wanted, 500) if since_id else []:
                yield f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(e)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if wanted and e["type"] not in wanted:
                    continue
                yield f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(e)}\n\n"
        finally:
            events.unsubscribe(q)
            _streams_per_key[key] -= 1

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ─────────────────────────── webhooks ───────────────────────────
@router_agents.post("/webhooks", tags=["Agents"])
async def create_webhook(payload: Dict[str, Any] = Body(..., examples=[{"url": "https://example.com/horus", "types": ["liquidation_cascade"]}]),
                         auth: dict = Depends(require_tier("PRO"))):
    """Register a webhook. Deliveries are POSTed as JSON and signed:
    X-Horus-Signature = sha256 HMAC of "<X-Horus-Timestamp>.<body>" with the returned secret."""
    try:
        hook = await events.create_webhook(auth["key"], str(payload.get("url", "")), list(payload.get("types") or []))
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "invalid_webhook", "message": str(e)})
    return {k: v for k, v in hook.items() if k != "owner"} | {"note": "Store the secret now; it is not shown again."}


@router_agents.get("/webhooks", tags=["Agents"])
async def get_webhooks(auth: dict = Depends(require_tier("PRO"))):
    return {"webhooks": await events.list_webhooks(auth["key"])}


@router_agents.delete("/webhooks/{hook_id}", tags=["Agents"])
async def remove_webhook(hook_id: str, auth: dict = Depends(require_tier("PRO"))):
    if not await events.delete_webhook(auth["key"], hook_id):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"deleted": hook_id}


@router_agents.post("/webhooks/{hook_id}/test", tags=["Agents"])
async def test_webhook(hook_id: str, auth: dict = Depends(require_tier("PRO"))):
    hooks = {h["id"]: h for h in await events.list_webhooks(auth["key"], reveal=True)}
    if hook_id not in hooks:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    import aiohttp
    test_event = {"id": 0, "type": "test", "symbol": None, "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "data": {"message": "Horus Flow webhook test"}}
    async with aiohttp.ClientSession() as s:
        ok = await events.deliver(s, hooks[hook_id], test_event)
    return {"delivered": ok}


# ─────────────────────────── US equities context ───────────────────────────
@router_agents.get("/equity/session", tags=["Agents"])
async def equity_session():
    """US equity session phase, holidays, early closes, next open/close and active trading halts. No key required."""
    h = us_market.halts_view(limit=10)
    return us_market.session() | {"halts": {k: h[k] for k in ("source", "fetched_at_utc", "active_count", "active")}}


@router_agents.get("/equity/halts", tags=["Agents"])
async def equity_halts(limit: int = Query(100, ge=1, le=500)):
    """US trading halts published today by Nasdaq Trader, with plain-language reasons. No key required."""
    return us_market.halts_view(limit=limit) | {"today": us_market._halts["items"][:limit]}


CROSS_WINDOW_S = 300
MIN_TRADES = {"crypto": 50, "equity": 30}


def window_flow(flow_detector, symbol: str, seconds: int = CROSS_WINDOW_S) -> Dict[str, Any]:
    """Aggressive buy share and trade count over a window, from the in-memory trade buffer."""
    now = time.time()
    trades = [t for t in list(flow_detector._trades.get(symbol, [])) if now - t["ts"] <= seconds]
    buy = sum(t["notional"] for t in trades if not t["is_sell"])
    total = sum(t["notional"] for t in trades)
    return {"trades": len(trades), "buy_ratio": round(buy / total, 3) if total else None,
            "price": trades[-1]["price"] if trades else None}


def _skew(buy_ratio: Optional[float], trades: int = 10 ** 9, min_trades: int = 0) -> str:
    if buy_ratio is None:
        return "NO_DATA"
    if trades < min_trades:
        return "THIN_SAMPLE"
    if buy_ratio >= 0.6:
        return "BUYING"
    if buy_ratio <= 0.4:
        return "SELLING"
    return "BALANCED"


@router_agents.get("/cross-asset", tags=["Agents"])
async def cross_asset(auth: dict = Depends(require_tier("BUILDER"))):
    """
    BTC order flow next to US equities: SPY, QQQ, and crypto-linked stocks and ETFs (COIN, MSTR, IBIT).
    When the US market is closed, BTC is the only live risk market and the response says so.
    Equity flow comes from the IEX feed (about 3% of US volume): treat it as a sample.
    """
    from app.feeds.alpaca_ws import alpaca_ws_manager
    from app.redis_client import redis_manager
    from app.routes.flow import build_flow_response

    from app.feeds.binance_ws import ws_manager
    sess = us_market.session()
    btc = None
    try:
        f = await build_flow_response("BTCUSDT", update_oscillation=False)
        w = window_flow(ws_manager.flow, "BTCUSDT")
        btc = {"signal": f["signal"], "direction_bias": f["direction_bias"], "price": f["metrics"].get("price"),
               "buy_ratio_5m": w["buy_ratio"], "trades_5m": w["trades"],
               "flow_skew": _skew(w["buy_ratio"], w["trades"], MIN_TRADES["crypto"])}
    except HTTPException:
        pass
    cortex = None
    if redis_manager.redis:
        raw = await redis_manager.redis.get("horus:maestro:state")
        if raw:
            c = json.loads(raw)
            cortex = {"regime_state": c.get("state"), "trust_score": c.get("trust_score"),
                      "btc_1h_return_pct": c.get("btc_1h_return_pct")}

    equities: Dict[str, Any] = {}
    us_live = sess["phase"] in ("pre_market", "regular", "after_hours")
    for sym in ("SPY", "QQQ", "COIN", "MSTR", "IBIT"):
        w = window_flow(alpaca_ws_manager.flow, sym) if us_live else None
        if w and w["trades"] > 0:
            equities[sym] = {"buy_ratio_5m": w["buy_ratio"], "trades_5m": w["trades"], "price": w["price"],
                             "flow_skew": _skew(w["buy_ratio"], w["trades"], MIN_TRADES["equity"])}
        else:
            equities[sym] = {"flow_skew": "NO_DATA" if us_live else "MARKET_CLOSED"}

    if not us_live:
        alignment = "CRYPTO_ONLY"
        note = f"US equities are closed until {sess['next_open_et']}. BTC flow is the only live risk gauge."
    else:
        b = (btc or {}).get("flow_skew")
        us = [equities[s]["flow_skew"] for s in ("SPY", "QQQ") if equities[s]["flow_skew"] in ("BUYING", "SELLING")]
        proxies = [equities[s]["flow_skew"] for s in ("COIN", "MSTR", "IBIT") if equities[s]["flow_skew"] in ("BUYING", "SELLING")]
        if b in ("BUYING", "SELLING") and us and all(x == b for x in us):
            alignment = "RISK_ON_ALIGNED" if b == "BUYING" else "RISK_OFF_ALIGNED"
        elif b in ("BUYING", "SELLING") and us and all(x != b for x in us):
            alignment = "DIVERGENT"
        else:
            alignment = "MIXED"
        note = "Crypto-linked equities " + ("confirm BTC flow." if proxies and b in proxies and len(set(proxies)) == 1
                                            else "do not confirm BTC flow." if proxies and b not in proxies
                                            else "show no clear skew.")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "us_session": {k: sess[k] for k in ("phase", "next_open_et", "next_close_et", "minutes_to_close")},
        "btc": btc, "cortex": cortex, "us_equities": equities,
        "alignment": alignment, "note": note,
        "windows": ("Flow skews use aggressive trades over the last 5 minutes (BUYING >= 60% of notional bought, "
                    "SELLING <= 40%). Fewer than 50 crypto or 30 equity trades is reported as THIN_SAMPLE."),
        "data_source": {"crypto": "Binance spot public stream", "equities": "IEX via Alpaca, about 3% of US consolidated volume (sample)"},
    }
