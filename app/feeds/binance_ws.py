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
from typing import Set

from app.config import BINANCE_WS_BASE, TRACKED_SYMBOLS_CRYPTO
from app.engines.imbalance import ImbalanceCalculator
from app.engines.flow_detector import FlowDetector
from app.engines.market_stress import MarketStressIndex
from app.interpreters.wise_flow_interpreter import get_wise_interpreter

logger = logging.getLogger("BinanceWS")

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
                
                # Feed the Wise Interpreter
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
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WS Error: {e}")
                await asyncio.sleep(3)

    def stop(self):
        self._running = False
        
    def add_symbol(self, symbol: str) -> bool:
        """Dynamically add symbol if not tracked. Returns True if added."""
        # Convert BTC/USDT to BTCUSDT if needed
        clean_symbol = symbol.replace("/", "").replace("-", "").upper()
        if clean_symbol not in self.symbols:
            self.symbols.add(clean_symbol)
            # We must schedule the subscription logic on the async loop.
            # In FastAPI, we can assume this will be called from an async path, 
            # so we'll just handle it by letting the WS reconnect or explicitly sending SUB.
            # For MVP, we will only track BTCUSDT initially anyway.
            return True
        return False

# Singleton instance
ws_manager = BinanceWSManager()
