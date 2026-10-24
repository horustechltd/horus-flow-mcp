# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — equity.py routes
"""
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.auth import verify_api_key, require_tier, tier_or_preview, upgrade_block, upgrade_required, plan_name
from app.models import FlowResponse, ENGINE_VERSION
from app.interpreters.flow_interpreter import interpret_flow
from app.feeds.alpaca_ws import alpaca_ws_manager

router_equity = APIRouter()
PREVIEW_SYMBOLS = ("SPY", "QQQ")  # equity flow open to lower plans as a preview

# Alpaca's free feed is IEX only. IEX prints were 2.4%-3.6% of US consolidated
# volume for SPY and NVDA in October 2026, so every equity reading is a sample.
DATA_SOURCE = {
    "feed": "IEX via Alpaca",
    "coverage_note": "IEX is roughly 3% of US consolidated volume. Ratios and prints are a sample of the tape, not the full market.",
}

# Signals too strong to assert from a ~3% sample; downgraded to plain pressure
_EXTREME_BEARISH = {"EMERGENCY_DUMP", "LIQUIDATION_CASCADE", "DEPTH_COLLAPSE", "WHALE_DUMP", "IMMINENT_DUMP_5M",
                    "SELL_SPIKE", "INSTITUTIONAL_DISTRIBUTION", "WHALE_EXIT", "STRONG_SELL_PRESSURE"}
_EXTREME_BULLISH = {"SHORT_SQUEEZE", "IMMINENT_PUMP_5M", "STRONG_BUY_PRESSURE"}
EQUITY_MAX_CONFIDENCE = 0.6


def _spy_mode(buy_ratio: float) -> str:
    if buy_ratio < 0.35:
        return "SELL_SKEW_STRONG"
    if buy_ratio < 0.45:
        return "SELL_SKEW"
    if buy_ratio > 0.65:
        return "BUY_SKEW"
    return "BALANCED"

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
        market_mode = _spy_mode(spy_buy_ratio)

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
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "spy_macro_climate": {
            "market_mode": market_mode,
            "spy_buy_ratio": round(spy_buy_ratio, 2),
            "window": "aggressive IEX trades, last 30s",
        },
        "recent_block_trades": blocks,
        "block_count": len(blocks),
        "block_definition": "single IEX print with notional >= $200,000 in the last 5 minutes",
        "data_source": DATA_SOURCE,
    }

@router_equity.get("/{symbol}", response_model=FlowResponse)
async def get_equity_flow_signal(symbol: str, auth: dict = Depends(tier_or_preview("BUILDER"))):
    """
    Get live orderflow signal for a specific US Equity symbol via IEX.
    Below the plan, SPY and QQQ are served as a preview.
    """
    clean_symbol = symbol.upper()
    unlocks = "Order flow for any US stock or ETF on IEX"
    if auth["preview"] and clean_symbol not in PREVIEW_SYMBOLS:
        raise upgrade_required(auth, auth["min_level"],
                               f"Equity flow for {clean_symbol} needs the {plan_name(auth, auth['min_level'])} plan. "
                               f"{' and '.join(PREVIEW_SYMBOLS)} are open on your plan as a preview.", unlocks)
    response = await _equity_signal(symbol, clean_symbol)
    if not auth["preview"]:
        return response
    return JSONResponse(response.model_dump(mode="json")
                        | {"upgrade": upgrade_block(auth, auth["min_level"], unlocks, f"{' and '.join(PREVIEW_SYMBOLS)} only on your plan")})


async def _equity_signal(symbol: str, clean_symbol: str) -> FlowResponse:
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
    
    if spy_flow and clean_symbol != "SPY":
        # SPY skew from the IEX sample informs context only; it never escalates to a liquidity event.
        spy_buy_ratio = spy_flow.get("buy_ratio", 0.5)
        if spy_buy_ratio < 0.45:
            global_state = "PRESSURE"
            wiseman_climate = {"market_mode": "CHOP", "health": "FRAGILE", "confidence": 0.5}
        elif spy_buy_ratio > 0.65:
            global_state = "ACCUMULATION"
            wiseman_climate = {"market_mode": "BULLISH", "health": "NORMAL", "confidence": 0.5}

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
    
    # Large prints on IEX (>= $200k)
    blocks = alpaca_ws_manager.block_trades.get(clean_symbol, [])
    recent_blocks = [b for b in blocks if (time.time() - b["ts"]) <= 60]
    if recent_blocks:
        interpretation["metrics"]["flags"].append(f"LARGE_IEX_PRINTS(count={len(recent_blocks)})")
        interpretation["description"] += f" {len(recent_blocks)} IEX print(s) of $200k or more in the last 60s."

    # Downgrade signals that a ~3% sample cannot support
    signal = interpretation["signal"]
    action = interpretation.get("action", "WAIT")
    bias = interpretation.get("direction_bias", "NEUTRAL")
    risk = interpretation["risk"]
    if signal in _EXTREME_BEARISH:
        signal, action, bias = "SELL_PRESSURE", "BLOCK_LONG", "BEARISH"
    elif signal in _EXTREME_BULLISH:
        signal, action, bias = "BUY_PRESSURE", "BLOCK_SHORT", "BULLISH"
    if risk == "EXTREME":
        risk = "HIGH"
    interpretation["metrics"]["flags"].append("IEX_SAMPLE")
    interpretation["metrics"]["spy_buy_ratio_iex"] = round(spy_flow.get("buy_ratio", 0.5), 3) if spy_flow else None

    response = FlowResponse(
        symbol=clean_symbol,
        signal=signal,
        action=action,
        direction_bias=bias,
        confidence=min(EQUITY_MAX_CONFIDENCE, interpretation["confidence"]),
        risk=risk,
        market_regime=interpretation.get("market_regime", "RANGING"),
        engine_version=ENGINE_VERSION,
        freshness_ms=0,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        explanation=interpretation.get("explanation", "") + " [IEX sample, ~3% of US volume]",
        market_state=interpretation["market_state"],
        description=interpretation["description"],
        metrics=interpretation["metrics"],
        data_source=DATA_SOURCE,
        timestamp=time.time()
    )

    return response
