# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — binance_ws.py
Connects to Binance WS, feeds orderbook and trades to engines.
"""
import json
import time
import asyncio
import logging
import websockets
import aiohttp
from typing import Set, Dict

from app.config import BINANCE_WS_BASE, TRACKED_SYMBOLS_CRYPTO, MAX_TRACKED_CRYPTO_SYMBOLS
from app.engines.imbalance import ImbalanceCalculator
from app.engines.flow_detector import FlowDetector
from app.engines.market_stress import MarketStressIndex
from app.interpreters.wise_flow_interpreter import get_wise_interpreter

logger = logging.getLogger("BinanceWS")

# wise_flow_interpreter keeps 60 snapshots meaning ~60 s. Feeding it on every trade made that
# window a fraction of a second on busy pairs and cost a full CPU core (get_delta over 5,000 trades
# per trade, profiled 2026-10-27).
WISE_FEED_INTERVAL_S = 1.0

class BinanceWSManager:
    """Manages WS connections and feeds data to engines"""
    
    def __init__(self):
        self.imbalance = ImbalanceCalculator()
        self.flow = FlowDetector()
        self.stress_index = MarketStressIndex(self.imbalance, self.flow)
        
        self.symbols: Set[str] = set(TRACKED_SYMBOLS_CRYPTO)
        self.ws = None
        self._running = False
        self._last_msg_time = time.time()
        
        # Track active subscriptions to avoid spamming
        self._active_subs = set()
        self._wise_fed: Dict[str, float] = {}  # symbol -> last time the wise interpreter was fed

        # Spot symbols currently TRADING on Binance (filled by refresh_market_info_loop).
        # Empty set = not loaded yet; new symbols are refused until it loads.
        self.valid_symbols: Set[str] = set()
        self.quote_volume_24h: Dict[str, float] = {}
        self.market_info_updated_at: float = 0.0
        self.reconnects = 0

    async def refresh_market_info_loop(self):
        """Load the list of tradable spot symbols (every 6h) and 24h quote volumes (every 10 min)."""
        last_exchange_info = 0.0
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    now = time.time()
                    if now - last_exchange_info > 6 * 3600 or not self.valid_symbols:
                        async with session.get("https://api.binance.com/api/v3/exchangeInfo?permissions=SPOT",
                                               timeout=aiohttp.ClientTimeout(total=20)) as r:
                            if r.status == 200:
                                info = await r.json()
                                syms = {x["symbol"] for x in info.get("symbols", []) if x.get("status") == "TRADING"}
                                if syms:
                                    self.valid_symbols = syms
                                    last_exchange_info = now
                    async with session.get("https://api.binance.com/api/v3/ticker/24hr",
                                           timeout=aiohttp.ClientTimeout(total=20)) as r:
                        if r.status == 200:
                            rows = await r.json()
                            vols = {x["symbol"]: float(x.get("quoteVolume") or 0) for x in rows}
                            if vols:
                                self.quote_volume_24h = vols
                                self.flow.set_quote_volumes(vols)
                                self.market_info_updated_at = time.time()
                except Exception as e:
                    logger.error(f"Market info refresh error: {e}")
                await asyncio.sleep(600 if self.valid_symbols else 30)

    async def _handle_message(self, message: str):
        self._last_msg_time = time.time()
        
        try:
            data = json.loads(message)
            
            # Sub response
            if "result" in data and "id" in data:
                return
                
            stream = data.get("stream", "")
            payload = data.get("data", {})
            
            if not stream or not payload:
                return
                
            symbol = payload.get("s", "")
            if not symbol and "@" in stream:
                symbol = stream.split("@")[0].upper()
            
            if "@depth20@100ms" in stream:
                bids = payload.get("bids", payload.get("b", []))
                asks = payload.get("asks", payload.get("a", []))
                self.imbalance.feed(symbol, bids, asks)
                
                # Check stress if BTC
                if symbol == MarketStressIndex.BTC_SYMBOL:
                    self.stress_index.evaluate()
                    
            elif "@aggTrade" in stream:
                price = float(payload.get("p", 0))
                qty = float(payload.get("q", 0))
                is_buyer_maker = payload.get("m", False)
                ts = payload.get("T", 0) / 1000.0  # ms to s
                
                self.flow.feed(symbol, price, qty, is_buyer_maker, ts)

                # Feed the Wise Interpreter, once a second per symbol
                now = time.time()
                if now - self._wise_fed.get(symbol, 0.0) < WISE_FEED_INTERVAL_S:
                    return
                self._wise_fed[symbol] = now
                try:
                    imb_data = self.imbalance.get_imbalance(symbol)
                    flow_data = self.flow.get_delta(symbol)
                    market_state_val = self.stress_index.state.value if symbol == MarketStressIndex.BTC_SYMBOL else "NORMAL"
                    get_wise_interpreter().feed(symbol, imb_data, flow_data, market_state_val)
                except Exception as e:
                    logger.error(f"WiseInterpreter Feed error: {e}")
                
        except Exception as e:
            logger.error(f"WS Parse error: {e}")

    async def _subscribe(self, symbols: Set[str]):
        if not self.ws or not self._running:
            return
            
        streams = []
        for sym in symbols:
            s_lower = sym.lower()
            streams.extend([
                f"{s_lower}@depth20@100ms",
                f"{s_lower}@aggTrade"
            ])
            
        req = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": int(time.time())
        }
        await self.ws.send(json.dumps(req))
        self._active_subs.update(symbols)
        logger.info(f"Subscribed to new symbols: {symbols}")

    async def start(self):
        self._running = True
        
        while self._running:
            try:
                # Combine multiple streams into one connection
                streams = []
                for sym in self.symbols:
                    s_lower = sym.lower()
                    streams.extend([
                        f"{s_lower}@depth20@100ms",
                        f"{s_lower}@aggTrade"
                    ])
                    
                stream_str = "/".join(streams)
                url = f"wss://stream.binance.com:9443/stream?streams={stream_str}"
                
                logger.info(f"Connecting to Binance WS...")
                
                async with websockets.connect(url, max_size=10**7) as ws:
                    self.ws = ws
                    self._active_subs = set(self.symbols)
                    
                    while self._running:
                        try:
                            # Use timeout to detect dead connections
                            msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                            await self._handle_message(msg)
                            
                        except asyncio.TimeoutError:
                            # Send ping
                            await ws.ping()
                            
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WS Connection closed. Reconnecting in 3s...")
                self.reconnects += 1
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WS Error: {e}")
                await asyncio.sleep(3)

    def stop(self):
        self._running = False
        
    def add_symbol(self, symbol: str) -> str:
        """
        Start tracking a symbol. Returns one of:
          "exists"   already tracked
          "added"    added and subscribed live (data arrives within seconds)
          "invalid"  not a TRADING spot symbol on Binance
          "capacity" tracking limit reached
          "unavailable" the Binance symbol list has not loaded yet
        """
        clean_symbol = symbol.replace("/", "").replace("-", "").upper()
        if clean_symbol in self.symbols:
            return "exists"
        if not self.valid_symbols:
            return "unavailable"
        if clean_symbol not in self.valid_symbols:
            return "invalid"
        if len(self.symbols) >= MAX_TRACKED_CRYPTO_SYMBOLS:
            return "capacity"
        self.symbols.add(clean_symbol)
        if self.ws is not None and self._running:
            try:
                asyncio.get_running_loop().create_task(self._subscribe({clean_symbol}))
            except RuntimeError:
                pass  # no running loop: the next reconnect subscribes it
        return "added"

# Singleton instance
ws_manager = BinanceWSManager()
