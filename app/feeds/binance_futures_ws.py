# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — binance_futures_ws.py

Connects to Binance Futures for:
  1. forceOrder stream (Liquidations) — WebSocket, real-time
  2. Open Interest — REST poll every 5 seconds
  3. Funding Rate — REST poll every 30 seconds

Feeds everything into DerivativesEngine (in-memory).
Runs as a parallel async task alongside the spot WS.
"""

import json
import time
import asyncio
import logging
import websockets
import aiohttp
from typing import Set

from app.engines.derivatives_engine import derivatives_engine

logger = logging.getLogger("BinanceFuturesWS")

BINANCE_FAPI = "https://fapi.binance.com"


class BinanceFuturesManager:
    """Manages Futures WS + REST polling for derivatives data."""

    def __init__(self):
        self._running = False
        self._symbols: Set[str] = {"BTCUSDT"}
        self._http_session = None

    async def start(self):
        """Start all futures data feeds in parallel."""
        self._running = True
        logger.info("🚀 BinanceFuturesManager starting...")

        await asyncio.gather(
            self._ws_liquidations(),
            self._poll_open_interest(),
            self._poll_funding_rate(),
        )

    def stop(self):
        self._running = False

    # ═══════════════════════════════════════════
    # 1. LIQUIDATION STREAM (WebSocket)
    # ═══════════════════════════════════════════

    async def _ws_liquidations(self):
        """Connect to Binance Futures forceOrder stream for real-time liquidations."""
        while self._running:
            try:
                streams = "/".join(f"{s.lower()}@forceOrder" for s in self._symbols)
                url = f"wss://fstream.binance.com/stream?streams={streams}"

                logger.info(f"Connecting to Futures Liquidation WS...")

                async with websockets.connect(url, max_size=10**7) as ws:
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                            data = json.loads(msg)

                            payload = data.get("data", {}).get("o", {})
                            if payload:
                                symbol = payload.get("s", "")
                                side = payload.get("S", "")  # BUY or SELL
                                price = float(payload.get("p", 0))
                                qty = float(payload.get("q", 0))

                                derivatives_engine.feed_liquidation(symbol, side, price, qty)

                                notional = price * qty
                                if notional > 50000:
                                    logger.info(f"🔥 LIQUIDATION: {symbol} {side} ${notional:,.0f}")

                        except asyncio.TimeoutError:
                            await ws.ping()

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Futures Liquidation WS closed. Reconnecting...")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Futures Liquidation WS error: {e}")
                await asyncio.sleep(5)

    # ═══════════════════════════════════════════
    # 2. OPEN INTEREST (REST Poll every 5s)
    # ═══════════════════════════════════════════

    async def _poll_open_interest(self):
        """Poll Binance Futures REST API for Open Interest every 5 seconds."""
        await asyncio.sleep(2)  # Let WS connect first

        while self._running:
            try:
                if not self._http_session:
                    self._http_session = aiohttp.ClientSession()

                for symbol in self._symbols:
                    url = f"{BINANCE_FAPI}/fapi/v1/openInterest?symbol={symbol}"
                    async with self._http_session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            oi_value = float(data.get("openInterest", 0))
                            derivatives_engine.feed_open_interest(symbol, oi_value)

            except Exception as e:
                logger.error(f"OI Poll error: {e}")

            await asyncio.sleep(5)

    # ═══════════════════════════════════════════
    # 3. FUNDING RATE (REST Poll every 30s)
    # ═══════════════════════════════════════════

    async def _poll_funding_rate(self):
        """Poll Binance Futures REST API for Funding Rate every 30 seconds."""
        await asyncio.sleep(3)

        while self._running:
            try:
                if not self._http_session:
                    self._http_session = aiohttp.ClientSession()

                for symbol in self._symbols:
                    url = f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol}"
                    async with self._http_session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            rate = float(data.get("lastFundingRate", 0))
                            derivatives_engine.feed_funding_rate(symbol, rate)

            except Exception as e:
                logger.error(f"Funding Rate Poll error: {e}")

            await asyncio.sleep(30)


# Singleton
futures_manager = BinanceFuturesManager()
