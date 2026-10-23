# -*- coding: utf-8 -*-
"""
Horus Flow API — Market Scanner for AI agents
=============================================
One question instead of hundreds of calls: "where are buyers in control right now?",
"which markets have a volume surge?", "which breakout candidates have buyers behind them?".

Universe: Binance USDT-margined perpetuals with 24h volume >= SCAN_MIN_VOLUME (about 190 markets).
Every cycle (60s) it refreshes the 24h tickers and funding for all perpetuals, and the 5-minute
candles for half of the universe, so every market is at most ~2 minutes old. From the candles:

  change_15m_pct, change_1h_pct      price change over the last 3 and 12 five-minute candles
  taker_buy_ratio_15m / _1h          share of traded notional bought by aggressive buyers
  net_taker_flow_15m_usd             aggressive buys minus aggressive sells, in USD
  volume_surge                       average 5m volume of the last 15m vs the 45m before it

Ignition scores come from the existing breakout scanner. Picks of the main presets are recorded
every 15 minutes (calibration_data/scanner_ledger.db) so their accuracy can be measured later.
"""
import asyncio
import json
import logging
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("API.MarketScanner")

FAPI = "https://fapi.binance.com"
SCAN_MIN_VOLUME = 5_000_000
MAX_UNIVERSE = 250
CYCLE_SECONDS = 60
KLINE_CONCURRENCY = 8
LEDGER_PATH = os.getenv("SCANNER_LEDGER_DB", "/root/horus_flow_api/calibration_data/scanner_ledger.db")
LEDGER_EVERY = 900
LEDGER_PRESETS = ("buyers_in_control", "sellers_in_control", "breakout_candidates")

_state: Dict[str, Any] = {"rows": {}, "universe": [], "cycle_at": 0.0, "tickers_at": 0.0, "cursor": 0,
                          "last_ledger": 0.0, "errors": 0}

PRESETS: Dict[str, Dict[str, Any]] = {
    "buyers_in_control": {
        "description": "Aggressive buyers took at least 58% of traded notional over 15 minutes and price is up.",
        "filter": lambda r: r["taker_buy_ratio_15m"] >= 0.58 and r["change_15m_pct"] > 0,
        "sort": lambda r: -r["net_taker_flow_15m_usd"]},
    "sellers_in_control": {
        "description": "Aggressive sellers took at least 58% of traded notional over 15 minutes and price is down.",
        "filter": lambda r: r["taker_buy_ratio_15m"] <= 0.42 and r["change_15m_pct"] < 0,
        "sort": lambda r: r["net_taker_flow_15m_usd"]},
    "volume_surge": {
        "description": "Volume over the last 15 minutes is at least twice the pace of the 45 minutes before.",
        "filter": lambda r: r["volume_surge"] >= 2.0,
        "sort": lambda r: -r["volume_surge"]},
    "breakout_candidates": {
        "description": "Ignition score >= 0.7, volume surging (>= 1.5x) and buyers slightly ahead (>= 52%).",
        "filter": lambda r: (r.get("ignition_score") or 0) >= 0.7 and r["volume_surge"] >= 1.5 and r["taker_buy_ratio_15m"] >= 0.52,
        "sort": lambda r: -(r.get("ignition_score") or 0)},
    "crowded_funding": {
        "description": "Funding at or beyond +/-0.05% per 8h: one side of the market is paying heavily to hold positions.",
        "filter": lambda r: r["funding_rate"] is not None and abs(r["funding_rate"]) >= 0.0005,
        "sort": lambda r: -abs(r["funding_rate"] or 0)},
    "top_movers": {
        "description": "Largest absolute price change over the last hour.",
        "filter": lambda r: True,
        "sort": lambda r: -abs(r["change_1h_pct"])},
}


# ─────────────────────────── pure computations ───────────────────────────
def metrics_from_klines(klines: List[list]) -> Optional[Dict[str, float]]:
    """klines: Binance 5m candles, oldest first, at least 12. Index 1 open, 4 close, 7 quote volume, 10 taker buy quote volume."""
    if not klines or len(klines) < 12:
        return None
    k = klines[-12:]
    f = lambda c, i: float(c[i])
    qv = [f(c, 7) for c in k]
    tb = [f(c, 10) for c in k]
    last3_q, last3_tb = sum(qv[-3:]), sum(tb[-3:])
    prev9_q = sum(qv[:-3])
    open_15m, open_1h, close = f(k[-3], 1), f(k[0], 1), f(k[-1], 4)
    if open_15m <= 0 or open_1h <= 0:
        return None
    return {
        "price": close,
        "change_15m_pct": round((close / open_15m - 1) * 100, 3),
        "change_1h_pct": round((close / open_1h - 1) * 100, 3),
        "taker_buy_ratio_15m": round(last3_tb / last3_q, 3) if last3_q else 0.5,
        "taker_buy_ratio_1h": round(sum(tb) / sum(qv), 3) if sum(qv) else 0.5,
        "net_taker_flow_15m_usd": round(2 * last3_tb - last3_q, 0),
        "volume_15m_usd": round(last3_q, 0),
        "volume_surge": round((last3_q / 3) / (prev9_q / 9), 2) if prev9_q > 0 else 0.0,
    }


def run_query(rows: Dict[str, Dict[str, Any]], preset: Optional[str] = None, limit: int = 20,
              min_volume_24h: float = SCAN_MIN_VOLUME, filters: Optional[Dict[str, Optional[float]]] = None,
              sort_by: Optional[str] = None, descending: bool = True) -> List[Dict[str, Any]]:
    data = [r for r in rows.values() if r.get("volume_24h_usd", 0) >= min_volume_24h and "taker_buy_ratio_15m" in r]
    if preset:
        p = PRESETS[preset]
        data = sorted((r for r in data if p["filter"](r)), key=p["sort"])
    else:
        f = filters or {}
        def ok(r):
            checks = [("min_taker_buy_ratio", "taker_buy_ratio_15m", lambda v, x: v >= x),
                      ("max_taker_buy_ratio", "taker_buy_ratio_15m", lambda v, x: v <= x),
                      ("min_volume_surge", "volume_surge", lambda v, x: v >= x),
                      ("min_ignition", "ignition_score", lambda v, x: (v or 0) >= x),
                      ("min_change_15m", "change_15m_pct", lambda v, x: v >= x),
                      ("max_change_15m", "change_15m_pct", lambda v, x: v <= x),
                      ("min_abs_funding", "funding_rate", lambda v, x: v is not None and abs(v) >= x)]
            return all(test(r.get(field), f[name]) for name, field, test in checks if f.get(name) is not None)
        key = sort_by or "net_taker_flow_15m_usd"
        data = sorted((r for r in data if ok(r)), key=lambda r: (r.get(key) is None, r.get(key) or 0), reverse=descending)
        if descending:  # keep None last after reverse
            data = [r for r in data if r.get(key) is not None] + [r for r in data if r.get(key) is None]
    return data[:limit]


def coverage() -> Dict[str, Any]:
    now = time.time()
    ages = [now - r["updated_at"] for r in _state["rows"].values() if "updated_at" in r and "taker_buy_ratio_15m" in r]
    return {"universe": len(_state["universe"]), "with_candles": len(ages),
            "oldest_seconds": int(max(ages)) if ages else None,
            "last_cycle_seconds_ago": int(now - _state["cycle_at"]) if _state["cycle_at"] else None}


def public_row(r: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("symbol", "price", "change_15m_pct", "change_1h_pct", "change_24h_pct", "volume_24h_usd", "volume_surge",
            "taker_buy_ratio_15m", "taker_buy_ratio_1h", "net_taker_flow_15m_usd", "funding_rate", "ignition_score")
    out = {k: r.get(k) for k in keys}
    out["data_age_s"] = int(time.time() - r["updated_at"]) if r.get("updated_at") else None
    return out


# ─────────────────────────── I/O ───────────────────────────
async def _json(session: aiohttp.ClientSession, url: str):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
        if r.status in (418, 429):
            raise RuntimeError(f"rate limited ({r.status})")
        r.raise_for_status()
        return await r.json()


async def _refresh_tickers(session: aiohttp.ClientSession, redis) -> None:
    tickers = await _json(session, f"{FAPI}/fapi/v1/ticker/24hr")
    premium = await _json(session, f"{FAPI}/fapi/v1/premiumIndex")
    funding = {p["symbol"]: float(p.get("lastFundingRate") or 0) for p in premium}
    ign = {}
    if redis:
        try:
            ign = {s.replace("/", ""): float(v) for s, v in (await redis.hgetall("horus:ignition_distribution")).items()}
        except Exception:
            ign = {}
    perps = []
    for t in tickers:
        sym = t["symbol"]
        if not sym.endswith("USDT") or sym not in funding:
            continue
        vol = float(t.get("quoteVolume") or 0)
        row = _state["rows"].setdefault(sym, {"symbol": sym})
        row.update(volume_24h_usd=round(vol, 0), change_24h_pct=round(float(t.get("priceChangePercent") or 0), 3),
                   funding_rate=funding.get(sym), ignition_score=ign.get(sym))
        if vol >= SCAN_MIN_VOLUME:
            perps.append((vol, sym))
    _state["universe"] = [s for _, s in sorted(perps, reverse=True)[:MAX_UNIVERSE]]
    _state["tickers_at"] = time.time()


async def _refresh_klines(session: aiohttp.ClientSession, symbols: List[str]) -> None:
    sem = asyncio.Semaphore(KLINE_CONCURRENCY)

    async def one(sym):
        async with sem:
            try:
                k = await _json(session, f"{FAPI}/fapi/v1/klines?symbol={sym}&interval=5m&limit=12")
                m = metrics_from_klines(k)
                if m:
                    _state["rows"][sym].update(m, updated_at=time.time())
            except Exception as e:
                _state["errors"] += 1
                if "rate limited" in str(e):
                    raise
    await asyncio.gather(*[one(s) for s in symbols], return_exceptions=True)


def _ledger_record(ts: float) -> None:
    con = sqlite3.connect(LEDGER_PATH)
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS picks (ts REAL, preset TEXT, rank INTEGER, symbol TEXT, price REAL,
                       taker_buy_ratio_15m REAL, volume_surge REAL, ignition_score REAL)""")
        rows = []
        for preset in LEDGER_PRESETS:
            for i, r in enumerate(run_query(_state["rows"], preset, 5), 1):
                rows.append((ts, preset, i, r["symbol"], r["price"], r["taker_buy_ratio_15m"], r["volume_surge"], r.get("ignition_score")))
        con.executemany("INSERT INTO picks VALUES (?,?,?,?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()


async def scanner_loop(redis_manager, record_ledger: bool = True):
    await asyncio.sleep(10)
    async with aiohttp.ClientSession() as session:
        while True:
            started = time.time()
            try:
                await _refresh_tickers(session, redis_manager.redis)
                uni = _state["universe"]
                half = math.ceil(len(uni) / 2) or 1
                batch = uni[_state["cursor"]:_state["cursor"] + half]
                _state["cursor"] = (_state["cursor"] + half) % max(len(uni), 1)
                await _refresh_klines(session, batch)
                _state["cycle_at"] = time.time()
                if redis_manager.redis:
                    await redis_manager.redis.set("horus:api:scanner:heartbeat", json.dumps({"timestamp": time.time(), **coverage()}), ex=600)
                if record_ledger and time.time() - _state["last_ledger"] >= LEDGER_EVERY and coverage()["with_candles"] >= 0.8 * len(uni):
                    _state["last_ledger"] = time.time()
                    await asyncio.to_thread(_ledger_record, _state["last_ledger"])
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"scanner cycle error: {e}")
                if "rate limited" in str(e):
                    await asyncio.sleep(120)
            await asyncio.sleep(max(5.0, CYCLE_SECONDS - (time.time() - started)))
