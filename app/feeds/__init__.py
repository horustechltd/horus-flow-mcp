# -*- coding: utf-8 -*-
import asyncio
from app.feeds.binance_ws import ws_manager
from app.feeds.alpaca_ws import alpaca_ws_manager

async def start_ws():
    # Only binance for now in this wrapper, but we can rename
    await ws_manager.start()

async def start_alpaca_ws():
    await alpaca_ws_manager.start()
