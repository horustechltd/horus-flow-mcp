# -*- coding: utf-8 -*-
"""
Horus Flow API — endpoints built for AI agents.

  GET  /v1/track-record                 public   live hit rates of every signal
  GET  /v1/track-record/signals         BUILDER  point-in-time signal ledger with outcomes (free: last 24h, 20 rows)
  GET  /v1/events                       BUILDER  recent events since an id (free: 3 events, 15 minutes late)
  GET  /v1/events/stream                BUILDER  Server-Sent Events stream
  POST /v1/webhooks                     PRO      register a signed webhook
  GET  /v1/webhooks                     PRO      list your webhooks
  DELETE /v1/webhooks/{id}              PRO      delete a webhook
  POST /v1/webhooks/{id}/test           PRO      send a test event
  GET  /v1/equity/session               public   US session phase, holidays, next open/close, active halts
  GET  /v1/equity/halts                 public   all US trading halts published today
  GET  /v1/cross-asset                  BUILDER  BTC order flow next to US equities flow (free: SPY and QQQ)
  GET  /v1/book/pressure                public   order-book pressure across 30 Binance spot pairs (free: 3 rows)

Endpoints marked "free:" serve lower plans a live preview with an "upgrade" block instead of a 403.
"""
import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app import book_measure, events, track_record, us_market, market_scanner
from app.auth import require_tier, tier_or_preview, upgrade_block, verify_api_key, tier_level

router_agents = APIRouter()
_streams_per_key: Dict[str, int] = defaultdict(int)
MAX_STREAMS_PER_KEY = 3
MAX_STREAMS_TOTAL = 500
PREVIEW_SIGNAL_ROWS = 20
PREVIEW_EVENTS = 3
PREVIEW_EVENT_DELAY_S = 900
PREVIEW_EQUITIES = ("SPY", "QQQ")


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
                            auth: dict = Depends(tier_or_preview("BUILDER"))):
    """What Horus said, when, at what price, and what the market did 1/5/15/30 minutes later. Use it to backtest."""
    sym = symbol.upper()
    if sym not in track_record.TRACKED_SYMBOLS:
        raise HTTPException(status_code=404, detail={"error": "not_tracked", "tracked": list(track_record.TRACKED_SYMBOLS)})
    now = time.time()
    t1 = _ts(end, now)
    t0 = _ts(start, t1 - 86400)
    if t1 <= t0 or t1 - t0 > 31 * 86400:
        raise HTTPException(status_code=400, detail={"error": "bad_range", "message": "end must be after start, at most 31 days apart."})
    if auth["preview"]:
        t0, t1, limit = now - 86400, now, min(limit, PREVIEW_SIGNAL_ROWS)
    rows = await asyncio.to_thread(track_record.query_signals, sym, t0, t1, limit)
    out = {"symbol": sym, "start_utc": datetime.fromtimestamp(t0, timezone.utc).isoformat(),
           "end_utc": datetime.fromtimestamp(t1, timezone.utc).isoformat(), "count": len(rows),
           "truncated": len(rows) >= limit, "method": track_record.METHOD, "signals": rows}
    if auth["preview"]:
        out["upgrade"] = upgrade_block(auth, auth["min_level"], "Any 31-day window since the ledger started, up to 5,000 rows per call",
                                       f"The first {PREVIEW_SIGNAL_ROWS} signals of the last 24 hours on your plan")
    return out


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
                     limit: int = Query(100, ge=1, le=500), auth: dict = Depends(tier_or_preview("BUILDER"))):
    """Events newer than since_id, oldest first. Poll with the last id you received."""
    if not auth["preview"]:
        ev = await events.recent(since_id, _types(types), limit)
        return {"count": len(ev), "last_id": ev[-1]["id"] if ev else since_id, "event_types": list(events.EVENT_TYPES), "events": ev}
    cutoff = time.time() - PREVIEW_EVENT_DELAY_S
    ev = [e for e in await events.recent(since_id, _types(types), 500)
          if datetime.fromisoformat(e["time_utc"]).timestamp() <= cutoff][-min(limit, PREVIEW_EVENTS):]
    return {"count": len(ev), "last_id": ev[-1]["id"] if ev else since_id, "event_types": list(events.EVENT_TYPES), "events": ev,
            "upgrade": upgrade_block(auth, auth["min_level"], "Every event as it happens, the live stream (/v1/events/stream) and signed webhooks",
                                     f"The last {PREVIEW_EVENTS} events, {PREVIEW_EVENT_DELAY_S // 60} minutes late, on your plan")}


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
async def cross_asset(auth: dict = Depends(tier_or_preview("BUILDER"))):
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
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "us_session": {k: sess[k] for k in ("phase", "next_open_et", "next_close_et", "minutes_to_close")},
        "btc": btc, "cortex": cortex, "us_equities": equities,
        "alignment": alignment, "note": note,
        "windows": ("Flow skews use aggressive trades over the last 5 minutes (BUYING >= 60% of notional bought, "
                    "SELLING <= 40%). Fewer than 50 crypto or 30 equity trades is reported as THIN_SAMPLE."),
        "data_source": {"crypto": "Binance spot public stream", "equities": "IEX via Alpaca, about 3% of US consolidated volume (sample)"},
    }
    if auth["preview"]:
        locked = [s for s in equities if s not in PREVIEW_EQUITIES]
        out["us_equities"] = {s: equities[s] for s in PREVIEW_EQUITIES}
        out.pop("cortex")
        out["locked_fields"] = ["cortex"] + [f"us_equities.{s}" for s in locked]
        out["upgrade"] = upgrade_block(auth, auth["min_level"], f"Cortex state and crypto-linked equities ({', '.join(locked)})",
                                       f"{' and '.join(PREVIEW_EQUITIES)} only on your plan")
    return out


# ─────────────────────────── market scanner ───────────────────────────
FREE_SCAN_ROWS = 3


@router_agents.get("/scan", tags=["Agents"])
async def scan_market(
    preset: str = Query("buyers_in_control", pattern="^(buyers_in_control|sellers_in_control|volume_surge|breakout_candidates|crowded_funding|top_movers|custom)$",
                        description="A ready question, or custom to use the filters below"),
    limit: int = Query(20, ge=1, le=100),
    min_volume_24h: float = Query(market_scanner.SCAN_MIN_VOLUME, ge=1_000_000, description="Minimum 24h futures volume in USD"),
    min_taker_buy_ratio: Optional[float] = Query(None, ge=0, le=1),
    max_taker_buy_ratio: Optional[float] = Query(None, ge=0, le=1),
    min_volume_surge: Optional[float] = Query(None, ge=0),
    min_ignition: Optional[float] = Query(None, ge=0, le=1),
    min_change_15m: Optional[float] = Query(None),
    max_change_15m: Optional[float] = Query(None),
    min_abs_funding: Optional[float] = Query(None, ge=0),
    sort_by: str = Query("net_taker_flow_15m_usd", pattern="^(net_taker_flow_15m_usd|taker_buy_ratio_15m|volume_surge|change_15m_pct|change_1h_pct|change_24h_pct|ignition_score|funding_rate|volume_24h_usd)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    auth: dict = Depends(verify_api_key),
):
    """
    Scan about 190 Binance USDT perpetuals (24h volume >= $5M) in one call. Every market is refreshed at
    least every ~2 minutes from 5-minute candles: price change, aggressive buy share, net taker flow in USD,
    volume surge, funding and ignition score. Rankings of current conditions, not predictions.
    Free plan: first 3 results. Paid plans: up to 100.
    """
    cov = market_scanner.coverage()
    if not cov["with_candles"]:
        raise HTTPException(status_code=503, detail={"error": "data_unavailable", "message": "Scanner is warming up. Retry in a minute."})
    filters = dict(min_taker_buy_ratio=min_taker_buy_ratio, max_taker_buy_ratio=max_taker_buy_ratio, min_volume_surge=min_volume_surge,
                   min_ignition=min_ignition, min_change_15m=min_change_15m, max_change_15m=max_change_15m, min_abs_funding=min_abs_funding)
    free = tier_level(auth.get("tier")) == 0
    cap = min(limit, FREE_SCAN_ROWS) if free else limit
    rows = market_scanner.run_query(market_scanner._state["rows"], None if preset == "custom" else preset, cap,
                                    min_volume_24h, filters, sort_by, order == "desc")
    results = [market_scanner.public_row(r) for r in rows]

    # attach Horus live order flow (with its measured hit rate) where Horus tracks the pair
    from app.feeds.binance_ws import ws_manager
    from app.routes.flow import build_flow_response
    for r in results:
        if r["symbol"] in ws_manager.symbols:
            try:
                f = await build_flow_response(r["symbol"], update_oscillation=False)
                rel = f.get("reliability") or {}
                r["horus_flow"] = {"signal": f["signal"], "direction_bias": f["direction_bias"],
                                   "hit_rate_5m": (rel.get("hit_rate") or {}).get("5m")}
            except HTTPException:
                pass

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "preset": preset,
        "criteria": market_scanner.PRESETS[preset]["description"] if preset != "custom" else
                    {k: v for k, v in filters.items() if v is not None} | {"sort_by": sort_by, "order": order},
        "coverage": cov,
        "count": len(results),
        "results": results,
        "fields": {
            "taker_buy_ratio_15m": "share of traded notional bought by aggressive buyers over 15 minutes (0.5 = balanced)",
            "net_taker_flow_15m_usd": "aggressive buys minus aggressive sells over 15 minutes, USD",
            "volume_surge": "average 5-minute volume of the last 15 minutes / the 45 minutes before",
            "funding_rate": "per 8 hours, Binance perpetual",
        },
        "note": "Rankings of current conditions, not predictions. Picks are recorded so their accuracy can be published later.",
        "data_source": "Binance USDT-margined perpetuals, 5-minute candles",
    }
    if free and limit > FREE_SCAN_ROWS:
        out["upgrade"] = upgrade_block(auth, 1, "Up to 100 results per scan", f"The first {FREE_SCAN_ROWS} results on your plan")
    return out


# ─────────────────────────── order-book pressure ───────────────────────────
FREE_BOOK_ROWS = 3
BOOK_MAX_AGE_S = 60


@router_agents.get("/book/pressure", tags=["Agents"])
async def book_pressure(
    sort: str = Query("bid", pattern="^(bid|ask)$", description="bid = strongest bid-side book first; ask = strongest ask side first"),
    limit: int = Query(30, ge=1, le=30),
    auth: dict = Depends(verify_api_key),
):
    """
    What the spot order book says right now across 30 deep Binance USDT pairs, in one call: the share of the
    top five levels' size on the bid side, the full-book bid/ask ratio and the last 30 seconds of taker flow,
    refreshed every 15 seconds. Comes with the measured link between this number and the next minute's move
    over the last 30 days. Free plan: first 3 rows. Paid plans: all 30.
    """
    from app.redis_client import redis_manager
    r = redis_manager.redis
    raw = await r.get(book_measure.LATEST_KEY) if r else None
    if not raw:
        raise HTTPException(status_code=503, detail={"error": "data_unavailable", "message": "Order-book recorder is starting. Retry in a minute."})
    doc = json.loads(raw)
    age = time.time() - doc["timestamp_epoch"]
    if age > BOOK_MAX_AGE_S:
        raise HTTPException(status_code=503, detail={"error": "data_stale", "age_seconds": int(age), "max_age_seconds": BOOK_MAX_AGE_S,
                                                     "message": "The order-book recorder has not refreshed recently. Not serving stale data."})
    rows = sorted(doc["rows"], key=lambda x: x["top5_imbalance"], reverse=(sort == "bid"))
    free = tier_level(auth.get("tier")) == 0
    cap = min(limit, FREE_BOOK_ROWS) if free else limit
    out = {
        "generated_at": datetime.fromtimestamp(doc["timestamp_epoch"], timezone.utc).isoformat(timespec="seconds"),
        "data_age_seconds": round(age, 1),
        "pairs_recorded": len(doc["rows"]),
        "sort": sort,
        "count": min(cap, len(rows)),
        "rows": [{"symbol": x["symbol"], "price": x["price"], "top5_imbalance": x["top5_imbalance"],
                  "book_tilt": book_measure.tilt(x["top5_imbalance"]), "bid_ask_ratio": x["bid_ask_ratio"],
                  "spread_pct": x["spread_pct"], "buy_sell_ratio_30s": x["buy_sell_ratio"],
                  "net_taker_flow_30s_usd": x["delta_30s"], "trades_30s": x["trade_count_30s"]} for x in rows[:cap]],
        "measured": await book_measure.current_measure(r),
        "fields": {
            "top5_imbalance": "share of the top five levels' size on the bid side (0.5 = even; BID_HEAVY >= 0.6, ASK_HEAVY <= 0.4)",
            "bid_ask_ratio": "total bid size / total ask size over the top 20 levels",
            "buy_sell_ratio_30s": "share of the last 30 seconds' traded notional bought by aggressive buyers",
            "net_taker_flow_30s_usd": "aggressive buys minus aggressive sells over the last 30 seconds, USD",
        },
        "note": "A reading of the book, not a prediction. 'measured' says how much this number has told about the next minute.",
        "data_source": "Binance spot order book (top 20 levels, 100 ms updates) and aggregated trades",
    }
    if free and limit > FREE_BOOK_ROWS:
        out["upgrade"] = upgrade_block(auth, 1, f"All {len(rows)} pairs, every 15 seconds", f"The first {FREE_BOOK_ROWS} pairs on your plan")
    return out
