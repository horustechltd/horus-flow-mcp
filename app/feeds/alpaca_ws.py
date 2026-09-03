# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — alpaca_ws.py
Connects to Alpaca IEX WS, feeds equity top-of-book quotes and trades.
"""
import json
import time
import asyncio
import logging
import websockets
from typing import Set

from app.config import ALPACA_KEY, ALPACA_SECRET, ALPACA_WS_BASE, TRACKED_SYMBOLS_EQUITY
from app.engines.imbalance import ImbalanceCalculator
from app.engines.flow_detector import FlowDetector

logger = logging.getLogger("AlpacaWS")

class AlpacaWSManager:
    def __init__(self):
        self.imbalance = ImbalanceCalculator()
        self.flow = FlowDetector()
        
        self.symbols: Set[str] = set(TRACKED_SYMBOLS_EQUITY)
        self.symbols.add("SPY")  # 🦅 Macro Gate: Always track the S&P 500
        
        self.block_trades = {}  # symbol -> list of recent {ts, price, size, is_sell}
        
        self.ws = None
        self._running = False
        self._authenticated = False

    async def _handle_message(self, message: str):
        try:
            data = json.loads(message)
            if not isinstance(data, list):
                return
                
            for payload in data:
                msg_type = payload.get("T")
                
                if msg_type == "success":
                    if payload.get("msg") == "connected":
                        logger.info("Alpaca WS Connected. Sending Auth...")
                        await self._authenticate(self.ws)
                    elif payload.get("msg") == "authenticated":
                        self._authenticated = True
                        logger.info("Alpaca WS Authenticated. Sending Subscribe...")
                        await self._subscribe(self.ws)
                    return
                elif msg_type == "error":
                    logger.error(f"Alpaca WS Error: {payload.get('msg')}")
                    return
                elif msg_type == "subscription":
                    logger.info(f"Alpaca WS Subscription Active: {payload}")
                    return
                
                symbol = payload.get("S", "")
                ts = time.time() # Alpaca uses "t" for RFC3339 timestamp, we just map time.time for simplicity
                
                if msg_type == "q":
                    # Quote (Top of Book)
                    bp, bs = float(payload.get("bp", 0)), float(payload.get("bs", 0))
                    ap, as_ = float(payload.get("ap", 0)), float(payload.get("as", 0))
                    
                    self.imbalance.feed_quote(symbol, bp, bs, ap, as_, ts)
                    
                elif msg_type == "t":
                    # Trade
                    # In equity, it's hard to know maker/taker perfectly without level 3. 
                    # We approximate by ticking the price vs the midpoint or simply comparing conditions. 
                    # For MVP: If we got a trade, we just consider it aggressive. We'll use 50/50 fallback if unpredictable, 
                    # but typically if price >= ask, aggressive buy. If price <= bid, aggressive sell.
                    # As we don't have the quote alongside the trade in 't', we'll use a naive boolean:
                    # In IEX, most explicit takers are moving the price.
                    price = float(payload.get("p", 0))
                    size = float(payload.get("s", 0))
                    
                    # Naive logic: alternate for MVP, or use price delta.
                    # Since we store top of book in self.imbalance snapshots, we can check it:
                    snaps = self.imbalance._snapshots.get(symbol, [])
                    is_sell = False
                    if len(snaps) > 0:
                        last_quote = snaps[-1]
                        midpoint = (last_quote["best_bid"] + last_quote["best_ask"]) / 2
                        if price < midpoint:
                            is_sell = True
                            
                    self.flow.feed(symbol, price, size, is_sell, ts)
                    
                    # 🐋 Institutional Block Trade Tracking
                    notional = price * size
                    if notional >= 200_000:
                        if symbol not in self.block_trades:
                            self.block_trades[symbol] = []
                        self.block_trades[symbol].append({"ts": ts, "price": price, "size": size, "is_sell": is_sell})
                        # Keep only recent memory
                        self.block_trades[symbol] = self.block_trades[symbol][-20:]
                    
                    
        except Exception as e:
            logger.error(f"Alpaca Parse Error: {e}")

    async def _authenticate(self, ws):
        if not ALPACA_KEY or not ALPACA_SECRET:
            logger.error("Missing Alpaca Credentials. Check APCA_API_KEY_ID.")
            return False
            
        auth_msg = {
            "action": "auth",
            "key": ALPACA_KEY,
            "secret": ALPACA_SECRET
        }
        await ws.send(json.dumps(auth_msg))
        return True

    async def _subscribe(self, ws):
        sub_msg = {
            "action": "subscribe",
            "trades": list(self.symbols),
            "quotes": list(self.symbols)
        }
        await ws.send(json.dumps(sub_msg))

    async def start(self):
        self._running = True
        
        while self._running:
            if not ALPACA_KEY:
                logger.warning("Alpaca keys omitted. Retrying in 10s...")
                await asyncio.sleep(10)
                continue
                
            try:
                logger.info(f"Connecting to Alpaca IEX WS...")
                async with websockets.connect(ALPACA_WS_BASE) as ws:
                    self.ws = ws
                    # Remove immediate auth, let _handle_message handle it when 'connected' is received
                    
                    while self._running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=20.0)
                            await self._handle_message(msg)
                        except asyncio.TimeoutError:
                            pass
                            
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Alpaca WS closed. Reconnecting...")
                self._authenticated = False
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Alpaca WS Error: {e}")
                self._authenticated = False
                await asyncio.sleep(3)

    def stop(self):
        self._running = False
        
    def add_symbol(self, symbol: str) -> bool:
        clean_symbol = symbol.upper()
        if clean_symbol not in self.symbols:
            self.symbols.add(clean_symbol)
            if self._authenticated and self.ws:
                asyncio.create_task(self._subscribe(self.ws))
            return True
        return False

# Singleton
alpaca_ws_manager = AlpacaWSManager()
