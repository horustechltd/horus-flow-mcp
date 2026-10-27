# -*- coding: utf-8 -*-
"""
Horus Flow — order-book recorder (its own PM2 process: horus-book-recorder).

The spot order book is the only stored data that measured informative (top5_imbalance and bid_ask_ratio
rank with the next minute's return, app/book_value_test.py), and Binance publishes no spot book history.
This process records it for a fixed list of 30 deep Binance USDT pairs every 15 seconds, outside the API
process so the API stays fast. Same engines, update speed (depth20@100ms) and field names as the API's
flow history, so the monthly test reads both the same way.

Files: calibration_data/book_history/YYYY-MM-DD/HH.jsonl, appended every 15 s; gzipped to HH.jsonl.gz
(verified) when the hour closes. The API's history archiver copies the .gz files to Backblaze B2.
Run: cd /root/horus_flow_api && python3 -m app.book_recorder
"""
import asyncio
import gzip
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import aiohttp
import websockets

from app.engines.flow_detector import FlowDetector
from app.engines.imbalance import ImbalanceCalculator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("BookRecorder")

# Fixed on purpose: a dataset is worth more when the same markets are recorded every day. Volume rankings
# move daily and are crowded with stablecoins and tokenized stocks. All 30 verified TRADING on 2026-10-27.
SYMBOLS = [f"{b}USDT" for b in ("BTC ETH SOL XRP BNB DOGE ADA TRX LINK AVAX SUI LTC NEAR UNI AAVE PEPE ENA "
                                 "WLD TAO FET ZEC DOT BCH APT ARB OP SHIB XLM HBAR ICP").split()]
BOOK_DIR = Path(os.getenv("HORUS_BOOK_DIR", "calibration_data/book_history"))
SNAPSHOT_EVERY_S = 15
MAX_BOOK_AGE_S = 5          # a symbol whose book has not updated for 5 s is not written (blind, never filled)
WS_URL = "wss://stream.binance.com:9443/stream?streams="
TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr?type=MINI"
HEARTBEAT_KEY = "horus:api:book_recorder:heartbeat"


def hour_file(base: Path, ts: float) -> Path:
    t = datetime.fromtimestamp(ts, timezone.utc)
    return base / t.strftime("%Y-%m-%d") / f"{t:%H}.jsonl"


def build_rows(imbalance: ImbalanceCalculator, flow: FlowDetector, symbols: List[str],
               book_seen: Dict[str, float], now: float) -> List[dict]:
    """One row per symbol whose book and trades are live, named like the API's flow history metrics."""
    rows = []
    for sym in symbols:
        if now - book_seen.get(sym, 0.0) > MAX_BOOK_AGE_S:
            continue
        imb, fl = imbalance.get_imbalance(sym), flow.get_delta(sym)
        if not imb or not fl:
            continue
        rows.append({
            "symbol": sym, "_ts": round(now, 3), "price": flow.last_price(sym),
            "best_bid": imb["best_bid"], "best_ask": imb["best_ask"],
            "bid_ask_ratio": round(imb["ratio"], 3), "top5_imbalance": imb["top5_imbalance"],
            "spread_pct": round(imb["spread_pct"], 4),
            "bid_depth_change_pct": round(imb["bid_depth_change_pct"], 2),
            "ask_depth_change_pct": round(imb["ask_depth_change_pct"], 2),
            "buy_sell_ratio": round(fl["buy_ratio"], 3), "delta_5s": round(fl["delta_5s"], 3),
            "delta_30s": round(fl["delta_30s"], 3), "delta_5m": round(fl["delta_5m"], 3),
            "delta_accel": fl["delta_accel"], "trade_count_30s": fl["trade_count_30s"],
            "large_sell_count": fl["large_sell_count"], "large_trade_threshold_usd": fl["large_trade_threshold_usd"],
            "book_age_s": round(now - book_seen[sym], 2),
        })
    return rows


def append_rows(base: Path, rows: List[dict], now: float) -> None:
    path = hour_file(base, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


def close_hours(base: Path, now: float) -> int:
    """gzip every hour file older than the current hour (verified byte for byte, then the plain file goes)."""
    current = hour_file(base, now)
    done = 0
    for path in sorted(base.glob("*/*.jsonl")):
        if path == current:
            continue
        gz, tmp = path.with_name(path.name + ".gz"), path.with_name(path.name + ".gz.tmp")
        data = path.read_bytes()
        with gzip.open(tmp, "wb", compresslevel=6) as dst:
            dst.write(data)
        with gzip.open(tmp, "rb") as check:
            if check.read() != data:
                tmp.unlink()
                logger.error(f"{path}: compressed copy does not match, plain file kept")
                continue
        os.replace(tmp, gz)
        path.unlink()
        done += 1
    return done


class BookRecorder:
    def __init__(self, symbols: List[str] = SYMBOLS, base: Path = BOOK_DIR):
        self.symbols, self.base = symbols, base
        self.imbalance, self.flow = ImbalanceCalculator(), FlowDetector()
        self.book_seen: Dict[str, float] = {}
        self.redis = None

    def handle(self, message: str) -> None:
        data = json.loads(message)
        stream, payload = data.get("stream", ""), data.get("data") or {}
        sym = stream.split("@", 1)[0].upper()
        if "@depth20" in stream:
            self.imbalance.feed(sym, payload.get("bids") or [], payload.get("asks") or [])
            self.book_seen[sym] = time.time()
        elif stream.endswith("@aggTrade"):
            self.flow.feed(sym, float(payload["p"]), float(payload["q"]), payload.get("m", False), payload["T"] / 1000.0)

    async def stream(self):
        url = WS_URL + "/".join(f"{s.lower()}@depth20@100ms/{s.lower()}@aggTrade" for s in self.symbols)
        backoff = 1
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2 ** 22) as ws:
                    logger.info(f"connected: {len(self.symbols)} symbols")
                    backoff = 1
                    async for message in ws:
                        self.handle(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"stream dropped: {e!r}; reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def volumes(self):
        """24h quote volumes size each market's large-trade threshold, as in the API."""
        while True:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(TICKER_URL, timeout=aiohttp.ClientTimeout(total=20)) as r:
                        tickers = await r.json()
                self.flow.set_quote_volumes({t["symbol"]: float(t["quoteVolume"]) for t in tickers if t["symbol"] in self.symbols})
            except Exception as e:
                logger.warning(f"24h volumes failed: {e!r}")
            await asyncio.sleep(3600)

    async def snapshots(self):
        while True:
            await asyncio.sleep(SNAPSHOT_EVERY_S - time.time() % SNAPSHOT_EVERY_S)
            now = time.time()
            try:
                rows = build_rows(self.imbalance, self.flow, self.symbols, self.book_seen, now)
                if rows:
                    await asyncio.to_thread(append_rows, self.base, rows, now)
                closed = await asyncio.to_thread(close_hours, self.base, now)
                if closed:
                    logger.info(f"closed {closed} hour file(s)")
                if self.redis:
                    await self.redis.set(HEARTBEAT_KEY, json.dumps({"timestamp_epoch": now, "symbols": len(rows)}), ex=600)
            except Exception as e:
                logger.error(f"snapshot failed: {e!r}")

    async def run(self):
        try:
            import redis.asyncio as aioredis
            from app.config import REDIS_URL
            self.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning(f"no heartbeat to Redis: {e!r}")
        await asyncio.gather(self.stream(), self.volumes(), self.snapshots())


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent.parent)
    asyncio.run(BookRecorder().run())
