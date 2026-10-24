# -*- coding: utf-8 -*-
"""
Horus Flow API — History Archiver
Redis keeps only 24 hours of the 15-second flow snapshots. Binance publishes spot trades
and candles for free but no spot order-book history, so these snapshots (book imbalance,
depth changes, taker flow) cannot be rebuilt later. Every finished hour is written to
calibration_data/flow_history/YYYY-MM-DD/HH.jsonl.gz, one JSON line per snapshot with its
symbol (about 3 MB a day for 11 symbols). Files are written whole and renamed into place,
so a restart rewrites an hour instead of duplicating it.
"""
import asyncio
import gzip
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from app.redis_client import redis_manager, HISTORY_TTL

logger = logging.getLogger("API.HistoryArchiver")

ARCHIVE_DIR = Path(os.getenv("HORUS_ARCHIVE_DIR", "calibration_data/flow_history"))
CHECK_INTERVAL = 300
KEY_LAST_HOUR = "horus:api:archive:last_hour"  # epoch of the start of the last archived hour


def hour_path(hour_start: int) -> Path:
    t = datetime.fromtimestamp(hour_start, timezone.utc)
    return ARCHIVE_DIR / t.strftime("%Y-%m-%d") / f"{t:%H}.jsonl.gz"


def _write(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for d in rows:
            f.write(json.dumps(d, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


async def archive_hour(redis, hour_start: int) -> int:
    """Write every symbol's snapshots of one UTC hour to its file. Returns the row count."""
    rows = []
    async for key in redis.scan_iter("flow:history:*"):
        symbol = key.split(":", 2)[2]
        for raw in await redis.zrangebyscore(key, hour_start, hour_start + 3599.999):
            d = json.loads(raw)
            d["symbol"] = symbol
            rows.append(d)
    if rows:
        rows.sort(key=lambda d: (d["_ts"], d["symbol"]))
        await asyncio.to_thread(_write, hour_path(hour_start), rows)
    return len(rows)


def archive_stats() -> dict:
    files = list(ARCHIVE_DIR.glob("*/*.jsonl.gz"))
    days = {f.parent.name for f in files}
    return {"days": len(days), "hours": len(files), "mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
            "first_day": min(days) if days else None}


async def archiver_loop():
    await asyncio.sleep(60)
    while True:
        try:
            r = redis_manager.redis
            if r:
                current = int(time.time()) // 3600 * 3600
                oldest = current - (HISTORY_TTL // 3600 - 1) * 3600  # oldest hour Redis still holds whole
                last = int(await r.get(KEY_LAST_HOUR) or 0)
                for hour in range(max(last + 3600, oldest) if last else oldest, current, 3600):
                    n = await archive_hour(r, hour)
                    await r.set(KEY_LAST_HOUR, hour)
                    logger.info(f"archived {n} snapshots to {hour_path(hour)}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"history archive failed: {e!r}")
        await asyncio.sleep(CHECK_INTERVAL)
