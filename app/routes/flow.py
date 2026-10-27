# -*- coding: utf-8 -*-
import time
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.auth import verify_api_key, tier_or_preview, tier_level, plan_name, upgrade_block, upgrade_required
from app.config import FREE_TIER_SYMBOLS
from app import book_measure, track_record


def _book_link(measured):
    """Average rank correlation of top5_imbalance with the next minute, when both halves agree; else None."""
    if not measured or not measured.get("consistent"):
        return None
    rc = measured["rank_correlation"]
    return round((rc["first_half"] + rc["second_half"]) / 2, 3)


def compact_flow(doc: dict) -> dict:
    """Token-light view for AI agents (~150 tokens). Deliberately has no "action" field:
    readings are context with a measured hit rate, not trade instructions."""
    m = doc.get("metrics") or {}
    rel = doc.get("reliability") or {}
    return {
        "symbol": doc.get("symbol"),
        "signal": doc.get("signal"),
        "direction_bias": doc.get("direction_bias"),
        "confidence": doc.get("confidence"),
        "risk": doc.get("risk"),
        "price": m.get("price"),
        "delta_30s_usd": m.get("delta_30s"),
        "buy_sell_ratio_30s": m.get("buy_sell_ratio"),
        "bid_ask_depth_ratio": m.get("bid_ask_ratio"),
        "large_sells_5m": m.get("large_sell_count"),
        "hit_rate_5m": (rel.get("hit_rate") or {}).get("5m"),
        "reliability": rel.get("interpretation") or rel.get("note"),
        "top5_imbalance": m.get("top5_imbalance"),
        "book_tilt": (doc.get("book_information") or {}).get("book_tilt"),
        "book_link_1m": _book_link((doc.get("book_information") or {}).get("measured")),
        "freshness_ms": doc.get("freshness_ms"),
        "timestamp_utc": doc.get("timestamp_utc"),
    }
from app.models import FlowResponse, ENGINE_VERSION
from app.interpreters.flow_interpreter import interpret_flow
from app.feeds.binance_ws import ws_manager
from app.redis_client import redis_manager

router = APIRouter()
PREVIEW_HISTORY_MINUTES = 15
def _full_view(auth: dict, doc: dict):
    """Full flow document; free plans also get one line on what the paid plans add."""
    if tier_level(auth.get("tier")) > 0:
        return FlowResponse(**doc)
    unlocks = ("Flow history, the full market scanner (100 rows), the event feed, BTC climate, ignitions and US equity flow; "
               f"derivatives for 10 symbols, Horus Cortex and webhooks on {plan_name(auth, 2)}")
    return JSONResponse(FlowResponse(**doc).model_dump(mode="json") | {"upgrade": upgrade_block(auth, 1, unlocks)})


@router.get("/{symbol}", response_model=FlowResponse)
async def get_flow_signal(symbol: str,
                          view: str = Query("full", pattern="^(full|compact)$",
                                            description="compact = token-light summary for AI agents"),
                          auth: dict = Depends(verify_api_key)):
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()

    if FREE_TIER_SYMBOLS and tier_level(auth.get("tier")) == 0 and clean_symbol not in FREE_TIER_SYMBOLS:
        raise upgrade_required(auth, 1, f"Your plan covers {', '.join(sorted(FREE_TIER_SYMBOLS))}. "
                                        f"Other pairs need the {plan_name(auth, 1)} plan or higher.", "Every Binance spot pair")

    # ⚡ Fast path: Redis cache (2s TTL). Keep the original timestamp so freshness is honest.
    cached = await redis_manager.get_cached_response(clean_symbol)
    if cached:
        ts = cached.get("timestamp") or time.time()
        cached["freshness_ms"] = int(max(0.0, time.time() - ts) * 1000)
        return JSONResponse(compact_flow(cached)) if view == "compact" else _full_view(auth, cached)

    status = ws_manager.add_symbol(clean_symbol)
    if status == "invalid":
        raise HTTPException(status_code=404, detail={"error": "unknown_symbol",
                                                     "message": f"{clean_symbol} is not a trading spot pair on Binance."})
    if status == "unavailable":
        raise HTTPException(status_code=503, detail={"error": "symbol_list_loading",
                                                     "message": "Symbol list is loading. Retry in a few seconds."})
    if status == "capacity":
        raise HTTPException(status_code=503, detail={"error": "tracking_capacity_reached",
                                                     "message": "Live tracking capacity reached. Try again later."})
    if status == "added":
        raise HTTPException(status_code=202, detail="Symbol just added to live tracking. Data arrives within seconds. Retry in 5 seconds.")

    response_data = await build_flow_response(clean_symbol)
    await redis_manager.set_cached_response(clean_symbol, response_data)
    if view == "compact":
        return JSONResponse(compact_flow(response_data))
    return _full_view(auth, response_data)


async def build_flow_response(clean_symbol: str, update_oscillation: bool = True) -> dict:
    """Compute the flow document for a tracked symbol. Raises HTTPException(503) when data is missing."""
    imb = ws_manager.imbalance.get_imbalance(clean_symbol)
    flow = ws_manager.flow.get_delta(clean_symbol)

    if not imb or not flow:
        raise HTTPException(
            status_code=503,
            detail="Insufficient flow data for this symbol right now. Try again shortly."
        )
    symbol = clean_symbol

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

    if update_oscillation and interpretation["confidence"] >= 0.50:
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

    response_data["metrics"]["price"] = ws_manager.flow.last_price(clean_symbol)
    response_data["reliability"] = track_record.reliability_for(
        response_data["signal"], clean_symbol, response_data["confidence"], response_data["direction_bias"])
    top5 = response_data["metrics"].get("top5_imbalance")
    if top5 is not None:
        response_data["book_information"] = {"top5_imbalance": top5, "book_tilt": book_measure.tilt(top5),
                                             "measured": await book_measure.current_measure(redis_manager.redis)}
    return response_data


# ═══════════════════════════════════════════════════════════════
#  NEW: History Endpoint — last N minutes of flow events
# ═══════════════════════════════════════════════════════════════

@router.get("/{symbol}/history")
async def get_flow_history(
    symbol: str,
    minutes: int = Query(default=30, ge=1, le=1440, description="Lookback in minutes (free preview 15, TRADER / RapidAPI PRO up to 60, PRO / RapidAPI ULTRA up to 1440)"),
    auth: dict = Depends(tier_or_preview("BUILDER"))
):
    """
    🦅 Flow History — Returns the last N minutes of orderflow snapshots.
    
    Snapshots are recorded every 15 seconds for every tracked symbol and include
    the signal fields plus price, deltas, ratios and depth metrics.
    """
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()
    cap = PREVIEW_HISTORY_MINUTES if auth["preview"] else 60 if tier_level(auth.get("tier")) < 2 else 1440
    capped = minutes > cap
    minutes = min(minutes, cap)

    history = await redis_manager.get_history(clean_symbol, minutes)

    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"No history available for {clean_symbol}. The symbol must be actively tracked first."
        )

    out = {
        "symbol": clean_symbol,
        "minutes": minutes,
        "snapshots": len(history),
        "history": history
    }
    if auth["preview"]:
        out["upgrade"] = upgrade_block(auth, 1, f"Up to 60 minutes of history, 24 hours on {plan_name(auth, 2)}",
                                       f"The last {cap} minutes on your plan")
    elif capped:
        out["upgrade"] = upgrade_block(auth, 2, "Up to 24 hours (1440 minutes) of history", f"The last {cap} minutes on your plan")
    return out
