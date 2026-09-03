# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — equity.py routes
"""
import time
from fastapi import APIRouter, Depends, HTTPException

from app.auth import verify_api_key, require_tier
from app.models import FlowResponse
from app.interpreters.flow_interpreter import interpret_flow
from app.feeds.alpaca_ws import alpaca_ws_manager

router_equity = APIRouter()

@router_equity.get("/macro-blocks", tags=["Equity Flow"])
async def get_macro_blocks(auth: dict = Depends(require_tier("FREE"))):
    """
    Get the overall US Market SPY Macro trend and all recent Institutional Block Trades.
    """
    spy_flow = alpaca_ws_manager.flow.get_delta("SPY")
    
    market_mode = "UNKNOWN"
    spy_buy_ratio = 0.5
    if spy_flow:
        spy_buy_ratio = spy_flow.get("buy_ratio", 0.5)
        if spy_buy_ratio < 0.35:
            market_mode = "DUMP (CRITICAL)"
        elif spy_buy_ratio < 0.45:
            market_mode = "CHOP (FRAGILE)"
        elif spy_buy_ratio > 0.65:
            market_mode = "BULLISH (ROBUST)"
        else:
            market_mode = "RANGE_BOUND (NORMAL)"

    blocks = []
    current_time = time.time()
    for sym, trades in alpaca_ws_manager.block_trades.items():
        for t in trades:
            if (current_time - t["ts"]) <= 300:  # Last 5 mins
                blocks.append({
                    "symbol": sym,
                    "price": t["price"],
                    "size": t["size"],
                    "notional": t["price"] * t["size"],
                    "is_sell": t["is_sell"],
                    "seconds_ago": int(current_time - t["ts"])
                })
    
    blocks.sort(key=lambda x: x["seconds_ago"])
    
    return {
        "timestamp": current_time,
        "spy_macro_climate": {
            "market_mode": market_mode,
            "spy_buy_ratio": round(spy_buy_ratio, 2)
        },
        "recent_block_trades": blocks,
        "block_count": len(blocks)
    }

@router_equity.get("/{symbol}", response_model=FlowResponse)
async def get_equity_flow_signal(symbol: str, auth: dict = Depends(require_tier("ULTRA"))):
    """
    Get live orderflow signal for a specific US Equity symbol via IEX.
    """
    clean_symbol = symbol.upper()
    
    # Dynamically add to WS
    added = alpaca_ws_manager.add_symbol(clean_symbol)
    
    imb = alpaca_ws_manager.imbalance.get_imbalance(clean_symbol)
    flow = alpaca_ws_manager.flow.get_delta(clean_symbol)
    
    if not imb or not flow:
        if added:
            raise HTTPException(
                status_code=202, 
                detail="Equity symbol just added. Gathering IEX flow data... Retry in 5 seconds."
            )
        raise HTTPException(
            status_code=503, 
            detail="Insufficient flow data. Try again shortly. Note: US market hours may be closed."
        )

    # 🦅 SPY Macro Gate
    spy_flow = alpaca_ws_manager.flow.get_delta("SPY")
    global_state = "NORMAL"
    wiseman_climate = {"market_mode": "RANGE_BOUND", "health": "NORMAL", "confidence": 0.50}
    
    if spy_flow and symbol != "SPY":
        spy_buy_ratio = spy_flow.get("buy_ratio", 0.5)
        # Check delta velocity and ratio
        if spy_buy_ratio < 0.35:
            global_state = "LIQUIDITY_EVENT"
            wiseman_climate = {"market_mode": "DUMP", "health": "CRITICAL", "confidence": 0.99}
        elif spy_buy_ratio < 0.45:
            global_state = "PRESSURE"
            wiseman_climate = {"market_mode": "CHOP", "health": "FRAGILE", "confidence": 0.85}
        elif spy_buy_ratio > 0.65:
            global_state = "ACCUMULATION"
            wiseman_climate = {"market_mode": "BULLISH", "health": "ROBUST", "confidence": 0.80}

    # Handle US Market Closed hours
    if flow.get("trade_count_30s", 0) == 0:
        return FlowResponse(
            symbol=symbol,
            signal="MARKET_CLOSED",
            confidence=0.0,
            market_state="OFFLINE",
            risk="UNKNOWN",
            description="US Equity Market is closed or illiquid. No trades matched in the last 30 seconds.",
            metrics={"trade_count_30s": 0, "delta_5s": 0.0, "bid_ask_ratio": imb.get("ratio", 1.0)},
            timestamp=time.time()
        )

    interpretation = interpret_flow(clean_symbol, imb, flow, global_state, wiseman_climate)
    
    # 🐋 Institutional Block Trade Injection
    blocks = alpaca_ws_manager.block_trades.get(clean_symbol, [])
    recent_blocks = [b for b in blocks if (time.time() - b["ts"]) <= 60]  # inside last 60s
    if recent_blocks:
        interpretation["metrics"]["flags"].append(f"INSTITUTIONAL_BLOCK_TRADE(count={len(recent_blocks)})")
        interpretation["description"] += f" 🐋 Warning/Notice: {len(recent_blocks)} Institutional block trade(s) detected (>$200k each) in last 60s."
        # Bump confidence of the prevailing signal if blocks confirm it
        interpretation["confidence"] = min(0.99, interpretation["confidence"] + 0.10)
    
    response = FlowResponse(
        symbol=symbol,
        signal=interpretation["signal"],
        confidence=interpretation["confidence"],
        market_state=interpretation["market_state"],
        risk=interpretation["risk"],
        description=interpretation["description"],
        metrics=interpretation["metrics"],
        timestamp=time.time()
    )
    
    return response
