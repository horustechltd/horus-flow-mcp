# -*- coding: utf-8 -*-
"""
Horus Flow API — History Archiver
Redis keeps only 24 hours of the 15-second flow snapshots. Binance publishes spot trades
and candles for free but no spot order-book history, so these snapshots (book imbalance,
depth changes, taker flow) cannot be rebuilt later. Every finished hour is written to
calibration_data/flow_history/YYYY-MM-DD/HH.jsonl.gz, one JSON line per snapshot with its
symbol (about 3 MB a day for 11 symbols). Files are written whole and renamed into place,
so a restart rewrites an hour instead of duplicating it.

Each file is then copied to Backblaze B2 (flow_history/YYYY-MM-DD/HH.jsonl.gz) and marked
with an empty HH.jsonl.gz.up next to it. The server keeps LOCAL_KEEP_DAYS of copied files;
files that were never copied are never deleted.

The same loop looks after qve_engine's market-intelligence snapshots (one uncompressed file
per local day since May 2026): closed days are gzipped (verified byte for byte, then the
original goes; about 27x smaller) and copied to B2 under raw_snapshots/. They stay on the
server too, because optimize_weights.py reads them.
"""
import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import aiohttp

from app.config import B2_KEY_ID, B2_APP_KEY, B2_BUCKET, TEST_INSTANCE
from app.redis_client import redis_manager, HISTORY_TTL

logger = logging.getLogger("API.HistoryArchiver")

ARCHIVE_DIR = Path(os.getenv("HORUS_ARCHIVE_DIR", "calibration_data/flow_history"))
CHECK_INTERVAL = 300
KEY_LAST_HOUR = "horus:api:archive:last_hour"  # epoch of the start of the last archived hour
KEY_REMOTE = "horus:api:archive:remote"  # hash: hours, bytes, first_day copied to B2
LOCAL_KEEP_DAYS = 40  # a full month stays local for the monthly order-book test (~3 MB a day)
SNAPSHOT_DIR = Path(os.getenv("HORUS_SNAPSHOT_DIR", "calibration_data/raw_snapshots"))
BOOK_DIR = Path(os.getenv("HORUS_BOOK_DIR", "calibration_data/book_history"))  # written by app/book_recorder.py
KEY_REMOTE_BOOK = "horus:api:archive:remote_book"
B2_API = "https://api.backblazeb2.com/b2api/v2"


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


def _marker(path: Path) -> Path:
    return path.with_name(path.name + ".up")


class B2Client:
    """Minimal Backblaze B2 client (native API): authorize, then upload whole files."""

    def __init__(self, key_id: str, app_key: str, bucket: str):
        self.key_id, self.app_key, self.bucket = key_id, app_key, bucket
        self.auth = None

    async def _authorize(self, s: aiohttp.ClientSession):
        cred = base64.b64encode(f"{self.key_id}:{self.app_key}".encode()).decode()
        async with s.get(f"{B2_API}/b2_authorize_account", headers={"Authorization": f"Basic {cred}"}) as r:
            r.raise_for_status()
            d = await r.json()
        allowed = d.get("allowed") or {}
        if allowed.get("bucketName") != self.bucket:
            raise RuntimeError(f"B2 key is not limited to bucket {self.bucket}")
        self.auth = {"token": d["authorizationToken"], "api_url": d["apiUrl"], "bucket_id": allowed["bucketId"]}

    async def upload(self, s: aiohttp.ClientSession, name: str, data: bytes):
        for _ in range(2):  # authorization tokens expire after 24h: re-authorize once
            if not self.auth:
                await self._authorize(s)
            async with s.post(f"{self.auth['api_url']}/b2api/v2/b2_get_upload_url",
                              headers={"Authorization": self.auth["token"]}, json={"bucketId": self.auth["bucket_id"]}) as r:
                if r.status == 401:
                    self.auth = None
                    continue
                r.raise_for_status()
                up = await r.json()
            headers = {"Authorization": up["authorizationToken"], "X-Bz-File-Name": quote(name),
                       "Content-Type": "application/gzip", "X-Bz-Content-Sha1": hashlib.sha1(data).hexdigest()}
            async with s.post(up["uploadUrl"], data=data, headers=headers) as r:
                if r.status == 401:
                    self.auth = None
                    continue
                r.raise_for_status()
                return
        raise RuntimeError("B2 authorization failed twice")


async def _copy(client, session, path: Path, name: str) -> int:
    data = await asyncio.to_thread(path.read_bytes)
    await client.upload(session, name, data)
    _marker(path).touch()
    return len(data)


async def upload_pending(client, redis, session: aiohttp.ClientSession, base: Path = None,
                         prefix: str = "flow_history", stats_key: str = KEY_REMOTE) -> int:
    """Copy every archived hour without a .up marker, oldest first. Returns how many were copied."""
    done = 0
    for path in sorted(p for p in (base or ARCHIVE_DIR).glob("*/*.jsonl.gz") if not _marker(p).exists()):
        size = await _copy(client, session, path, f"{prefix}/{path.parent.name}/{path.name}")
        await redis.hincrby(stats_key, "hours", 1)
        await redis.hincrby(stats_key, "bytes", size)
        if not await redis.hget(stats_key, "first_day"):
            await redis.hset(stats_key, "first_day", path.parent.name)
        done += 1
    return done


def compress_closed_snapshots(now: float = None) -> int:
    """gzip every snapshot day before today (qve_engine names files by the server's local date)."""
    today = datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")
    done = 0
    for path in sorted(SNAPSHOT_DIR.glob("snapshots_*.jsonl")):
        if path.stem.removeprefix("snapshots_") >= today:
            continue
        gz = path.with_name(path.name + ".gz")
        tmp = path.with_name(path.name + ".gz.tmp")
        with open(path, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        size = 0
        with gzip.open(tmp, "rb") as f:
            while chunk := f.read(1 << 20):
                size += len(chunk)
        if size != path.stat().st_size:
            tmp.unlink()
            raise RuntimeError(f"{path.name}: compressed copy does not match, original kept")
        os.replace(tmp, gz)
        path.unlink()
        done += 1
    return done


async def upload_snapshots(client, session: aiohttp.ClientSession) -> int:
    done = 0
    for path in sorted(p for p in SNAPSHOT_DIR.glob("snapshots_*.jsonl.gz") if not _marker(p).exists()):
        await _copy(client, session, path, f"raw_snapshots/{path.name}")
        done += 1
    return done


def prune_local(now: float = None, base: Path = None) -> int:
    """Delete copied files older than LOCAL_KEEP_DAYS. Files never copied stay."""
    base = base or ARCHIVE_DIR
    cutoff = (datetime.fromtimestamp(now or time.time(), timezone.utc).date() - timedelta(days=LOCAL_KEEP_DAYS)).isoformat()
    removed = 0
    for path in base.glob("*/*.jsonl.gz"):
        if path.parent.name < cutoff and _marker(path).exists():
            path.unlink()
            _marker(path).unlink()
            removed += 1
    for d in base.glob("*"):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed


async def archive_summary(redis) -> dict:
    remote = await redis.hgetall(KEY_REMOTE) if redis else {}
    return {"local": archive_stats(),
            "remote": {"hours": int(remote.get("hours", 0)), "mb": round(int(remote.get("bytes", 0)) / 1e6, 1),
                       "first_day": remote.get("first_day")}}


def archive_stats() -> dict:
    files = list(ARCHIVE_DIR.glob("*/*.jsonl.gz"))
    days = {f.parent.name for f in files}
    return {"days": len(days), "hours": len(files), "mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
            "first_day": min(days) if days else None}


async def archiver_loop():
    b2 = B2Client(B2_KEY_ID, B2_APP_KEY, B2_BUCKET) if B2_KEY_ID and B2_APP_KEY and B2_BUCKET and not TEST_INSTANCE else None
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
                if not TEST_INSTANCE:
                    zipped = await asyncio.to_thread(compress_closed_snapshots)
                    if zipped:
                        logger.info(f"gzipped {zipped} closed snapshot days in {SNAPSHOT_DIR}")
                if b2:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as s:
                        copied = await upload_pending(b2, r, s)
                        books = await upload_pending(b2, r, s, BOOK_DIR, "book_history", KEY_REMOTE_BOOK)
                        snaps = await upload_snapshots(b2, s)
                    if copied or books or snaps:
                        logger.info(f"copied {copied} flow hours, {books} book hours and {snaps} snapshot days to B2 bucket {B2_BUCKET}")
                    await asyncio.to_thread(prune_local)
                    await asyncio.to_thread(prune_local, None, BOOK_DIR)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"history archive failed: {e!r}")
        await asyncio.sleep(CHECK_INTERVAL)
