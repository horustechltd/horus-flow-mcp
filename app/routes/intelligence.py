# -*- coding: utf-8 -*-
"""
Horus Flow Intelligence API — Premium Intelligence Endpoints v2.1
═══════════════════════════════════════════════════════════════
Exposes the hidden 90% of Horus:
  /climate     — WiseMan BTC Climate Gate (is the market worth trading?)
  /verdict     — Behavioral Court verdict for any asset
  /ignitions   — Global Ignition Scanner (which coins are about to explode?)
  /incubator   — Incubator Pipeline (rejected assets being nursed for re-entry)

All responses include strict schema fields:
  action, direction_bias, risk, market_regime, engine_version, freshness_ms, timestamp_utc

All data is read from the production Redis keys populated by the
saas_platform engines (wise_man.py, behavioral_court.py, vbe_engine.py).
"""
import json
import time
import logging
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional

from app.auth import verify_api_key, require_tier
from app.redis_client import redis_manager
from app.models import ENGINE_VERSION

logger = logging.getLogger("API.Intelligence")

# ═══ Emoji Stripping (shared with flow_interpreter) ═══
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF\U00002600-\U000026FF\U0000200D"
    "\U00002B50-\U00002B55\U0000231A-\U0000231B\U000023E9-\U000023F3"
    "\U000023F8-\U000023FA\U000025AA-\U000025AB\U000025B6"
    "\U000025FB-\U000025FE\U00002934-\U00002935\U00002B05-\U00002B07"
    "\U00003030\U00003297\U00003299"
    "]+", flags=re.UNICODE
)

def _strip_emojis(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()

router_intelligence = APIRouter()

# ═══════════════════════════════════════════════════════════════
# 🔐 TIER GATE — Handled by require_tier dependency from auth.py
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# 1️⃣  /climate — WiseMan BTC Market Climate
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/climate", tags=["Intelligence"])
async def get_market_climate(request: Request, auth: dict = Depends(require_tier("PRO"))):
    """
    🦅 WiseMan Climate Gate — Is the market worth trading right now?

    Returns BTC market mode (TREND/RANGE/CHOP/NO_TRADE),
    health assessment (HEALTHY/DECAYING/FRAGILE),
    and confidence score with full reasoning.

    This is the same intelligence used by the internal Horus trading engine
    to decide whether to scan the market or stay silent.
    """

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    try:
        raw = await redis_manager.redis.get("hta:state:wiseman_climate")
        if not raw:
            raise HTTPException(status_code=503, detail="WiseMan climate data not available yet")

        climate = json.loads(raw)

        # Enrich with aggression level
        aggression = await redis_manager.redis.get("horus:aggression:level")

        # Build trading recommendation
        mode = climate.get("market_mode", "UNKNOWN")
        health = climate.get("health", "UNKNOWN")
        confidence = climate.get("confidence", 0)

        if mode == "NO_TRADE" or health == "FRAGILE":
            recommendation = "🔴 STAY OUT — Market conditions are dangerous"
            action = "FULL_EXIT"
            market_regime = "NO_TRADE"
        elif mode == "CHOP":
            recommendation = "🟡 CAUTION — Choppy conditions, scalps only"
            action = "WAIT"
            market_regime = "CHOP"
        elif mode == "TREND" and health == "HEALTHY":
            recommendation = "🟢 SAFE TO TRADE — Trending market with healthy structure"
            action = "ENTER_LONG"  # Direction determined by other layers
            market_regime = "TRENDING"
        elif mode == "RANGE" and health == "HEALTHY":
            recommendation = "🟢 RANGE PLAYS — Mean-reversion strategies favored"
            action = "WAIT"
            market_regime = "RANGING"
        else:
            recommendation = "🟡 MIXED — Proceed with reduced size"
            action = "REDUCE_EXPOSURE"
            market_regime = "VOLATILE"

        # Derive risk from mode + health
        if mode == "NO_TRADE" or health == "FRAGILE":
            risk = "EXTREME"
        elif mode == "CHOP":
            risk = "HIGH"
        elif health == "DECAYING":
            risk = "MEDIUM"
        else:
            risk = "LOW"

        return {
            # === Strict Schema ===
            "action": action,
            "direction_bias": "NEUTRAL",  # Climate is direction-agnostic
            "risk": risk,
            "market_regime": market_regime,
            "engine_version": ENGINE_VERSION,
            "freshness_ms": int((time.time() - climate.get("timestamp_epoch", time.time())) * 1000) if isinstance(climate.get("timestamp_epoch"), (int, float)) else 0,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "explanation": recommendation.split(" — ")[1] if " — " in recommendation else recommendation,
            
            # === Existing fields (backward compatible) ===
            "market_mode": mode,
            "health": health,
            "confidence": confidence,
            "recommendation": recommendation,
            "reasoning": climate.get("reason", ""),
            "aggression_level": float(aggression) if aggression else 0.5,
            "timestamp": climate.get("timestamp", ""),
            "engine": "WiseMan Cognitive Gate v64.0"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Climate endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 2️⃣  /ignitions — Global Ignition Scanner
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/ignitions", tags=["Intelligence"])
async def get_ignitions(request: Request, auth: dict = Depends(require_tier("ULTRA"))):
    """
    🔥 Ignition Scanner — Which coins are about to explode?

    Returns the global ignition regime (DORMANT/RISING/IGNITED),
    plus per-coin ignition scores for all tracked assets.

    Ignition Score >= 0.6 = HIGH probability of explosive move.
    Ignition Score >= 0.8 = EXTREME — institutional-grade signal.
    """

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    try:
        raw = await redis_manager.redis.get("horus:global_ignition_state")
        if not raw:
            raise HTTPException(status_code=503, detail="Ignition data not available yet")

        state = json.loads(raw)

        # Get per-coin distribution.
        # NOTE: `horus:ignition_distribution` is published as a Redis HASH
        # by vbe_engine (field=symbol, value=ignition_score). We read it,
        # coerce values to float, sort descending, and return top 20.
        distribution = []
        try:
            key_type = await redis_manager.redis.type("horus:ignition_distribution")
            if isinstance(key_type, bytes):
                key_type = key_type.decode()

            if key_type == "hash":
                raw_map = await redis_manager.redis.hgetall("horus:ignition_distribution")
                parsed = []
                for sym, score in raw_map.items():
                    try:
                        sym_s = sym if isinstance(sym, str) else sym.decode()
                        score_f = float(score)
                        parsed.append((sym_s, score_f))
                    except (TypeError, ValueError):
                        continue
                parsed.sort(key=lambda x: x[1], reverse=True)
                for sym_s, score_f in parsed[:20]:
                    distribution.append({
                        "symbol": sym_s,
                        "ignition_score": round(score_f, 4),
                        "status": "🔥 IGNITED" if score_f >= 0.6 else "⚡ WARMING" if score_f >= 0.4 else "💤 DORMANT"
                    })
            elif key_type == "zset":
                # Backward-compatible path in case the producer ever switches to a sorted set
                dist_data = await redis_manager.redis.zrevrangebyscore(
                    "horus:ignition_distribution", "+inf", "0", withscores=True, start=0, num=20
                )
                for symbol, score in dist_data:
                    distribution.append({
                        "symbol": symbol if isinstance(symbol, str) else symbol.decode(),
                        "ignition_score": round(score, 4),
                        "status": "🔥 IGNITED" if score >= 0.6 else "⚡ WARMING" if score >= 0.4 else "💤 DORMANT"
                    })
        except Exception as e:
            logger.warning(f"Ignition distribution read failed: {e}")

        metrics = state.get("metrics", {})

        regime = state.get("regime", "UNKNOWN")
        regime_bias = state.get("regime_bias", "NEUTRAL")
        
        # Strict schema: map ignition regime to action/risk
        if regime == "ERUPTING":
            ign_action = "ENTER_LONG"
            ign_risk = "HIGH"
            ign_market_regime = "LIQUIDITY_EVENT"
        elif regime == "IGNITING":
            ign_action = "ENTER_LONG"
            ign_risk = "MEDIUM"
            ign_market_regime = "VOLATILE"
        else:  # DORMANT
            ign_action = "WAIT"
            ign_risk = "LOW"
            ign_market_regime = "RANGING"
        
        return {
            # === Strict Schema ===
            "action": ign_action,
            "direction_bias": "BULLISH" if regime_bias == "RISING" else "BEARISH" if regime_bias == "FALLING" else "NEUTRAL",
            "risk": ign_risk,
            "market_regime": ign_market_regime,
            "engine_version": ENGINE_VERSION,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            
            # === Existing fields ===
            "regime": regime,
            "regime_bias": regime_bias,
            "global_ignition_score": round(state.get("global_ignition", 0), 4),
            "delta": round(state.get("delta", 0), 4),
            "stability": round(state.get("stability_score", 0), 2),
            "summary": {
                "total_tracked": metrics.get("total_tracked", 0),
                "avg_ignition": round(metrics.get("avg_ignition", 0), 4),
                "pct_above_0_6": round(metrics.get("pct_above_0_6", 0) * 100, 1),
                "pct_above_0_8": round(metrics.get("pct_above_0_8", 0) * 100, 1),
            },
            "top_ignitions": distribution,
            "timestamp": state.get("timestamp", ""),
            "engine": "Volatility Breakout Engine (VBE)"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ignitions endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 3️⃣  /verdict/{symbol} — Behavioral Court Verdict
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/verdict/{symbol}", tags=["Intelligence"])
async def get_court_verdict(symbol: str, request: Request, auth: dict = Depends(require_tier("PRO"))):
    """
    ⚖️ Behavioral Court — What is the Court's judgment on this asset?

    Returns the incubator state for the asset, which includes:
    - Court rejection reason (why was it convicted?)
    - Current state (HOT/WAITING_BOUNCE/ABSORBING/READY)
    - Action recommendation (IGNORE/PROBE/FULL_ENTRY)
    - Original signal data with full judicial evidence

    Assets in READY state with FULL_ENTRY action are the ones
    that achieved 100% win rate on the EdgeBridge strategy.
    """

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    clean = symbol.replace("-", "/").upper()
    if "/" not in clean:
        # Convert BTCUSDT → BTC/USDT
        for quote in ["USDT", "BUSD", "USDC", "BTC", "ETH"]:
            if clean.endswith(quote):
                clean = clean[:-len(quote)] + "/" + quote
                break

    try:
        data = await redis_manager.redis.hgetall(f"incubator:{clean}")

        if not data:
            return {
                # === Strict Schema ===
                "action": "WAIT",
                "direction_bias": "NEUTRAL",
                "risk": "MEDIUM",
                "engine_version": ENGINE_VERSION,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                
                # === Existing fields ===
                "symbol": clean,
                "status": "NOT_TRACKED",
                "message": "This asset has no court record. It may be clean or not yet scanned.",
                "recommendation": "Use /v1/flow/crypto/{symbol} for raw orderflow data.",
                "engine": "Behavioral Court v1.0"
            }

        # Parse original signal if available
        original_signal = {}
        judicial_evidence = {}
        wiseman_at_signal = {}
        if data.get("original_signal"):
            try:
                sig = json.loads(data["original_signal"])
                original_signal = {
                    "entry_price": sig.get("price"),
                    "stop_loss": sig.get("stop_loss"),
                    "take_profit": sig.get("take_profit"),
                    "strength": sig.get("strength"),
                    "strategy": sig.get("strategy"),
                    "signal_time": sig.get("timestamp"),
                }
                # Extract court evidence
                je = sig.get("judicial_evidence", {})
                if je:
                    pre_cascade = je.get("pre_cascade_evidence", {})
                    judicial_evidence = {
                        "accumulation_detected": pre_cascade.get("accumulation_context", False),
                        "absorption_detected": pre_cascade.get("absorption_detected", False),
                        "domino_pressure": pre_cascade.get("domino_pressure", False),
                        "volatility_readiness": pre_cascade.get("volatility_readiness", 0),
                        "mmc_verdict": je.get("mmc_verdict", ""),
                        "mmc_score": je.get("mmc_score", 0),
                        "global_regime": je.get("global_regime", ""),
                        "global_ignition": je.get("global_ignition", 0),
                    }
                wiseman_at_signal = sig.get("wiseman_climate", {})
            except Exception:
                pass

        state = data.get("current_state", "UNKNOWN")
        action = data.get("action", "UNKNOWN")

        # Build human-readable verdict
        if state == "READY" and action == "FULL ENTRY":
            verdict_summary = "🟢 READY — Bounce confirmed. EdgeBridge entry conditions met."
        elif state == "ABSORBING" and action == "PROBE":
            verdict_summary = "🟡 ABSORBING — Early bounce detected. Probe position recommended."
        elif state == "WAITING_BOUNCE":
            verdict_summary = "🔴 WAITING — Asset dropped but no confirmed bounce yet."
        elif state == "HOT":
            verdict_summary = "⚪ HOT — Asset hasn't dropped enough yet. Monitoring."
        else:
            verdict_summary = f"📋 {state} — {action}"

        return {
            "symbol": clean,
            "court_verdict": data.get("rejection_type", "UNKNOWN"),
            "incubator_state": state,
            "action": action,
            "verdict_summary": verdict_summary,
            "current_price": float(data.get("price", 0)),
            "tracking_cycles": int(data.get("global_tracking_cycles", 0)),
            "original_signal": original_signal,
            "judicial_evidence": judicial_evidence,
            "wiseman_at_conviction": wiseman_at_signal,
            "timestamp": time.time(),
            "engine": "Behavioral Court v1.0 + Incubator v5.2"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Verdict endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 4️⃣  /incubator — Full Incubator Pipeline
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/incubator", tags=["Intelligence"])
async def get_incubator_pipeline(request: Request, auth: dict = Depends(require_tier("PRO"))):
    """
    🍼 Incubator Pipeline — All assets currently being nursed for re-entry.

    Shows every asset that was rejected by the Behavioral Court and is now
    being monitored for a potential rebound entry. Assets in READY state
    are the highest-conviction opportunities.

    This is the intelligence layer behind the EdgeBridge strategy
    that achieved 6/6 wins (+$3,269) in April 2026.
    """

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    try:
        # Scan all incubator:* keys
        pipeline_ready = []
        pipeline_absorbing = []
        pipeline_waiting = []
        pipeline_hot = []

        async for key in redis_manager.redis.scan_iter("incubator:*"):
            try:
                data = await redis_manager.redis.hgetall(key)
                if not data:
                    continue

                symbol = data.get("symbol", key.split(":", 1)[1] if ":" in key else key)
                state = data.get("current_state", "UNKNOWN")
                action = data.get("action", "IGNORE")
                price = float(data.get("price", 0))

                entry = {
                    "symbol": symbol,
                    "state": state,
                    "action": action,
                    "price": price,
                    "rejection_reason": data.get("rejection_type", "")[:80],
                    "tracking_cycles": int(data.get("global_tracking_cycles", 0)),
                }

                if state == "READY":
                    pipeline_ready.append(entry)
                elif state == "ABSORBING":
                    pipeline_absorbing.append(entry)
                elif state == "WAITING_BOUNCE":
                    pipeline_waiting.append(entry)
                else:
                    pipeline_hot.append(entry)

            except Exception:
                continue

        total = len(pipeline_ready) + len(pipeline_absorbing) + len(pipeline_waiting) + len(pipeline_hot)

        return {
            # === Strict Schema ===
            "action": "ENTER_LONG" if len(pipeline_ready) > 0 else "WAIT",
            "risk": "LOW" if len(pipeline_ready) > 0 else "MEDIUM",
            "engine_version": ENGINE_VERSION,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            
            # === Existing fields ===
            "total_incubated": total,
            "summary": {
                "ready_count": len(pipeline_ready),
                "absorbing_count": len(pipeline_absorbing),
                "waiting_count": len(pipeline_waiting),
                "hot_count": len(pipeline_hot),
            },
            "ready": pipeline_ready,
            "absorbing": pipeline_absorbing,
            "waiting": pipeline_waiting,
            "hot": pipeline_hot,
            "note": "Assets in 'ready' state have confirmed bounces and meet EdgeBridge entry criteria.",
            "timestamp": time.time(),
            "engine": "Incubator v5.2 + EdgeBridge"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Incubator endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 5️⃣  /liquidation-heatmap — Liquidation Gravity Map
# ═══════════════════════════════════════════════════════════════

VALID_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
STALE_THRESHOLD = 300  # 5 minutes


def _check_freshness(data: dict) -> str:
    """Check if data is stale (> 5 min old)."""
    ts = data.get("timestamp", 0)
    if isinstance(ts, str):
        return "FRESH"
    return "FRESH" if (time.time() - ts) < STALE_THRESHOLD else "STALE"


@router_intelligence.get("/liquidation-heatmap", tags=["Level 3 Intelligence"])
async def get_liquidation_heatmap(symbol: str = "BTCUSDT", auth: dict = Depends(require_tier("PRO"))):
    """
    🔥 Liquidation Heatmap — Where is the price forced to go?

    Shows where leveraged positions are clustered and estimates
    liquidation cascade zones. Uses Binance Futures OI, Long/Short ratios,
    Top Trader positioning, and Taker Buy/Sell volume.

    - gravity_direction: DOWN (longs will get liquidated) / UP (shorts squeezed)
    - gravity_score: 0.0 to 1.0 intensity
    - smart_money_divergence: true = top traders disagree with crowd
    - estimated_liquidation_zones: exact price levels for cascades
    """
    clean = symbol.upper()
    if clean not in VALID_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Symbol {clean} not tracked. Available: {', '.join(sorted(VALID_SYMBOLS))}")

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    try:
        raw = await redis_manager.redis.get(f"horus:liq_heatmap:{clean}")
        if not raw:
            raise HTTPException(status_code=404, detail=f"No liquidation heatmap data for {clean}. Worker may be starting up.")

        data = json.loads(raw)
        data["data_freshness"] = _check_freshness(data)
        data["engine"] = "Liquidation Heatmap v1.0"
        
        # === Derive strict schema fields (Issue #6: improved action logic) ===
        gravity = data.get("gravity_direction", "")
        gravity_score = data.get("gravity_score", 0.5)
        crowd = data.get("crowd_bias", "")
        smd = data.get("smart_money_divergence", False)
        
        data["direction_bias"] = "BULLISH" if gravity == "UP" else "BEARISH" if gravity == "DOWN" else "NEUTRAL"
        
        # Action: factor in crowd_bias, SMD, and gravity (not just gravity_score > 0.6)
        if crowd == "OVERLEVERAGED_LONG" and gravity == "DOWN":
            data["action"] = "BLOCK_LONG"
        elif crowd == "OVERLEVERAGED_SHORT" and gravity == "UP":
            data["action"] = "BLOCK_SHORT"
        elif smd:
            data["action"] = "REDUCE_EXPOSURE"
        elif gravity == "DOWN" and gravity_score > 0.6:
            data["action"] = "BLOCK_LONG"
        elif gravity == "UP" and gravity_score > 0.6:
            data["action"] = "BLOCK_SHORT"
        else:
            data["action"] = "WAIT"
        
        if gravity_score > 0.7 or "OVERLEVERAGED" in crowd:
            data["risk"] = "EXTREME"
        elif gravity_score > 0.5 or smd:
            data["risk"] = "HIGH"
        elif gravity_score > 0.3:
            data["risk"] = "MEDIUM"
        else:
            data["risk"] = "LOW"
        
        data["market_regime"] = "LIQUIDITY_EVENT" if gravity_score > 0.7 else "VOLATILE" if gravity_score > 0.5 else "RANGING"
        data["engine_version"] = ENGINE_VERSION
        data["freshness_ms"] = int((time.time() - data.get("timestamp", time.time())) * 1000)
        data["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        raw_explanation = data.get("risk_assessment", "").split(" — ")[1] if " — " in data.get("risk_assessment", "") else ""
        data["explanation"] = _strip_emojis(raw_explanation)
        
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Liquidation heatmap endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 6️⃣  /cross-exchange-flow — Spot ↔ Futures Flow Analysis
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/cross-exchange-flow", tags=["Level 3 Intelligence"])
async def get_cross_exchange_flow(symbol: str = "BTCUSDT", auth: dict = Depends(require_tier("PRO"))):
    """
    🔄 Cross-Exchange Flow — Is the move real or speculative?

    Compares Spot vs Futures volume, tracks Futures Premium/Discount,
    and monitors OI velocity to detect aggressive positioning.

    - market_type: SPOT_DRIVEN (real) / HYPER_SPECULATION (dangerous)
    - premium_bias: BULLISH / BEARISH / NEUTRAL
    - positioning_signal: AGGRESSIVE_POSITIONING_LONG / SHORT / MASS_DELEVERAGING
    """
    clean = symbol.upper()
    if clean not in VALID_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Symbol {clean} not tracked. Available: {', '.join(sorted(VALID_SYMBOLS))}")

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    try:
        raw = await redis_manager.redis.get(f"horus:xflow:{clean}")
        if not raw:
            raise HTTPException(status_code=404, detail=f"No cross-exchange flow data for {clean}. Worker may be starting up.")

        data = json.loads(raw)
        data["data_freshness"] = _check_freshness(data)
        data["engine"] = "Cross-Exchange Flow v1.0"
        
        # === Derive strict schema fields (Issue #9: funding rate logic) ===
        market_type = data.get("market_type", "")
        premium_bias = data.get("premium_bias", "NEUTRAL")
        positioning = data.get("positioning_signal", "")
        funding = data.get("funding_rate", 0) or 0
        
        if premium_bias == "BULLISH":
            data["direction_bias"] = "BULLISH"
        elif premium_bias == "BEARISH":
            data["direction_bias"] = "BEARISH"
        else:
            data["direction_bias"] = "NEUTRAL"
        
        if "MASS_DELEVERAGING" in positioning:
            data["risk"] = "EXTREME"
            data["action"] = "FULL_EXIT"
            data["market_regime"] = "LIQUIDITY_EVENT"
        elif market_type == "HYPER_SPECULATION":
            data["risk"] = "HIGH"
            # Extreme funding = block the side paying
            if funding > 0.0005:
                data["action"] = "BLOCK_LONG"  # longs paying shorts heavily
            elif funding < -0.0005:
                data["action"] = "BLOCK_SHORT"  # shorts paying longs heavily
            else:
                data["action"] = "REDUCE_EXPOSURE"
            data["market_regime"] = "VOLATILE"
        elif market_type == "SPOT_DRIVEN":
            data["risk"] = "LOW"
            data["action"] = "WAIT"
            data["market_regime"] = "TRENDING"
        else:
            data["risk"] = "MEDIUM"
            data["action"] = "WAIT"
            data["market_regime"] = "RANGING"
        
        data["engine_version"] = ENGINE_VERSION
        data["freshness_ms"] = int((time.time() - data.get("timestamp", time.time())) * 1000)
        data["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        raw_xflow_explanation = data.get("risk_assessment", "").split(" — ")[1] if " — " in data.get("risk_assessment", "") else data.get("risk_assessment", "")
        data["explanation"] = _strip_emojis(raw_xflow_explanation)
        
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cross-exchange flow endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 7️⃣  /composite — Composite Intelligence Score (The Verdict)
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/composite", tags=["Level 3 Intelligence"])
async def get_composite_intelligence(symbol: str = "BTCUSDT", auth: dict = Depends(require_tier("PRO"))):
    """
    🦅 Composite Intelligence — The Final Verdict.

    Combines 4 intelligence layers into ONE actionable score (0-100):
      - Climate (WiseMan): Is the market worth trading?
      - Ignition (VBE): Is volatility about to explode?
      - Heatmap (Liquidations): Where is price forced to go?
      - XFlow (Spot↔Futures): Is the move real or speculative?

    Verdicts:
      - FULL_CONVICTION (>80): All layers agree. High-probability trade.
      - PARTIAL_CONVICTION (60-80): Most layers agree. Proceed with caution.
      - NEUTRAL (40-60): Mixed signals. No edge.
      - STAY_OUT (<40): Conditions unfavorable. Do not trade.

    Strict schema fields included:
      action, direction_bias, risk, market_regime, engine_version
    """
    clean = symbol.upper()
    if clean not in VALID_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Symbol {clean} not tracked. Available: {', '.join(sorted(VALID_SYMBOLS))}")

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    try:
        raw = await redis_manager.redis.get(f"horus:composite:{clean}")
        if not raw:
            raise HTTPException(status_code=404, detail=f"No composite intelligence for {clean}. Worker may be starting up.")

        data = json.loads(raw)
        data["data_freshness"] = _check_freshness(data)
        data["engine"] = "Composite Intelligence v1.0 (Climate + Ignition + Heatmap + XFlow)"
        
        # === Derive strict schema fields ===
        verdict = data.get("verdict", "NEUTRAL")
        direction = data.get("direction", "")
        score = data.get("composite_score", 0)
        
        # action
        if verdict == "FULL_CONVICTION":
            data["action"] = "ENTER_LONG" if direction == "LONG" else "ENTER_SHORT"
        elif verdict == "PARTIAL_CONVICTION":
            data["action"] = "ENTER_LONG" if direction == "LONG" else "ENTER_SHORT"
        elif verdict == "STAY_OUT":
            data["action"] = "WAIT"
        else:
            data["action"] = "WAIT"
        
        # direction_bias
        if direction == "LONG":
            data["direction_bias"] = "BULLISH"
        elif direction == "SHORT":
            data["direction_bias"] = "BEARISH"
        else:
            data["direction_bias"] = "NEUTRAL"
        
        # risk
        if score >= 80:
            data["risk"] = "LOW"
        elif score >= 60:
            data["risk"] = "MEDIUM"
        elif score >= 40:
            data["risk"] = "HIGH"
        else:
            data["risk"] = "EXTREME"
        
        # market_regime (from climate detail)
        climate_detail = data.get("details", {}).get("climate", "")
        if "CHOP" in climate_detail:
            data["market_regime"] = "CHOP"
        elif "TREND" in climate_detail:
            data["market_regime"] = "TRENDING"
        elif "NO_TRADE" in climate_detail:
            data["market_regime"] = "NO_TRADE"
        elif "RANGE" in climate_detail:
            data["market_regime"] = "RANGING"
        else:
            data["market_regime"] = "VOLATILE"
        
        # Safety override: no entries during extreme risk
        if data["risk"] == "EXTREME" and data["action"] in ("ENTER_LONG", "ENTER_SHORT"):
            data["action"] = "WAIT"
        
        # metadata
        data["confidence"] = round(score / 100, 2)
        data["engine_version"] = ENGINE_VERSION
        data["freshness_ms"] = int((time.time() - data.get("timestamp", time.time())) * 1000)
        data["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        data["explanation"] = _strip_emojis(data.get("one_liner", ""))
        
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Composite intelligence endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 8️⃣  /market-intelligence — Full Intelligence Dashboard (All-in-One)
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/market-intelligence", tags=["Level 3 Intelligence"])
async def get_full_market_intelligence(auth: dict = Depends(require_tier("PRO"))):
    """
    🌐 Full Market Intelligence — Everything in one call.

    Returns ALL intelligence layers for ALL tracked symbols in a single response.
    This is the ultimate endpoint for dashboards and AI agents.
    """

    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Intelligence data source unavailable")

    try:
        now_utc = datetime.now(timezone.utc).isoformat()
        
        result = {
            "timestamp": time.time(),
            "timestamp_utc": now_utc,
            "engine": "Horus Level 3 Intelligence v1.0",
            "engine_version": ENGINE_VERSION,
            "symbols": {},
            "action_summary": {},  # NEW: per-symbol quick action lookup
        }

        # Read summaries
        for key_name, field_name in [
            ("horus:liq_heatmap:summary", "heatmap_summary"),
            ("horus:xflow:summary", "xflow_summary"),
            ("horus:composite:summary", "composite_summary"),
        ]:
            raw = await redis_manager.redis.get(key_name)
            if raw:
                result[field_name] = json.loads(raw)

        # Read climate
        raw_climate = await redis_manager.redis.get("hta:state:wiseman_climate")
        if raw_climate:
            result["climate"] = json.loads(raw_climate)

        # Read ignition
        raw_ignition = await redis_manager.redis.get("horus:global_ignition_state")
        if raw_ignition:
            result["ignition"] = json.loads(raw_ignition)

        # Read Cortex state (Maestro)
        raw_cortex = await redis_manager.redis.get("horus:maestro:state")
        if raw_cortex:
            cortex_dict = json.loads(raw_cortex)
            result["cortex"] = {
                "state": cortex_dict.get("state"),
                "trust_score": cortex_dict.get("trust_score"),
                "weapons_policy": cortex_dict.get("weapons_policy"),
                "narrative": cortex_dict.get("narrative"),
                "active_contradictions": cortex_dict.get("contradictions", [])
            }

        # Per-symbol detail
        for sym in sorted(VALID_SYMBOLS):
            sym_data = {}
            for prefix, label in [
                ("horus:liq_heatmap:", "heatmap"),
                ("horus:xflow:", "xflow"),
                ("horus:composite:", "composite"),
            ]:
                raw = await redis_manager.redis.get(f"{prefix}{sym}")
                if raw:
                    parsed = json.loads(raw)
                    parsed["data_freshness"] = _check_freshness(parsed)
                    sym_data[label] = parsed

            if sym_data:
                result["symbols"][sym] = sym_data
                
                # Build action_summary from composite data
                comp = sym_data.get("composite", {})
                if comp:
                    verdict = comp.get("verdict", "NEUTRAL")
                    direction = comp.get("direction", "")
                    score = comp.get("composite_score", 0)
                    
                    if verdict == "FULL_CONVICTION":
                        sym_action = "ENTER_LONG" if direction == "LONG" else "ENTER_SHORT"
                    elif verdict == "PARTIAL_CONVICTION":
                        sym_action = "ENTER_LONG" if direction == "LONG" else "ENTER_SHORT"
                    else:
                        sym_action = "WAIT"
                    
                    sym_bias = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else "NEUTRAL"
                    sym_risk = "LOW" if score >= 80 else "MEDIUM" if score >= 60 else "HIGH" if score >= 40 else "EXTREME"
                    
                    # Safety override
                    if sym_risk == "EXTREME" and sym_action in ("ENTER_LONG", "ENTER_SHORT"):
                        sym_action = "WAIT"
                    
                    result["action_summary"][sym] = {
                        "action": sym_action,
                        "direction_bias": sym_bias,
                        "risk": sym_risk,
                        "composite_score": score,
                        "verdict": verdict,
                    }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Full market intelligence endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal intelligence error")


# ═══════════════════════════════════════════════════════════════
# 9️⃣  /cortex & /maestro — Horus Cortex Cognitive Intelligence
# ═══════════════════════════════════════════════════════════════

@router_intelligence.get("/cortex", tags=["Level 4 Cognitive Intelligence"])
@router_intelligence.get("/maestro", tags=["Level 4 Cognitive Intelligence"], include_in_schema=False)
async def get_horus_cortex(auth: dict = Depends(require_tier("PRO"))):
    """
    🦅 Horus Cortex — Full-Spectrum Cognitive Market Brain.

    Fuses 7 independent evidence families into a single authoritative state:
      1. Price Structure (HH/HL, 15m/1h Momentum Returns)
      2. Dynamic S/R Map (Volume-weighted Structural Pivots)
      3. Orderflow (Taker Aggressive Ratio, Imbalance & Delta)
      4. Lagging Witnesses (Moving Averages, Macro Confirmations)
      5. Cycle Memory (Wave Extension %, Touch Count at Boundaries)
      6. Breadth & RS (Global Ignition, Altcoin Flow Gravity)
      7. Microstructure Anomaly (Absorption Traps, Spoofing, Wall Pulls)

    Features:
      - First-Class Contradiction Engine (Catches Divergences like Price-Up vs Flow-Down)
      - Penalized Trust Score (0-100) based on Evidence Freshness and Coherence
      - Execution Boundaries (Concrete Support/Resistance Invalidation Levels)
      - Dynamic Action Policy (Position Sizing Multipliers for Autonomous Bots)
      - Deterministic Institutional Arabic & English Narrative
    """
    if not redis_manager.redis:
        raise HTTPException(status_code=503, detail="Cortex data source unavailable")

    try:
        raw_state = await redis_manager.redis.get("horus:maestro:state")
        if not raw_state:
            raise HTTPException(status_code=404, detail="Horus Cortex engine warming up. Please retry shortly.")

        state = json.loads(raw_state)
        
        narrative = state.get("narrative") or {}
        evidence = state.get("evidence_ledger") or []
        contradictions = state.get("contradictions") or []
        weapons = state.get("weapons_policy") or {}
        
        btc_price = float(state.get("btc_price") or 0.0)
        
        invalidation_sup = 0.0
        breakout_res = 0.0
        
        for w in narrative.get("what_worsens_verdict", []):
            if "$" in w:
                try:
                    part = w.split("$")[1].split()[0].replace(",", "")
                    invalidation_sup = float(part)
                    break
                except Exception:
                    pass
                    
        for i in narrative.get("what_improves_verdict", []):
            if "$" in i:
                try:
                    part = i.split("$")[1].split()[0].replace(",", "")
                    breakout_res = float(part)
                    break
                except Exception:
                    pass
                    
        if invalidation_sup == 0.0 and btc_price > 0:
            invalidation_sup = round(btc_price * 0.99, 2)
        if breakout_res == 0.0 and btc_price > 0:
            breakout_res = round(btc_price * 1.01, 2)

        # Check freshness from market_clock_iso
        clock_iso = state.get("market_clock_iso")
        freshness_status = "FRESH"
        if clock_iso:
            try:
                dt = datetime.fromisoformat(clock_iso)
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                freshness_status = "FRESH" if age < 60 else "STALE"
            except Exception:
                freshness_status = "FRESH"

        # Unify headline branding to Horus Cortex
        if isinstance(narrative, dict) and "headline" in narrative:
            narrative["headline"] = narrative["headline"].replace("تقرير المايسترو", "تقرير عقل حورس")

        return {
            "status": "success",
            "timestamp": time.time(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "engine": "Horus Cortex Symphony v3.0",
            "regime_state": state.get("state", "TRANSITION"),
            "transition_direction": state.get("transition_direction", "STABLE"),
            "trust_score": round(float(state.get("trust_score", 50.0)), 1),
            "trust_components": state.get("trust_components", {}),
            "penalties": state.get("penalties", {}),
            "action_policy": {
                "directive": weapons.get("policy_reason", "Selective Operations"),
                "ignition_multiplier": weapons.get("ignition_multiplier", 0.0),
                "trend_multiplier": weapons.get("mtf_multiplier", 0.0),
                "reversal_multiplier": weapons.get("reversal_multiplier", 0.0),
                "shock_multiplier": weapons.get("shock_multiplier", 0.0),
                "ignition_allowed": weapons.get("ignition_allowed", False),
                "trend_allowed": weapons.get("mtf_allowed", False),
                "reversal_allowed": weapons.get("reversal_allowed", False),
            },
            "execution_boundaries": {
                "btc_price": btc_price,
                "invalidation_support": invalidation_sup,
                "breakout_resistance": breakout_res,
                "invalidation_risk_pct": round((btc_price - invalidation_sup) / btc_price * 100, 2) if btc_price > 0 else 0.0,
                "breakout_target_pct": round((breakout_res - btc_price) / btc_price * 100, 2) if btc_price > 0 else 0.0,
            },
            "market_vitals": {
                "taker_ratio": state.get("taker_ratio", 1.0),
                "global_ignition": state.get("global_ignition", 0.0),
                "global_dominant_gravity": state.get("global_dominant_gravity", "NEUTRAL"),
                "btc_15m_return_pct": state.get("btc_15m_return_pct", 0.0),
                "btc_1h_return_pct": state.get("btc_1h_return_pct", 0.0),
            },
            "active_contradictions": contradictions,
            "narrative": narrative,
            "evidence_ledger": evidence,
            "cycle_memory": state.get("cycle_memory", {}),
            "data_freshness": freshness_status
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Horus Cortex endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal Cortex intelligence error")


