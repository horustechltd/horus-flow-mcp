# -*- coding: utf-8 -*-
"""
Horus Flow API — Live Track Record
==================================
Every directional signal recorded by the Edge Proof engine (edge_proof.db) is
checked against the real Binance price 1, 5, 15 and 30 minutes later.
This module turns that ledger into numbers an AI agent can reason with:

  * hit rate per signal, per symbol, per horizon (last 30 days and all time)
  * average move in the signal's direction, in basis points
  * measured hit rate per confidence bucket (calibration)

It is attached to every flow response as `reliability`, published at
/v1/track-record, and the raw ledger is queryable at /v1/track-record/signals.
"""
import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("API.TrackRecord")

EDGE_DB = os.getenv("EDGE_PROOF_DB", "/root/horus_flow_api/calibration_data/edge_proof.db")
HORIZONS = ("1m", "5m", "15m", "30m")
MIN_SAMPLES = 100
REFRESH_SECONDS = 900
TRACKED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
CONF_BUCKETS: List[Tuple[float, float, str]] = [
    (0.0, 0.75, "<0.75"), (0.75, 0.85, "0.75-0.85"), (0.85, 0.95, "0.85-0.95"), (0.95, 1.01, ">=0.95"),
]
METHOD = (
    "Each directional signal (bullish or bearish) is recorded with the Binance price at emission, at most once per "
    "symbol and direction every 5 minutes. A hit means the price 1/5/15/30 minutes later moved in the signal's "
    "direction; an unchanged price counts as a miss. avg_directional_move_bps is the mean move in the signal's "
    "direction in basis points (negative = the market went the other way). Fees are not deducted. A coin flip scores 50%."
)

_cache: Dict[str, Any] = {"stats": None, "computed_at": 0.0}


def _bucket(conf: float) -> str:
    for lo, hi, name in CONF_BUCKETS:
        if lo <= conf < hi:
            return name
    return CONF_BUCKETS[-1][2]


def _empty() -> Dict[str, Any]:
    return {h: {"n": 0, "hits": 0, "ties": 0, "dir_sum": 0.0} for h in HORIZONS}


def _add(acc: Dict[str, Any], direction: str, moves: Tuple) -> None:
    sign = 1.0 if direction == "BULLISH" else -1.0
    for h, m in zip(HORIZONS, moves):
        if m is None:
            continue
        a = acc[h]
        a["n"] += 1
        d = sign * m
        if d > 0:
            a["hits"] += 1
        elif m == 0:
            a["ties"] += 1
        a["dir_sum"] += d


def _finish(acc: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for h, a in acc.items():
        n = a["n"]
        out[h] = {
            "samples": n,
            "hit_rate": round(a["hits"] / n, 4) if n else None,
            "tie_rate": round(a["ties"] / n, 4) if n else None,
            "avg_directional_move_bps": round(a["dir_sum"] / n * 100, 2) if n else None,
        }
    return out


def compute_stats(db_path: str = EDGE_DB, now: Optional[float] = None) -> Dict[str, Any]:
    now = now or time.time()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        first, last, total = con.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM predictions").fetchone()
        windows = {"30d": now - 30 * 86400, "all": 0.0}
        result: Dict[str, Any] = {
            "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "ledger": {
                "first_signal_utc": datetime.fromtimestamp(first, timezone.utc).isoformat() if first else None,
                "last_signal_utc": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
                "total_signals": total,
                "symbols": list(TRACKED_SYMBOLS),
            },
            "method": METHOD,
            "windows": {},
        }
        for wname, since in windows.items():
            rows = con.execute(
                "SELECT signal, symbol, direction_bias, confidence, move_pct_1m, move_pct_5m, move_pct_15m, move_pct_30m "
                "FROM predictions WHERE ts >= ?", (since,)).fetchall()
            overall, by_sig, by_sig_sym, by_conf = _empty(), {}, {}, {}
            for sig, sym, direction, conf, *moves in rows:
                if direction not in ("BULLISH", "BEARISH"):
                    continue
                moves = tuple(moves)
                _add(overall, direction, moves)
                _add(by_sig.setdefault(sig, _empty()), direction, moves)
                _add(by_sig_sym.setdefault(f"{sig}|{sym}", _empty()), direction, moves)
                _add(by_conf.setdefault(_bucket(conf or 0.0), _empty()), direction, moves)
            result["windows"][wname] = {
                "overall": _finish(overall),
                "by_signal": {k: _finish(v) for k, v in sorted(by_sig.items())},
                "by_signal_and_symbol": {k: _finish(v) for k, v in sorted(by_sig_sym.items())},
                "by_confidence": {k: _finish(v) for k, v in by_conf.items()},
            }
        return result
    finally:
        con.close()


def _interpret(hit: Optional[float], n: int, avg_bps: Optional[float] = None) -> str:
    if hit is None or n < MIN_SAMPLES:
        return "Not enough history to judge this signal yet."
    edge = hit - 0.5
    move = f", average move {avg_bps:+.1f} bps" if avg_bps is not None else ""
    if abs(edge) < 0.02:
        return f"Historically {hit:.0%} at 5 minutes (n={n:,}): close to a coin flip. Use as context, not as a trade trigger."
    if edge >= 0.05:
        return f"Historically {hit:.0%} at 5 minutes (n={n:,}{move}): a measurable directional edge before fees, small in size."
    if edge > 0:
        return f"Historically {hit:.0%} at 5 minutes (n={n:,}{move}): a slight edge before fees."
    if edge <= -0.05:
        return f"Historically {hit:.0%} at 5 minutes (n={n:,}): price more often moved the other way."
    return f"Historically {hit:.0%} at 5 minutes (n={n:,}): slightly worse than a coin flip."


def reliability_for(signal: str, symbol: str, confidence: float, direction_bias: str) -> Dict[str, Any]:
    """Reliability block attached to a flow response."""
    stats = _cache.get("stats")
    if direction_bias not in ("BULLISH", "BEARISH"):
        return {"directional": False, "note": "Non-directional reading; hit rates are tracked for bullish and bearish signals only."}
    if not stats:
        return {"directional": True, "note": "Track record is loading."}

    chosen, basis = None, None
    for wname in ("30d", "all"):
        w = stats["windows"].get(wname, {})
        for key, label in ((f"{signal}|{symbol}", f"{signal} on {symbol}"), (signal, f"{signal}, all tracked symbols")):
            src = w.get("by_signal_and_symbol" if "|" in key else "by_signal", {}).get(key)
            if src and src["5m"]["samples"] >= MIN_SAMPLES:
                chosen, basis = src, f"{label}, {'last 30 days' if wname == '30d' else 'since ' + stats['ledger']['first_signal_utc'][:10]}"
                break
        if chosen:
            break

    conf_stats = stats["windows"]["30d"]["by_confidence"].get(_bucket(confidence or 0.0), {}).get("5m", {})
    if not chosen:
        return {"directional": True, "basis": None, "samples": 0, "coin_flip": 0.5,
                "confidence_bucket_hit_rate_5m": conf_stats.get("hit_rate"),
                "interpretation": _interpret(None, 0),
                "track_record_url": "/v1/track-record"}
    return {
        "directional": True,
        "basis": basis,
        "samples": chosen["5m"]["samples"],
        "hit_rate": {h: chosen[h]["hit_rate"] for h in HORIZONS},
        "avg_directional_move_bps": {h: chosen[h]["avg_directional_move_bps"] for h in HORIZONS},
        "coin_flip": 0.5,
        "confidence_bucket_hit_rate_5m": conf_stats.get("hit_rate"),
        "interpretation": _interpret(chosen["5m"]["hit_rate"], chosen["5m"]["samples"], chosen["5m"]["avg_directional_move_bps"]),
        "track_record_url": "/v1/track-record",
    }


def query_signals(symbol: str, start: float, end: float, limit: int) -> List[Dict[str, Any]]:
    con = sqlite3.connect(f"file:{EDGE_DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT ts, signal, direction_bias, confidence, price_at_signal, "
            "move_pct_1m, move_pct_5m, move_pct_15m, move_pct_30m, correct_1m, correct_5m, correct_15m, correct_30m "
            "FROM predictions WHERE symbol = ? AND ts >= ? AND ts < ? ORDER BY ts LIMIT ?",
            (symbol, start, end, limit)).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        out.append({
            "time_utc": datetime.fromtimestamp(r[0], timezone.utc).isoformat(),
            "signal": r[1], "direction_bias": r[2], "confidence": r[3], "price": r[4],
            "move_pct": dict(zip(HORIZONS, r[5:9])),
            "hit": {h: (None if v is None else bool(v)) for h, v in zip(HORIZONS, r[9:13])},
        })
    return out


def current_stats() -> Optional[Dict[str, Any]]:
    return _cache.get("stats")


async def refresh_once() -> bool:
    try:
        stats = await asyncio.to_thread(compute_stats, EDGE_DB)
        _cache.update(stats=stats, computed_at=time.time())
        return True
    except Exception as e:
        logger.error(f"track record refresh failed: {e}")
        return False


async def track_record_loop():
    while True:
        await refresh_once()
        await asyncio.sleep(REFRESH_SECONDS)
