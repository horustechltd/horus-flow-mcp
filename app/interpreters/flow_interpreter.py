# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — flow_interpreter.py
Full-spectrum microstructure interpreter.

Synced with the main SaaS brain (horus_trade_advisor.py) logic.
Uses ALL computed signals from imbalance.py and flow_detector.py.
"""
from typing import Dict, Any


def interpret_flow(symbol: str, imb: Dict[str, Any], flow: Dict[str, Any], state: str, wiseman_climate: Dict[str, Any] = None, whale_intent: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Interprets raw orderbook imbalance and trade flow data into
    an institutional-grade signal with full microstructure context.
    """
    
    # ═══════════════════════════════════════════
    # Extract ALL available data (zero extra computation)
    # ═══════════════════════════════════════════
    
    # From imbalance.py
    bid_ratio = imb.get("ratio", 1.0)
    top5_imbalance = imb.get("top5_imbalance", 0.5)
    imb_stability = imb.get("imb_stability", 0.0)
    wall_side = imb.get("wall_side", None)
    spread_pct = imb.get("spread_pct", 0.0)
    refill_ratio = imb.get("refill_ratio", 1.0)
    bid_depth_change = imb.get("bid_depth_change_pct", 0.0)
    ask_depth_change = imb.get("ask_depth_change_pct", 0.0)
    
    # From flow_detector.py
    buy_ratio = flow.get("buy_ratio", 0.5)
    delta_5s = flow.get("delta_5s", 0)
    delta_30s = flow.get("delta_30s", 0)
    delta_60s = flow.get("delta_60s", 0)
    delta_5m = flow.get("delta_5m", 0)
    macro_divergence = flow.get("macro_divergence", "NONE")
    sell_spike = flow.get("sell_spike", False)
    large_sell_count = flow.get("large_sell_count", 0)
    delta_accel = flow.get("delta_accel", 0.0)
    delta_declining = flow.get("delta_declining", False)
    trade_count_30s = flow.get("trade_count_30s", 0)
    avg_trade_size = flow.get("avg_trade_size", 0.0)
    
    # From derivatives_engine.py (OI + Funding + Liquidations)
    try:
        from app.engines.derivatives_engine import derivatives_engine
        deriv = derivatives_engine.get_derivatives_state(symbol)
        # Also feed price for OI divergence
        derivatives_engine.feed_price(symbol, imb.get("best_bid", 0))
    except Exception:
        deriv = {"oi_signal": "NONE", "funding_signal": "NONE", "liquidation_signal": "NONE", "has_data": False}
    
    # ═══════════════════════════════════════════
    # Phase 1: Global Market State Override
    # ═══════════════════════════════════════════
    
    signal = "NEUTRAL"
    confidence = 0.50
    risk = "MEDIUM"
    state_desc = "RANGE_BOUND"
    flags = []  # Human-readable event flags
    
    if state == "LIQUIDITY_EVENT":
        signal = "EMERGENCY_DUMP"
        confidence = 0.99
        state_desc = "LIQUIDITY_EVENT"
        risk = "EXTREME"
        flags.append("GLOBAL_LIQUIDITY_EVENT")
        desc = "Critical liquidity withdrawal detected globally. Do not enter longs. Close existing positions if unprotected."
        # Skip all other checks — this is the nuclear option
        return _build_response(signal, confidence, state_desc, risk, desc, flags,
                               imb, flow, sell_spike, large_sell_count, wall_side,
                               delta_accel, refill_ratio, top5_imbalance, spread_pct,
                               bid_depth_change, ask_depth_change, wiseman_climate)
    
    # ═══════════════════════════════════════════
    # Phase 1.2: Liquidation Cascade Detection (Derivatives)
    # ═══════════════════════════════════════════
    
    if deriv.get("liquidation_signal") == "CASCADE_LONG":
        signal = "LIQUIDATION_CASCADE"
        confidence = 0.95
        state_desc = "LONG_LIQUIDATION"
        risk = "EXTREME"
        liq_usd = deriv.get("liq_long_usd_60s", 0)
        flags.append(f"LONG_CASCADE(${liq_usd:,.0f})")
        desc = f"🔥 LIQUIDATION CASCADE: ${liq_usd:,.0f} in long liquidations in 60s. Waterfall dump imminent."
        return _build_response(signal, confidence, state_desc, risk, desc, flags,
                               imb, flow, sell_spike, large_sell_count, wall_side,
                               delta_accel, refill_ratio, top5_imbalance, spread_pct,
                               bid_depth_change, ask_depth_change, wiseman_climate)
    
    elif deriv.get("liquidation_signal") == "CASCADE_SHORT":
        signal = "SHORT_SQUEEZE"
        confidence = 0.95
        state_desc = "SHORT_LIQUIDATION"
        risk = "LOW"
        liq_usd = deriv.get("liq_short_usd_60s", 0)
        flags.append(f"SHORT_SQUEEZE(${liq_usd:,.0f})")
        desc = f"🚀 SHORT SQUEEZE: ${liq_usd:,.0f} in short liquidations in 60s. Violent pump imminent."
        return _build_response(signal, confidence, state_desc, risk, desc, flags,
                               imb, flow, sell_spike, large_sell_count, wall_side,
                               delta_accel, refill_ratio, top5_imbalance, spread_pct,
                               bid_depth_change, ask_depth_change, wiseman_climate)

    # ═══════════════════════════════════════════
    # Phase 1.5: HFT Predictive Macro Foresight (Icebergs)
    # ═══════════════════════════════════════════
    
    if macro_divergence == "BEARISH_ABSORPTION":
        signal = "IMMINENT_DUMP_5M"
        confidence = 0.95
        state_desc = "HIDDEN_DISTRIBUTION"
        risk = "EXTREME"
        flags.append("ICEBERG_ASK_DETECTED")
        desc = "🚨 PREDICTIVE FORESIGHT: Massive hidden distribution (Iceberg Asks) detected. Whales are absorbing heavy buying pressure while pinning the price. A violent drop is highly probable as buyers exhaust."
        return _build_response(signal, confidence, state_desc, risk, desc, flags,
                               imb, flow, sell_spike, large_sell_count, wall_side,
                               delta_accel, refill_ratio, top5_imbalance, spread_pct,
                               bid_depth_change, ask_depth_change, wiseman_climate)
        
    elif macro_divergence == "BULLISH_ABSORPTION":
        signal = "IMMINENT_PUMP_5M"
        confidence = 0.95
        state_desc = "HIDDEN_ACCUMULATION"
        risk = "LOW"
        flags.append("ICEBERG_BID_DETECTED")
        desc = "🚀 PREDICTIVE FORESIGHT: Massive hidden accumulation (Iceberg Bids) detected. Whales are absorbing heavy selling pressure while pinning the price. A violent pump is highly probable as sellers exhaust."
        return _build_response(signal, confidence, state_desc, risk, desc, flags,
                               imb, flow, sell_spike, large_sell_count, wall_side,
                               delta_accel, refill_ratio, top5_imbalance, spread_pct,
                               bid_depth_change, ask_depth_change, wiseman_climate)
    
    # ═══════════════════════════════════════════
    # Phase 2: Whale & Spike Detection (from HTA _check_bailout)
    # ═══════════════════════════════════════════
    
    whale_dump = False
    
    if sell_spike and large_sell_count >= 2:
        # Multiple whales dumping during a sell spike — maximum danger
        signal = "WHALE_DUMP"
        confidence = 0.92
        state_desc = "CAPITULATION"
        risk = "EXTREME"
        whale_dump = True
        flags.append(f"SELL_SPIKE + LARGE_SELLS({large_sell_count})")
    elif sell_spike:
        # Sell spike without confirmed whales — still dangerous
        signal = "SELL_SPIKE"
        confidence = 0.80
        state_desc = "DISTRIBUTION"
        risk = "HIGH"
        flags.append("SELL_SPIKE_5s")
    elif large_sell_count >= 3:
        # Check Whale Intent first
        is_real_exit = True
        if whale_intent and whale_intent.get("direction") == "LONG" and whale_intent.get("delta_30s", 0) > 0:
            if flow.get("delta_5s", 0) > -1000: # Not a massive dump in 5s
                is_real_exit = False
                
        # Check Bid Wall Trap
        bid_ask_ratio = imb.get("avg_ratio", 1.0)
        has_bid_wall = imb.get("wall_side") == "BID"
        
        if bid_ask_ratio > 2.5 and has_bid_wall:
            signal = "INSTITUTIONAL_DISTRIBUTION"
            confidence = 0.88
            state_desc = "DISTRIBUTION"
            risk = "HIGH"
            flags.append(f"BID_WALL_TRAP({bid_ask_ratio:.1f}x)")
        elif is_real_exit:
            signal = "WHALE_EXIT"
            confidence = 0.85
            state_desc = "DISTRIBUTION"
            risk = "HIGH"
            whale_dump = True
            flags.append(f"LARGE_SELLS({large_sell_count})")
        else:
            signal = "SELL_PRESSURE"
            confidence = 0.70
            state_desc = "NORMAL"
            risk = "MEDIUM"
            flags.append("WHALE_INTENT_LONG_OVERRIDE")
    
    # ═══════════════════════════════════════════
    # Phase 3: Depth Collapse Detection (from HTA bailout triggers)
    # ═══════════════════════════════════════════
    
    if bid_depth_change < -40 and not whale_dump:
        signal = "DEPTH_COLLAPSE"
        confidence = 0.88
        state_desc = "LIQUIDITY_VACUUM"
        risk = "EXTREME"
        flags.append(f"BID_DEPTH_COLLAPSE({bid_depth_change:.0f}%)")
    
    # ═══════════════════════════════════════════
    # Phase 4: Spoofing Detection (Pulled Walls)
    # ═══════════════════════════════════════════
    
    spoofing_detected = False
    
    # Depth Collapse without matching market delta = PULLED WALL (Fake support/resistance)
    if bid_depth_change < -30 and delta_30s >= -10000:
        spoofing_detected = True
        flags.append("PULLED_BID_WALL_SPOOF")
    elif ask_depth_change < -30 and delta_30s <= 10000:
        spoofing_detected = True
        flags.append("PULLED_ASK_WALL_SPOOF")
        
    # High bid_vol variance = orders cycling place→cancel→place = faking
    if imb_stability > 0.40 and wall_side is not None:
        spoofing_detected = True
        flags.append(f"STABILITY_SPOOFING(wall={wall_side})")
    
    # Ask refill trap: Market maker distributing into breakout
    if refill_ratio > 2.5:
        flags.append(f"MM_REFILL_TRAP(ratio={refill_ratio:.1f})")
        if signal in ("BUY_PRESSURE", "STRONG_BUY_PRESSURE"):
            # Downgrade buy signals when MM is distributing
            confidence -= 0.20
            risk = "HIGH"
    
    # ═══════════════════════════════════════════
    # Phase 5: Standard Signal Classification (existing logic, enhanced)
    # ═══════════════════════════════════════════
    
    if signal == "NEUTRAL":  # Only if no critical signal was set above
        if state == "PRESSURE":
            if bid_ratio > 2.0 and buy_ratio > 0.6:
                signal = "BUY_ABSORPTION"
                confidence = 0.70
                state_desc = "COUNTER_TREND"
                risk = "HIGH"
            else:
                signal = "SELL_PRESSURE"
                confidence = 0.80
                state_desc = "DISTRIBUTION"
                risk = "HIGH"
        else:
            is_bullish = bid_ratio > 1.8 and buy_ratio > 0.62
            is_strong_bull = bid_ratio > 2.5 and buy_ratio > 0.68
            is_bearish = bid_ratio < 0.55 and buy_ratio < 0.38
            is_strong_bear = bid_ratio < 0.40 and buy_ratio < 0.30
            
            if is_strong_bull:
                signal = "STRONG_BUY_PRESSURE"
                confidence = 0.85
                state_desc = "ACCUMULATION"
                risk = "LOW"
            elif is_bullish:
                signal = "BUY_PRESSURE"
                confidence = 0.65
                state_desc = "ACCUMULATION"
                risk = "MEDIUM"
            elif is_strong_bear:
                signal = "STRONG_SELL_PRESSURE"
                confidence = 0.85
                state_desc = "DISTRIBUTION"
                risk = "LOW"
            elif is_bearish:
                signal = "SELL_PRESSURE"
                confidence = 0.65
                state_desc = "DISTRIBUTION"
                risk = "MEDIUM"
    
    # ═══════════════════════════════════════════
    # Phase 6: Confidence Modifiers (from HTA logic)
    # ═══════════════════════════════════════════
    
    # Spoofing penalty — reduce confidence when book is fake
    if spoofing_detected:
        confidence -= 0.20
        risk = "HIGH"
    
    # Delta acceleration boost — momentum is BUILDING
    if delta_accel > 2.0 and signal != "NEUTRAL":
        confidence += 0.10
        flags.append(f"MOMENTUM_BUILDING(accel={delta_accel:.1f})")
    
    # Delta declining — momentum is FADING
    if delta_declining and "BUY" in signal:
        confidence -= 0.10
        flags.append("MOMENTUM_FADING")
    
    # Ask wall with weak bids — distribution ceiling
    if wall_side == "ASK" and bid_ratio < 0.5:
        flags.append("ASK_WALL_DOMINANT")
        if "BUY" in signal:
            confidence -= 0.15
    
    # Bid wall with strong buying — accumulation floor
    if wall_side == "BID" and buy_ratio > 0.6 and not spoofing_detected:
        flags.append("BID_WALL_SUPPORT")
        if "BUY" in signal:
            confidence += 0.05
    
    # ── Derivatives Confidence Modifiers ──
    
    # Funding Rate: Extreme funding AGAINST the signal = danger
    funding_sig = deriv.get("funding_signal", "NONE")
    if funding_sig == "EXTREME_LONG" and "BUY" in signal:
        confidence -= 0.15
        flags.append("FUNDING_OVERLEVERAGED_LONG")
    elif funding_sig == "EXTREME_SHORT" and "SELL" in signal:
        confidence -= 0.15
        flags.append("FUNDING_OVERLEVERAGED_SHORT")
    elif funding_sig == "EXTREME_LONG" and "SELL" in signal:
        confidence += 0.10  # Selling when market is overleveraged long = smart
        flags.append("FUNDING_SUPPORTS_SELL")
    elif funding_sig == "EXTREME_SHORT" and "BUY" in signal:
        confidence += 0.10  # Buying when market is overleveraged short = smart
        flags.append("FUNDING_SUPPORTS_BUY")
    
    # OI: Rising OI confirms conviction, falling OI = trend exhaustion
    oi_sig = deriv.get("oi_signal", "NONE")
    if oi_sig == "OI_RISING" and signal != "NEUTRAL":
        confidence += 0.05
        flags.append("OI_CONVICTION")
    elif oi_sig == "OI_FALLING" and signal != "NEUTRAL":
        confidence -= 0.05
        flags.append("OI_EXHAUSTION")
    
    # Clamp confidence
    confidence = min(max(confidence, 0.10), 0.99)
    
    # ═══════════════════════════════════════════
    # Phase 7: Description Generation (Explicit Accountability)
    # ═══════════════════════════════════════════
    
    forecast = "RANGING ⚖️"
    if "BUY" in signal or "PUMP" in signal:
        forecast = "UP 🚀"
    elif "SELL" in signal or "DUMP" in signal or "EXIT" in signal or "COLLAPSE" in signal:
        forecast = "DOWN 🩸"
        
    # Constant 30-Second Projection based on Dynamic Flow Physics
    proj_2m = "SIDEWAYS ➖"
    
    # Calculate Institutional Physics Score (Microstructural Toxicity Model - VPIN)
    
    # 0. PRICE MOMENTUM FILTER (The Falling Knife Protection)
    price_change_30s = flow.get("price_change_30s", 0.0)
    current_price = imb.get("best_bid", 1.0) # Avoid div by zero
    price_momentum = (price_change_30s / current_price) * 100
    
    if price_momentum < -0.10:
        macro_trend = "BEARISH_MACRO"
    elif price_momentum > 0.10:
        macro_trend = "BULLISH_MACRO"
    else:
        macro_trend = "NEUTRAL"
        
    # 1. Flow Skew (Informed Trading Aggression)
    # How far from 50/50 is the market taking liquidity? (0.0 to 1.0)
    flow_skew = min(abs(buy_ratio - 0.5) * 2.0, 1.0)
    
    # 2. Velocity Gamma (Momentum Acceleration)
    # How fast is delta accelerating compared to the 30s baseline?
    velocity_gamma = min(delta_accel / 2.0, 1.5)
    
    # 3. Orderbook Vacuum (Limit Resistance/Support)
    # If buying, we want high bid_ratio (support below, vacuum above).
    # If selling, we want low bid_ratio (vacuum below, resistance above).
    is_flow_bullish = buy_ratio > 0.50
    
    if is_flow_bullish:
        book_vacuum = min(bid_ratio / 1.5, 1.2) # Max 1.2x boost
    else:
        book_vacuum = min((1.0 / max(bid_ratio, 0.1)) / 1.5, 1.2)
        
    # 4. Toxicity Probability Score
    # Combines flow aggression, speed, and lack of resistance
    toxicity_prob = (flow_skew * 0.45) + (velocity_gamma * 0.40) + (book_vacuum * 0.15)
    
    # Normalize to percentage
    toxicity_pct = round(min(toxicity_prob, 1.0) * 100)
    vel_str = f"{round(delta_accel, 1)}x"
    
    if macro_divergence == "BULLISH_ABSORPTION":
        proj_2m = f"ICEBERG BIDS 🟢 (Hidden Accumulation | Tox: {toxicity_pct}%)"
    elif macro_divergence == "BEARISH_ABSORPTION":
        proj_2m = f"ICEBERG ASKS 🔴 (Hidden Distribution | Tox: {toxicity_pct}%)"
    elif macro_trend == "BEARISH_MACRO":
        # Prevent TOXIC BUYING during a waterfall crash
        proj_2m = f"WATERFALL DUMP 🔴 (Trend Override | Tox: {toxicity_pct}%)"
    elif macro_trend == "BULLISH_MACRO":
        # Prevent TOXIC SELLING during a vertical rally
        proj_2m = f"VERTICAL PUMP 🟢 (Trend Override | Tox: {toxicity_pct}%)"
    else:
        if toxicity_pct >= 80 and delta_accel >= 2.0:
            if is_flow_bullish:
                proj_2m = f"TOXIC BUYING 🟢 (Toxicity: {toxicity_pct}% | Gamma: {vel_str})"
            else:
                proj_2m = f"TOXIC SELLING 🔴 (Toxicity: {toxicity_pct}% | Gamma: {vel_str})"
        elif toxicity_pct >= 65 and delta_accel >= 1.5:
            if is_flow_bullish:
                proj_2m = f"BUY PRESSURE 🟢 (Toxicity: {toxicity_pct}% | Gamma: {vel_str})"
            else:
                proj_2m = f"SELL PRESSURE 🔴 (Toxicity: {toxicity_pct}% | Gamma: {vel_str})"
        else:
            proj_2m = f"LIQUIDITY ABSORPTION ➖ (Toxicity: {toxicity_pct}% | Gamma: {vel_str})"
             
            
    # ═══════════════════════════════════════════
    # Phase 6.8: Wise Flow Interpreter Override (The Wisdom Layer)
    # ═══════════════════════════════════════════
    try:
        from app.interpreters.wise_flow_interpreter import get_wise_interpreter
        wise_reading = get_wise_interpreter().interpret_pre_entry(symbol)
        
        if wise_reading.verdict.name == "TRAP":
            proj_2m = f"SIDEWAYS ➖ (WISEMAN REJECTED: TRAP | Conf: {wise_reading.confidence*100:.0f}%)"
            signal = "NEUTRAL"
            confidence = 0.50
            forecast = "RANGING ⚖️"
            flags.append("WISEMAN_OVERRIDE(TRAP)")
            # Append safely
            desc = f"⚠️ WISEMAN OVERRIDE: {wise_reading.reason}\n" + locals().get("desc", "")
        elif wise_reading.verdict.name in ["RIDE", "SAFE"]:
            flags.append(f"WISEMAN_APPROVED({wise_reading.verdict.name})")
    except Exception as e:
        import logging
        logging.getLogger("FlowInterpreter").error(f"Wise Flow error: {e}")

    # Append the main verdict text
    desc = locals().get("desc", "") + f"VERDICT: {forecast} | ⏱️ 30-SEC PROJECTION: {proj_2m}\n"
    
    if signal == "WHALE_DUMP":
        desc += f"Whale dump detected: {large_sell_count} large sells during aggressive spike. Expect downward pressure."
    elif signal == "INSTITUTIONAL_DISTRIBUTION":
        desc += f"⚠️ INSTITUTIONAL DISTRIBUTION: Whales are selling into a massive {bid_ask_ratio:.1f}x Bid Wall. Hidden selling pressure detected!"
    elif signal == "WHALE_EXIT":
        desc += f"Institutional exit: {large_sell_count} large sell orders (>$50K each) in last 60s."
    elif signal == "SELL_SPIKE":
        desc += "Sudden sell volume spike. Short-term bearish pressure."
    elif signal == "DEPTH_COLLAPSE":
        desc += f"Bid-side liquidity collapsed {bid_depth_change:.0f}%. Liquidity vacuum forming below."
    elif signal == "STRONG_BUY_PRESSURE":
        desc += "Heavy bidding combined with aggressive buying detected. Favorable conditions for UP movement."
    elif signal == "STRONG_SELL_PRESSURE":
        desc += "Strong selling into a thin limit book. Favorable conditions for DOWN movement."
    elif signal == "BUY_ABSORPTION":
        desc += "Bids absorbing sell pressure during market stress — potential upward reversal."
    elif signal == "BUY_PRESSURE":
        desc += "Steady buying pressure and accumulation detected."
    elif signal == "SELL_PRESSURE":
        desc += "Steady selling pressure and distribution detected."
    else:
        desc += f"Market is in '{state_desc}' phase."
    
    if spoofing_detected:
        desc += f" | ⚠️ WARNING: Spoofing detected! Walls are being pulled to trap liquidity."
    
    if refill_ratio > 2.5:
        desc += " | ⚠️ WARNING: Market maker refilling ask liquidity aggressively — possible distribution trap."
    
    return _build_response(signal, confidence, state_desc, risk, desc, flags,
                           imb, flow, sell_spike, large_sell_count, wall_side,
                           delta_accel, refill_ratio, top5_imbalance, spread_pct,
                           bid_depth_change, ask_depth_change, wiseman_climate)


# ═══════════════════════════════════════════════════════════════
# Strict Schema Derivation — Signal → Action / Direction / Regime
# ═══════════════════════════════════════════════════════════════

def _derive_action(signal: str, risk: str) -> str:
    """Deterministic signal → action mapping.
    
    Converts raw market observations into machine-readable
    recommendations that bots can act on without parsing text.
    """
    _ACTION_MAP = {
        "EMERGENCY_DUMP":             "FULL_EXIT",
        "LIQUIDATION_CASCADE":        "FULL_EXIT",
        "WHALE_DUMP":                 "EXIT_LONG",
        "DEPTH_COLLAPSE":             "BLOCK_LONG",
        "WHALE_EXIT":                 "REDUCE_EXPOSURE",
        "SELL_SPIKE":                 "BLOCK_LONG",
        "INSTITUTIONAL_DISTRIBUTION": "BLOCK_LONG",
        "IMMINENT_DUMP_5M":           "BLOCK_LONG",
        "SHORT_SQUEEZE":              "ENTER_LONG",
        "IMMINENT_PUMP_5M":           "ENTER_LONG",
        "STRONG_BUY_PRESSURE":        "ENTER_LONG",
        "BUY_PRESSURE":               "ENTER_LONG",
        "BUY_ABSORPTION":             "WAIT",
        "STRONG_SELL_PRESSURE":        "ENTER_SHORT",
        "SELL_PRESSURE":               "ENTER_SHORT",
        "NEUTRAL":                     "WAIT",
    }
    action = _ACTION_MAP.get(signal, "WAIT")
    # Safety override: do not recommend entries during extreme risk
    if risk == "EXTREME" and action in ("ENTER_LONG", "ENTER_SHORT"):
        action = "WAIT"
    return action


def _derive_direction_bias(signal: str) -> str:
    """Deterministic signal → direction bias mapping."""
    _BULLISH = {
        "BUY_PRESSURE", "STRONG_BUY_PRESSURE", "BUY_ABSORPTION",
        "SHORT_SQUEEZE", "IMMINENT_PUMP_5M",
    }
    _BEARISH = {
        "SELL_PRESSURE", "STRONG_SELL_PRESSURE", "WHALE_DUMP",
        "WHALE_EXIT", "SELL_SPIKE", "DEPTH_COLLAPSE", "EMERGENCY_DUMP",
        "LIQUIDATION_CASCADE", "INSTITUTIONAL_DISTRIBUTION",
        "IMMINENT_DUMP_5M",
    }
    if signal in _BULLISH:
        return "BULLISH"
    elif signal in _BEARISH:
        return "BEARISH"
    return "NEUTRAL"


def _to_regime(market_state: str, wiseman_climate: dict = None) -> str:
    """Map internal market_state strings to the strict MarketRegime enum."""
    _REGIME_MAP = {
        "LIQUIDITY_EVENT":      "LIQUIDITY_EVENT",
        "LONG_LIQUIDATION":     "LIQUIDITY_EVENT",
        "SHORT_LIQUIDATION":    "LIQUIDITY_EVENT",
        "HIDDEN_DISTRIBUTION":  "VOLATILE",
        "HIDDEN_ACCUMULATION":  "VOLATILE",
        "CAPITULATION":         "LIQUIDITY_EVENT",
        "LIQUIDITY_VACUUM":     "LIQUIDITY_EVENT",
        "DISTRIBUTION":         "RANGING",
        "ACCUMULATION":         "TRENDING",
        "COUNTER_TREND":        "RANGING",
        "RANGE_BOUND":          "RANGING",
        "NORMAL":               "RANGING",
    }
    regime = _REGIME_MAP.get(market_state, "RANGING")
    
    # If WiseMan climate is available, let it override for CHOP/NO_TRADE
    if wiseman_climate:
        wm_mode = wiseman_climate.get("market_mode", "")
        wm_health = wiseman_climate.get("health", "")
        if wm_mode == "CHOP":
            regime = "CHOP"
        elif wm_mode == "NO_TRADE" or wm_health == "FRAGILE":
            regime = "NO_TRADE"
        elif wm_mode == "TREND" and regime not in ("LIQUIDITY_EVENT",):
            regime = "TRENDING"
    
    return regime


import re

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U00002600-\U000026FF"  # misc symbols
    "\U0000200D"             # zero width joiner
    "\U00002B50-\U00002B55"  # stars
    "\U0000231A-\U0000231B"  # watch
    "\U000023E9-\U000023F3"  # timer
    "\U000025AA-\U000025AB"  # squares
    "\U000025B6"             # play
    "\U000025FB-\U000025FE"  # squares
    "\U00002934-\U00002935"  # arrows
    "\U00002B05-\U00002B07"  # arrows
    "\U00003030"             # wavy dash
    "\U00003297"             # circled ideograph
    "\U00003299"             # circled ideograph
    "]+", flags=re.UNICODE
)


def _strip_emojis(text: str) -> str:
    """Remove all emoji characters from text."""
    return _EMOJI_RE.sub("", text).strip()


def _extract_explanation(desc: str) -> str:
    """Extract a clean one-liner from the verbose description text.
    
    Priority: non-VERDICT lines (actual explanation) > fallback to VERDICT content.
    All emojis are stripped for clean machine output.
    """
    if not desc:
        return ""
    
    _NOISE_PREFIXES = ["⚠️ WISEMAN OVERRIDE: ", "🔥 ", "🚀 ", "🚨 ", "VERDICT: "]
    
    lines = desc.strip().split("\n")
    
    # Find lines that are NOT VERDICT headers
    candidate_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("VERDICT:"):
            continue
        candidate_lines.append(stripped)
    
    if candidate_lines:
        # Prefer the last candidate (usually the most specific explanation)
        best = candidate_lines[-1]
    else:
        # All lines are VERDICT — extract from the VERDICT itself
        best = lines[0].strip()
    
    # Clean noise prefixes
    for prefix in _NOISE_PREFIXES:
        if best.startswith(prefix):
            best = best[len(prefix):]
    
    # Strip emojis for clean machine output
    return _strip_emojis(best).strip()


def _build_response(signal, confidence, state_desc, risk, desc, flags,
                    imb, flow, sell_spike, large_sell_count, wall_side,
                    delta_accel, refill_ratio, top5_imbalance, spread_pct,
                    bid_depth_change, ask_depth_change, wiseman_climate=None):
    """Build the final response dictionary with full metrics payload."""
    
    # Derive strict schema fields
    action = _derive_action(signal, risk)
    direction_bias = _derive_direction_bias(signal)
    market_regime = _to_regime(state_desc, wiseman_climate)
    explanation = _extract_explanation(desc)
    
    # Issue #5: Detect wiseman stale during whale events
    whale_active = large_sell_count >= 2
    wm_mode = (wiseman_climate or {}).get("market_mode", "UNKNOWN")
    wm_health = (wiseman_climate or {}).get("health", "UNKNOWN")
    if whale_active and wm_health in ("HEALTHY", "UNKNOWN") and wm_mode not in ("CHOP", "NO_TRADE"):
        flags = list(flags) if flags else []
        if "WISEMAN_STALE_DURING_EVENT" not in flags:
            flags.append("WISEMAN_STALE_DURING_EVENT")
    
    return {
        # === Strict Schema (machine-parseable) ===
        "signal": signal,
        "action": action,
        "direction_bias": direction_bias,
        "confidence": round(confidence, 2),
        "risk": risk,
        "market_regime": market_regime,
        "explanation": explanation,
        
        # === Backward Compatible ===
        "market_state": state_desc,
        "description": desc,
        "metrics": {
            # Core ratios (existing)
            "bid_ask_ratio": round(imb.get("ratio", 1.0), 3),
            "buy_sell_ratio": round(flow.get("buy_ratio", 0.5), 3),
            "delta_5s": round(flow.get("delta_5s", 0), 3),
            "delta_30s": round(flow.get("delta_30s", 0), 3),
            "delta_5m": round(flow.get("delta_5m", 0), 3),
            "imbalance_stability": round(imb.get("imb_stability", 0.0), 3),
            "macro_divergence": flow.get("macro_divergence", "NONE"),
            # Whale & Spike Intelligence
            "whale_activity": large_sell_count >= 2,
            "large_sell_count": large_sell_count,
            "sell_spike": sell_spike,
            # Momentum Physics
            "delta_accel": round(delta_accel, 2),
            # Orderbook Microstructure
            "wall_side": wall_side,
            "top5_imbalance": round(top5_imbalance, 4),
            "spread_pct": round(spread_pct, 4),
            "refill_ratio": round(refill_ratio, 2),
            # Depth Dynamics
            "bid_depth_change_pct": round(bid_depth_change, 1),
            "ask_depth_change_pct": round(ask_depth_change, 1),
            # Global Macros
            "wiseman_climate": wiseman_climate or {"market_mode": "UNKNOWN", "health": "UNKNOWN", "confidence": 0},
            # Event Flags
            "flags": flags,
        }
    }
