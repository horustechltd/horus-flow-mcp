# -*- coding: utf-8 -*-
import os
import time
import json
import logging
import redis.asyncio as aioredis
from app.config import REDIS_URL

logger = logging.getLogger("API.Redis")

# Cache TTL for flow responses (seconds)
FLOW_CACHE_TTL = 2
# Max history entries per symbol
HISTORY_MAX_ENTRIES = 120  # ~30 min at 1 snapshot per 15s
# History entry TTL (seconds)
HISTORY_TTL = 3600  # 1 hour


class RedisManager:
    def __init__(self):
        self.redis = None

    async def connect(self):
        try:
            self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
            logger.info(f"Connected to Redis at {REDIS_URL}")
        except Exception as e:
            logger.error(f"Redis Connection Error: {e}")

    async def disconnect(self):
        if self.redis:
            await self.redis.close()
            logger.info("Disconnected from Redis")

    # ── Response Cache (2s TTL — eliminates redundant computation) ──

    async def get_cached_response(self, symbol: str) -> dict | None:
        """Get cached flow response. Returns None on miss."""
        if not self.redis:
            return None
        try:
            cached = await self.redis.get(f"flow:cache:{symbol}")
            return json.loads(cached) if cached else None
        except Exception:
            return None

    async def set_cached_response(self, symbol: str, data: dict):
        """Cache flow response with short TTL."""
        if not self.redis:
            return
        try:
            await self.redis.set(
                f"flow:cache:{symbol}",
                json.dumps(data),
                ex=FLOW_CACHE_TTL
            )
        except Exception:
            pass

    # ── History Store (sorted set by timestamp) ──

    async def push_history(self, symbol: str, data: dict):
        """Store a flow snapshot in history (sorted set, scored by timestamp)."""
        if not self.redis:
            return
        try:
            key = f"flow:history:{symbol}"
            ts = time.time()
            data["_ts"] = ts
            await self.redis.zadd(key, {json.dumps(data): ts})
            # Trim old entries
            await self.redis.zremrangebyscore(key, 0, ts - HISTORY_TTL)
            # Cap max entries
            count = await self.redis.zcard(key)
            if count > HISTORY_MAX_ENTRIES:
                await self.redis.zremrangebyrank(key, 0, count - HISTORY_MAX_ENTRIES - 1)
        except Exception:
            pass

    async def get_history(self, symbol: str, minutes: int = 30) -> list:
        """Get flow history for last N minutes."""
        if not self.redis:
            return []
        try:
            key = f"flow:history:{symbol}"
            since = time.time() - (minutes * 60)
            entries = await self.redis.zrangebyscore(key, since, "+inf")
            return [json.loads(e) for e in entries]
        except Exception:
            return []


redis_manager = RedisManager()
