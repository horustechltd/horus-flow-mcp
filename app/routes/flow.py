# -*- coding: utf-8 -*-
import time
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import verify_api_key, require_tier
from app.models import FlowResponse, ENGINE_VERSION
from app.interpreters.flow_interpreter import interpret_flow
from app.feeds.binance_ws import ws_manager
from app.redis_client import redis_manager

router = APIRouter()


@router.get("/{symbol}", response_model=FlowResponse)
async def get_flow_signal(symbol: str, auth: dict = Depends(verify_api_key)):
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()

    # ⚡ Fast path: check Redis cache first (2s TTL)
    cached = await redis_manager.get_cached_response(clean_symbol)
    if cached:
        cached["timestamp"] = time.time()  # Fresh timestamp
        return FlowResponse(**cached)

    added = ws_manager.add_symbol(clean_symbol)

    imb = ws_manager.imbalance.get_imbalance(clean_symbol)
    flow = ws_manager.flow.get_delta(clean_symbol)

    if not imb or not flow:
        if added:
            raise HTTPException(
                status_code=202,
                detail="Symbol just added to tracking. Gathering flow data... Retry in 5 seconds."
            )
        raise HTTPException(
            status_code=503,
            detail="Insufficient flow data for this symbol right now. Try again shortly."
        )

    global_state = ws_manager.stress_index.state.value

    # 🦅 Fetch Global Macros from WiseMan via Redis
    wiseman_climate = None
    if redis_manager.redis:
        try:
            cached_wm = await redis_manager.redis.get("hta:state:wiseman_climate")
            if cached_wm:
                wiseman_climate = json.loads(cached_wm)
        except Exception:
            pass

    if not wiseman_climate:
        wiseman_climate = {"market_mode": "UNKNOWN", "health": "UNKNOWN", "confidence": 0, "target": "GLOBAL_BTC_MACRO"}
    else:
        wiseman_climate["target"] = "GLOBAL_BTC_MACRO"
    
    # 🐋 Fetch HTA Whale Intent from Redis FIRST (for logic integration)
    fi_dict = None
    if redis_manager.redis:
        try:
            # Redis key uses BTC/USDT format, convert BTCUSDT → BTC/USDT
            redis_symbol = clean_symbol
            for quote in ["USDT", "BUSD", "USDC"]:
                if redis_symbol.endswith(quote):
                    redis_symbol = redis_symbol[:-len(quote)] + "/" + quote
                    break
            
            fi_raw = await redis_manager.redis.get(f"flow_intent:{redis_symbol}")
            if fi_raw:
                fi = json.loads(fi_raw)
                fi_age = time.time() - fi.get("timestamp", 0)
                if fi_age < 30:  # Only use if fresh (< 30 seconds)
                    fi_dict = {
                        "direction": fi.get("direction", "NEUTRAL"),
                        "buy_ratio": round(fi.get("buy_ratio", 0.5), 4),
                        "delta_30s": round(fi.get("delta_30s", 0), 2),
                        "persistence": fi.get("persistence", 0),
                        "exec_intensity": round(fi.get("exec_intensity", 0), 2),
                        "age_seconds": round(fi_age, 1)
                    }
        except Exception:
            pass

    interpretation = interpret_flow(clean_symbol, imb, flow, global_state, wiseman_climate, whale_intent=fi_dict)

    if interpretation["confidence"] >= 0.50:
        desc = interpretation.get("description", "")
        forecast_str = interpretation["signal"] # Fallback
        
        if "⏱️ 30-SEC PROJECTION:" in desc:
            proj_part = desc.split("⏱️ 30-SEC PROJECTION:")[1].split("\n")[0].strip()
            forecast_str = proj_part
            
        # ANTI-OSCILLATION FILTER
        words = forecast_str.split(" ")
        base_new = " ".join(words[:2]) if len(words) >= 2 else forecast_str
        
        state_key = f"horus:oscillation:{clean_symbol}"
        raw_state = await redis_manager.redis.get(state_key)
        if raw_state:
            state = json.loads(raw_state)
        else:
            state = {"base": base_new, "count": 0, "last_full": forecast_str}
            
        if base_new != state["base"]:
            state["count"] += 1
            if state["count"] < 3:
                # Block change, revert to previous forecast
                forecast_str = state["last_full"]
                
                # Update the description text to reflect the blocked forecast
                lines = desc.split("\n")
                for i, line in enumerate(lines):
                    if "⏱️ 30-SEC PROJECTION:" in line:
                        parts = line.split("⏱️ 30-SEC PROJECTION:")
                        lines[i] = parts[0] + "⏱️ 30-SEC PROJECTION: " + forecast_str
                interpretation["description"] = "\n".join(lines)
            else:
                # Accept the new forecast
                state["base"] = base_new
                state["count"] = 0
                state["last_full"] = forecast_str
        else:
            state["count"] = 0
            state["last_full"] = forecast_str
            
        await redis_manager.redis.setex(state_key, 300, json.dumps(state)) # Persist state

    now_ts = time.time()
    now_utc = datetime.now(timezone.utc).isoformat()

    response_data = {
        # === Strict Schema (machine-parseable) ===
        "symbol": symbol,
        "signal": interpretation["signal"],
        "action": interpretation.get("action", "WAIT"),
        "direction_bias": interpretation.get("direction_bias", "NEUTRAL"),
        "confidence": interpretation["confidence"],
        "risk": interpretation["risk"],
        "market_regime": interpretation.get("market_regime", "RANGING"),
        
        # === Metadata ===
        "engine_version": ENGINE_VERSION,
        "freshness_ms": 0,  # Real-time, no cache lag
        "timestamp_utc": now_utc,
        "explanation": interpretation.get("explanation", ""),
        
        # === Backward Compatible ===
        "market_state": interpretation["market_state"],
        "description": interpretation["description"],
        "metrics": interpretation["metrics"],
        "timestamp": now_ts,
    }

    # 🐋 Inject HTA Whale Intent into response (if exists)
    if fi_dict:
        response_data["whale_intent"] = fi_dict

    # ⚡ Cache response + push to history (non-blocking)
    await redis_manager.set_cached_response(clean_symbol, response_data)
    await redis_manager.push_history(clean_symbol, {
        "signal": response_data["signal"],
        "action": response_data["action"],
        "direction_bias": response_data["direction_bias"],
        "confidence": response_data["confidence"],
        "market_state": response_data["market_state"],
        "risk": response_data["risk"],
    })

    return FlowResponse(**response_data)


# ═══════════════════════════════════════════════════════════════
#  NEW: History Endpoint — last N minutes of flow events
# ═══════════════════════════════════════════════════════════════

@router.get("/{symbol}/history")
async def get_flow_history(
    symbol: str,
    minutes: int = Query(default=30, ge=1, le=60, description="Lookback period in minutes"),
    auth: dict = Depends(require_tier("PRO"))
):
    """
    🦅 Flow History — Returns the last N minutes of orderflow snapshots.
    
    Each snapshot includes the signal, confidence, market state, and risk
    at that point in time. Useful for AI agents to detect pressure trends.
    """
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()

    history = await redis_manager.get_history(clean_symbol, minutes)

    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"No history available for {clean_symbol}. The symbol must be actively tracked first."
        )

    return {
        "symbol": clean_symbol,
        "minutes": minutes,
        "snapshots": len(history),
        "history": history
    }
