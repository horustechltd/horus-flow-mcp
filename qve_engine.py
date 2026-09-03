"""
HORUS Quant Validation Engine (QVE) - Phase 3
Institutional Evidence Court & Truth Dashboard (Statistical Honesty)
"""

import os
import time
import json
import uuid
import asyncio
import aiohttp
from datetime import datetime
from pathlib import Path

from qve_database import qve_db

# ══════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "7649770299:AAEW3nO-ko1a63tQZSzreNF7RpjYjInRCi4")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1245603051")
API_KEY = "horus-demo-key-2026"
BASE_URL = "http://127.0.0.1:8011"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Execution Simulation Parameters
FEES_PCT = 0.08 / 100.0
SLIPPAGE_PCT = 0.03 / 100.0
DEFAULT_TP_PCT = 1.5 / 100.0  # Fallback if ATR unavailable
DEFAULT_SL_PCT = 0.5 / 100.0  # Fallback if ATR unavailable
MIN_EDGE_MOVE = 0.25 / 100.0

# ATR-based Risk Parameters
ATR_PERIOD = 14  # 14-candle ATR on 1m klines
ATR_SL_MULT = 1.0  # SL = 1.0 × ATR
ATR_TP_MULT = 3.0  # TP = 3.0 × ATR (3:1 R:R)

# 1R = Risk (Stop Loss) — dynamically recalculated per trade via ATR
R_UNIT = DEFAULT_SL_PCT  # Fallback, overridden per-decision

# Regime-based Dynamic Entry Thresholds
# ──────────────────────────────────────────────────────────
REGIME_THRESHOLDS = {
    "TREND": 55,
    "RANGING": 60,
    "LIQUIDITY_EVENT": 58,
    "CHOP": 75,
    "VOLATILE": 65,
    "PANIC": 75,
    "UNKNOWN": 65,
    "NO_TRADE": 80,
}

DATA_DIR = Path("/root/horus_flow_api/calibration_data")
RAW_DIR = DATA_DIR / "raw_snapshots"

# ══════════════════════════════════════════════
# Hybrid Sequence System
# ══════════════════════════════════════════════
CANONICAL_SEQUENCES = {
    ("INSTITUTIONAL_DISTRIBUTION", "WHALE_EXIT", "EMERGENCY_DUMP"): "CASCADE_DUMP",
    ("CAPITULATION", "BUY_ABSORPTION", "STRONG_BUY_PRESSURE"): "V_RECOVERY",
    ("LIQUIDITY_VACUUM", "SPOOFING", "TRAP"): "FAKE_BREAKOUT",
    ("WHALE_ACCUMULATION", "BUY_PRESSURE", "EMERGENCY_PUMP"): "IMPULSE_PUMP"
}

class QVEEngine:
    def __init__(self):
        self.active_decisions = {}
        self.last_regime = {sym: "UNKNOWN" for sym in SYMBOLS}
        self.regime_start_ts = {sym: time.time() for sym in SYMBOLS}
        self.session = None
        self.milestones_fired = set()  # Track which milestone alerts have been sent
        self.eval_count = 0
        self.attack_cooldown = {}  # {symbol: (direction, ts)} — prevent duplicate alerts
        self.atr_cache = {}  # {symbol: (atr_value, atr_ts)} — cached ATR per symbol

    def compute_atr(self, klines: list) -> float:
        """Compute ATR (Average True Range) from klines as a percentage of price."""
        if len(klines) < 2:
            return 0.0
        trs = []
        for i in range(1, len(klines)):
            h = klines[i]['high']
            l = klines[i]['low']
            prev_c = klines[i-1]['close']
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        if not trs:
            return 0.0
        atr = sum(trs) / len(trs)
        # Return as percentage of latest close
        last_close = klines[-1]['close']
        return atr / last_close if last_close > 0 else 0.0

    async def start(self):
        print("=" * 60)
        print("  HORUS QVE — Phase 3 (Truth Dashboard)")
        print("  Ruthless Statistical Honesty Edition")
        print("=" * 60)
        
        self.session = aiohttp.ClientSession()
        
        # Start background tasks
        asyncio.create_task(self.poll_signals_loop())
        asyncio.create_task(self.poll_klines_loop())
        asyncio.create_task(self.evaluate_decisions_loop())
        asyncio.create_task(self.daily_report_loop())
        
        # Keep engine alive
        while True:
            await asyncio.sleep(3600)

    # ══════════════════════════════════════════════
    # Data Ingestion
    # ══════════════════════════════════════════════
    async def poll_signals_loop(self):
        while True:
            try:
                async with self.session.get(f"{BASE_URL}/v1/intelligence/market-intelligence", params={"key": API_KEY}, timeout=10) as r:
                    if r.status == 200:
                        data = await r.json()
                        await self.process_market_intelligence(data)
            except Exception as e:
                print(f"[QVE Signals Error] {e}")
            await asyncio.sleep(10)

    async def poll_klines_loop(self):
        """Fetch 1m klines for accurate H/L/C tracking"""
        while True:
            for symbol in SYMBOLS:
                try:
                    async with self.session.get(BINANCE_KLINES_URL, params={"symbol": symbol, "interval": "1m", "limit": 5}, timeout=5) as r:
                        if r.status == 200:
                            klines = await r.json()
                            for k in klines:
                                ts = float(k[0]) / 1000.0
                                o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
                                await qve_db.insert_candle(symbol, "1m", ts, o, h, l, c, v)
                except Exception as e:
                    pass
            await asyncio.sleep(60)

    async def process_market_intelligence(self, data: dict):
        now = time.time()
        
        # 1. Archive Raw JSON Forensics
        date_str = datetime.now().strftime("%Y-%m-%d")
        raw_file = RAW_DIR / f"snapshots_{date_str}.jsonl"
        with open(raw_file, "a") as f:
            f.write(json.dumps({"ts": now, "data": data}) + "\n")
            
        # 2. Extract structured signal for SQLite
        symbols_data = data.get("symbols", {})
        for symbol, sym_data in symbols_data.items():
            composite = sym_data.get("composite", {})
            heatmap = sym_data.get("heatmap", {})
            
            score = composite.get("composite_score", 0)
            verdict = composite.get("verdict", "")
            direction_raw = composite.get("direction", "NEUTRAL")
            
            # ══════════════════════════════════════════════
            # DERIVED FIELDS — Raw Redis data does NOT contain action,
            # confidence, or direction_bias. We must derive them here
            # using the same logic as the /composite API endpoint.
            # Without this, action always defaults to "WAIT" and
            # GOOD_ENTRY is structurally impossible.
            # ══════════════════════════════════════════════
            
            # Regime Attribution Engine & Transitions (computed FIRST for threshold)
            regime = self.determine_regime(sym_data)
            regime_threshold = REGIME_THRESHOLDS.get(regime, 65)
            
            # Derive action from verdict + direction (mirrors /composite endpoint logic)
            if verdict == "FULL_CONVICTION":
                action = f"ENTER_{'LONG' if direction_raw == 'LONG' else 'SHORT'}"
            elif verdict == "PARTIAL_CONVICTION":
                action = f"ENTER_{'LONG' if direction_raw == 'LONG' else 'SHORT'}"
            elif verdict == "STAY_OUT":
                action = "WAIT"
            else:
                action = "WAIT"
            
            # Dynamic regime-aware threshold override
            if score < regime_threshold and action.startswith("ENTER"):
                action = "WAIT"

            # ══════════════════════════════════════════════
            # OFFENSIVE DIRECTIONAL BIAS GATE v2 (2026-05-19)
            # ──────────────────────────────────────────────
            # First gate (v1, 2026-05-18) failed: 19 SHORTs / 0 LONGs / -80R
            # in 24h because the gate accepted SHORT in TREND/HEALTHY whenever
            # gravity score was 0.5+. But TREND/HEALTHY is precisely the
            # uptrend regime — taking SHORT there is fighting the dominant
            # macro flow, regardless of micro liquidation pressure.
            #
            # v2 hard rules:
            #   1. In TREND/HEALTHY → SHORT requires score >= 75 (very rare).
            #      This is the dominant regime and SHORTing it is the bias.
            #   2. In TREND/DECAYING or RANGE/HEALTHY → SHORT requires
            #      score >= 70 OR clearly bearish gravity (DOWN, score >= 0.6).
            #   3. In CHOP / NO_TRADE / FRAGILE / PANIC → SHORT allowed at
            #      regime threshold (these are not uptrend regimes).
            #   4. LONG is left unrestricted; the audit shows LONG side is
            #      profitable and the asymmetry is on SHORT.
            #
            # If 7 days of data show <30% BAD_ENTRY rate on SHORT, gate can
            # be relaxed. If LONG also degrades, widen this symmetrically.
            # ══════════════════════════════════════════════
            if action == "ENTER_SHORT":
                # Pull macro climate context
                details = composite.get("details", {})
                climate_str = details.get("climate", "")
                wiseman_mode = ""
                wiseman_health = ""
                if "/" in climate_str:
                    parts = climate_str.split("/")
                    wiseman_mode = parts[0].strip()
                    if len(parts) > 1:
                        wiseman_health = parts[1].split("(")[0].strip()

                # Pull liquidation gravity
                gravity = heatmap.get("gravity_direction", "")
                gravity_score_val = heatmap.get("gravity_score", 0.0) or 0.0

                # Determine if we are in an uptrend-like regime
                is_strong_uptrend = (wiseman_mode == "TREND" and wiseman_health == "HEALTHY")
                is_mild_uptrend = (
                    (wiseman_mode == "TREND" and wiseman_health == "DECAYING")
                    or (wiseman_mode == "RANGE" and wiseman_health == "HEALTHY")
                )

                allow_short = False
                block_reason = ""

                if is_strong_uptrend:
                    # Hard gate: in TREND/HEALTHY, SHORT only at score >= 75
                    if score >= 75:
                        allow_short = True
                    else:
                        block_reason = f"TREND/HEALTHY requires score>=75 (got {score:.1f})"
                elif is_mild_uptrend:
                    # Mid gate: score >= 70 OR clearly bearish gravity
                    bearish_gravity = (gravity == "DOWN" and gravity_score_val >= 0.6)
                    if score >= 70 or bearish_gravity:
                        allow_short = True
                    else:
                        block_reason = (
                            f"{wiseman_mode}/{wiseman_health} requires score>=70 or "
                            f"gravity DOWN>=0.6 (got score={score:.1f}, "
                            f"gravity={gravity}({gravity_score_val:.2f}))"
                        )
                else:
                    # CHOP / NO_TRADE / FRAGILE / PANIC / unknown — pass through
                    allow_short = True

                if not allow_short:
                    print(
                        f"[QVE] 🛡️ SHORT BLOCKED v2 on {symbol}: {block_reason} "
                        f"— refusing to fight the trend"
                    )
                    action = "WAIT"
            
            # Derive confidence from score (same as /composite endpoint: score/100)
            confidence = round(score / 100.0, 2)
            
            # Derive direction for QVE (normalize LONG/SHORT/NEUTRAL)
            direction = "LONG" if direction_raw in ("UP", "LONG") else \
                        "SHORT" if direction_raw in ("DOWN", "SHORT") else "NEUTRAL"
            
            # Derive risk from score (same tiers as /composite endpoint)
            if score >= 80:
                risk = "LOW"
            elif score >= 60:
                risk = "MEDIUM"
            elif score >= 40:
                risk = "HIGH"
            else:
                risk = "EXTREME"
            
            # Regime Transitions (regime already computed above for threshold)
            regime_transition = f"{self.last_regime[symbol]} -> {regime}"
            
            if self.last_regime[symbol] != regime and self.last_regime[symbol] != "UNKNOWN":
                print(f"[REGIME] 🔄 Transition Detected: {symbol} {regime_transition}")
                self.regime_start_ts[symbol] = now
            self.last_regime[symbol] = regime
            
            regime_duration = now - self.regime_start_ts[symbol]
            
            sig_uuid = str(uuid.uuid4())
            signal_id = await qve_db.insert_signal({
                "ts": now,
                "symbol": symbol,
                "signal_type": verdict,
                "action": action,
                "direction": direction,
                "confidence": confidence,
                "risk": risk,
                "market_state": sym_data.get("xflow", {}).get("market_type", "UNKNOWN"),
                "market_regime": regime,
                "composite_score": score,
                "uuid": sig_uuid
            })
            
            # Log non-WAIT actions for visibility + instant Telegram alert (session cooldown)
            if action != "WAIT":
                print(f"[QVE] 🎯 {symbol} ACTION={action} | Dir={direction} | Score={score} | Conf={confidence} | Verdict={verdict} | Regime={regime}")
                # 🚨 INSTANT ENTRY ALERT — one alert per attack session
                # Only send if this is a NEW attack (previous action was WAIT or different direction) or >30m passed
                last_attack_dir, last_attack_ts = self.attack_cooldown.get(symbol, (None, 0))
                if last_attack_dir != direction or (now - last_attack_ts >= 1800):
                    self.attack_cooldown[symbol] = (direction, now)
                    entry_price = heatmap.get("current_price", 0)
                    alert_msg = f"🎯 QVE ATTACK SIGNAL\n"
                    alert_msg += f"━━━━━━━━━━━━━━━\n"
                    alert_msg += f"Symbol: {symbol}\n"
                    alert_msg += f"Action: {action}\n"
                    alert_msg += f"Direction: {direction}\n"
                    alert_msg += f"Score: {score} | Confidence: {confidence}\n"
                    alert_msg += f"Verdict: {verdict}\n"
                    alert_msg += f"Regime: {regime}\n"
                    alert_msg += f"Entry Price: ${entry_price:,.2f}\n"
                    alert_msg += f"━━━━━━━━━━━━━━━\n"
                    alert_msg += f"Awaiting TP/SL outcome...\n"
                    await self.send_telegram(alert_msg)
                else:
                    print(f"[QVE] ⏳ Attack alert suppressed for {symbol} (same session, dir={direction})")
            else:
                # Reset cooldown when action returns to WAIT
                if symbol in self.attack_cooldown:
                    del self.attack_cooldown[symbol]
            
            # Sequence Forensics
            await self.check_sequences(symbol)
            
            # Register a decision to evaluate:
            # - All non-WAIT actions (actual entries to track)
            # - High-conviction WAIT signals (score >= 55) for counterfactual analysis
            # - Low-score WAITs are sampled (1 per symbol at a time) for baseline tracking
            is_attack = action != "WAIT"
            should_register = is_attack or score >= 55 or symbol not in self.active_decisions
            slot_available = symbol not in self.active_decisions
            
            if should_register:
                # For attacks: only register if this is the FIRST entry of the session
                if is_attack:
                    existing = self.active_decisions.get(symbol)
                    if existing and existing.get('action') != 'WAIT' and existing.get('direction') == direction:
                        slot_available = False # Already tracking this attack session
                        # print(f"[QVE] ⚔️ Attack session already tracked for {symbol}, skipping overwrite")
                    else:
                        if existing:
                            print(f"[QVE] ⚔️ ATTACK overrides existing WAIT decision for {symbol}")
                        slot_available = True  # Force open the slot for new attack
                
                if slot_available:
                    entry_price = heatmap.get("current_price", 0)
                    if entry_price > 0:
                        # Compute ATR-based TP/SL for this decision
                        atr_klines = await qve_db.get_recent_klines(symbol, "1m", now, limit=ATR_PERIOD + 1)
                        atr_pct = self.compute_atr(atr_klines)
                        if atr_pct > 0:
                            tp_pct = atr_pct * ATR_TP_MULT
                            sl_pct = atr_pct * ATR_SL_MULT
                            r_unit = sl_pct
                        else:
                            tp_pct = DEFAULT_TP_PCT
                            sl_pct = DEFAULT_SL_PCT
                            r_unit = R_UNIT
                        
                        self.active_decisions[symbol] = {
                            "signal_id": signal_id,
                            "symbol": symbol,
                            "action": action,
                            "direction": direction,
                            "entry_price": entry_price,
                            "entry_ts": now,
                            "regime": regime,
                            "regime_transition": regime_transition,
                            "regime_duration": regime_duration,
                            "score": score,
                            "is_realized": 1 if is_attack else 0,
                            "tp_pct": tp_pct,
                            "sl_pct": sl_pct,
                            "r_unit": r_unit,
                            "atr_pct": atr_pct,
                        }
                        if is_attack:
                            print(f"[QVE] 📊 ATR={atr_pct*100:.3f}% | SL={sl_pct*100:.3f}% | TP={tp_pct*100:.3f}% | R:R=1:{ATR_TP_MULT:.0f}")

    # ══════════════════════════════════════════════
    # Regime Attribution Engine
    # ══════════════════════════════════════════════
    def determine_regime(self, sym_data: dict) -> str:
        """Categorize current market into TREND, CHOP, PANIC, DISTRIBUTION, LIQUIDITY_EVENT, VOLATILE"""
        # XFlow extreme conditions override everything
        xflow = sym_data.get("xflow", {})
        positioning = xflow.get("positioning_signal", "")
        if "MASS_DELEVERAGING" in positioning:
            return "PANIC"
        
        market_type = xflow.get("market_type", "")
        if market_type == "HYPER_SPECULATION":
            return "LIQUIDITY_EVENT"
        
        # Extract WiseMan market_mode from composite.details.climate
        # Format: "CHOP/HEALTHY(conf=55%)" or "TREND/DECAYING(conf=70%)" etc.
        composite = sym_data.get("composite", {})
        details = composite.get("details", {})
        climate_str = details.get("climate", "")
        
        wiseman_mode = ""
        if "/" in climate_str:
            wiseman_mode = climate_str.split("/")[0].strip()
        
        if wiseman_mode == "TREND":
            return "TREND"
        if wiseman_mode == "RANGE":
            return "RANGING"
        if wiseman_mode == "CHOP":
            return "CHOP"
        if wiseman_mode == "NO_TRADE":
            return "NO_TRADE"
        if wiseman_mode == "VOLATILE":
            return "VOLATILE"
            
        return "UNKNOWN"

    # ══════════════════════════════════════════════
    # Sequence Forensics (Hybrid)
    # ══════════════════════════════════════════════
    async def check_sequences(self, symbol: str):
        recent = await qve_db.get_recent_signals(symbol, limit=3)
        if len(recent) < 3: return
            
        recent = recent[::-1]
        events = tuple([r['signal_type'] for r in recent])
        
        if events in CANONICAL_SEQUENCES:
            seq_name = CANONICAL_SEQUENCES[events]
            await qve_db.insert_sequence({
                "symbol": symbol,
                "sequence_type": "CANONICAL",
                "sequence_name": seq_name,
                "events": list(events),
                "start_ts": recent[0]['ts'],
                "end_ts": recent[-1]['ts'],
                "outcome": "PENDING",
                "expectancy": 0.0
            })
            print(f"[FORENSICS] 🚨 Canonical Sequence: {seq_name} on {symbol}")

    # ══════════════════════════════════════════════
    # Decision Evaluation Matrix (MFE/MAE via Klines)
    # ══════════════════════════════════════════════
    async def evaluate_decisions_loop(self):
        while True:
            resolved = []
            for symbol, dec in self.active_decisions.items():
                age = time.time() - dec['entry_ts']
                if age < 300:
                    continue
                    
                klines = await qve_db.get_klines_since(symbol, "1m", dec['entry_ts'])
                if not klines:
                    continue
                    
                entry_p = dec['entry_price']
                direction = dec['direction']
                action = dec['action']
                
                # Dynamic ATR-based TP/SL prices (with fallback for old entries)
                tp_pct = dec.get('tp_pct', DEFAULT_TP_PCT)
                sl_pct = dec.get('sl_pct', DEFAULT_SL_PCT)
                
                # ══════════════════════════════════════════════
                # FIX (counterfactual realism): enforce minimum meaningful
                # TP and SL distances. In LIQUIDITY_EVENT regimes, ATR on
                # 1m candles can shrink to 0.02%, making TP = 0.06%. That
                # is market noise — price taps TP then fully reverses,
                # producing false MISSED_OPPORTUNITY verdicts. We clamp to
                # a minimum that represents an actually tradable edge.
                # ══════════════════════════════════════════════
                MIN_TP_PCT = 0.004   # 0.4% minimum take-profit distance
                MIN_SL_PCT = 0.0015  # 0.15% minimum stop-loss (protects r_unit)
                tp_pct = max(tp_pct, MIN_TP_PCT)
                sl_pct = max(sl_pct, MIN_SL_PCT)
                
                tp_price_up = entry_p * (1 + tp_pct)
                sl_price_up = entry_p * (1 - sl_pct)
                tp_price_dn = entry_p * (1 - tp_pct)
                sl_price_dn = entry_p * (1 + sl_pct)
                
                max_fav = 0.0
                max_adv = 0.0
                exit_p = 0.0
                exit_ts = 0.0
                
                # Counterfactual outcomes
                cf_long_result = "PENDING"
                cf_short_result = "PENDING"
                cf_max_fav_up = 0.0
                cf_max_fav_dn = 0.0
                
                hit_tp = False
                hit_sl = False
                
                for k in klines:
                    h, l, c, ts = k['high'], k['low'], k['close'], k['ts']
                    
                    fav_up = (h - entry_p) / entry_p
                    fav_dn = (entry_p - l) / entry_p
                    
                    if fav_up > cf_max_fav_up: cf_max_fav_up = fav_up
                    if fav_dn > cf_max_fav_dn: cf_max_fav_dn = fav_dn
                    
                    # Track Counterfactual Long
                    if cf_long_result == "PENDING":
                        if l <= sl_price_up: cf_long_result = "SL"
                        elif h >= tp_price_up: cf_long_result = "TP"
                    
                    # Track Counterfactual Short
                    if cf_short_result == "PENDING":
                        if h >= sl_price_dn: cf_short_result = "SL"
                        elif l <= tp_price_dn: cf_short_result = "TP"
                    
                    # Track actual direction (LONG/SHORT from composite)
                    if action != "WAIT":
                        if direction in ("UP", "LONG") and not hit_tp and not hit_sl:
                            if fav_up > max_fav: max_fav = fav_up
                            adv = (l - entry_p) / entry_p
                            if adv < max_adv: max_adv = adv
                            
                            if l <= sl_price_up:
                                hit_sl = True
                                exit_p = sl_price_up
                                exit_ts = ts
                            elif h >= tp_price_up:
                                hit_tp = True
                                exit_p = tp_price_up
                                exit_ts = ts
                                
                        elif direction in ("DOWN", "SHORT") and not hit_tp and not hit_sl:
                            if fav_dn > max_fav: max_fav = fav_dn
                            adv = (entry_p - h) / entry_p
                            if adv < max_adv: max_adv = adv
                            
                            if h >= sl_price_dn:
                                hit_sl = True
                                exit_p = sl_price_dn
                                exit_ts = ts
                            elif l <= tp_price_dn:
                                hit_tp = True
                                exit_p = tp_price_dn
                                exit_ts = ts
                            
                result_matrix = "PENDING"
                cf_long_r = 0.0
                cf_short_r = 0.0
                opp_cost_r = 0.0
                is_realized = 1 if action != "WAIT" else 0
                
                # 1. Evaluate WAIT Actions (Counterfactual Evaluation)
                if action == "WAIT":
                    if age >= 3600:
                        # ══════════════════════════════════════════════
                        # FIX #1 (directional sanity): a counterfactual TP
                        # is only credible if the final close agrees with
                        # the direction. If LONG "TP" was tagged but price
                        # closed BELOW entry, the TP was a spike followed
                        # by full reversal — not a real edge. Demote to
                        # NEUTRAL so it is not counted as +3R.
                        # ══════════════════════════════════════════════
                        final_close = klines[-1]['close']
                        net_move_pct = (final_close - entry_p) / entry_p  # + = up, - = down

                        # Long CF: require both TP touched AND net move positive
                        if cf_long_result == "SL":
                            cf_long_r = -1.0
                        elif cf_long_result == "TP" and net_move_pct > 0:
                            cf_long_r = 3.0
                        else:
                            cf_long_r = 0.0  # TP-then-reverse or no move

                        # Short CF: require both TP touched AND net move negative
                        if cf_short_result == "SL":
                            cf_short_r = -1.0
                        elif cf_short_result == "TP" and net_move_pct < 0:
                            cf_short_r = 3.0
                        else:
                            cf_short_r = 0.0

                        # ══════════════════════════════════════════════
                        # FIX #2 (opportunity cost floor): r_unit is derived
                        # from ATR and can be microscopic in quiet sessions,
                        # which inflates opportunity_cost_r to absurd values
                        # (20R+ on a 0.4% move). Floor r_unit to a realistic
                        # per-trade risk (0.15%) to keep R-math meaningful.
                        # ══════════════════════════════════════════════
                        raw_r_unit = dec.get('r_unit', R_UNIT)
                        r_unit = max(raw_r_unit, 0.0015)  # at least 0.15%
                        max_cf_fav_pct = max(cf_max_fav_up, cf_max_fav_dn)
                        opp_cost_r = round(max_cf_fav_pct / r_unit, 2)
                        
                        if cf_long_r <= 0 and cf_short_r <= 0:
                            result_matrix = "GOOD_AVOIDANCE"
                        elif cf_long_r > 0 or cf_short_r > 0:
                            result_matrix = "MISSED_OPPORTUNITY"
                        else:
                            result_matrix = "NEUTRAL_AVOIDANCE"
                            
                        exit_p = klines[-1]['close']
                        exit_ts = klines[-1]['ts']
                        
                        # ══════════════════════════════════════════════
                        # FIX #3 (price-movement telemetry): record max
                        # favorable & adverse excursions even for WAIT
                        # decisions so dashboards/reports can show how
                        # much price actually moved during the window.
                        # Use the dominant direction of the net move.
                        # ══════════════════════════════════════════════
                        wait_max_fav = cf_max_fav_up if net_move_pct >= 0 else cf_max_fav_dn
                        wait_max_adv = cf_max_fav_dn if net_move_pct >= 0 else cf_max_fav_up
                        wait_max_adv = -wait_max_adv  # adverse is stored as negative
                        
                        resolved.append((symbol, dec, result_matrix, wait_max_fav, wait_max_adv, exit_p, exit_ts, cf_long_r, cf_short_r, opp_cost_r, is_realized))
                
                # 2. Evaluate Executions
                elif hit_tp:
                    result_matrix = "GOOD_ENTRY"
                    resolved.append((symbol, dec, result_matrix, max_fav, max_adv, exit_p, exit_ts, 0.0, 0.0, 0.0, is_realized))
                elif hit_sl:
                    result_matrix = "BAD_ENTRY"
                    resolved.append((symbol, dec, result_matrix, max_fav, max_adv, exit_p, exit_ts, 0.0, 0.0, 0.0, is_realized))
                elif age >= 14400: # 4 hour timeout
                    result_matrix = "NO_EDGE"
                    exit_p = klines[-1]['close']
                    exit_ts = klines[-1]['ts']
                    resolved.append((symbol, dec, result_matrix, max_fav, max_adv, exit_p, exit_ts, 0.0, 0.0, 0.0, is_realized))
            
            # Process resolved
            for sym, dec, res, mf, ma, xp, xts, cfl_r, cfs_r, opp_cost_r, is_realized in resolved:
                pnl_pct = 0.0
                if dec['action'] != "WAIT":
                    if dec['direction'] in ("UP", "LONG"):
                        pnl_pct = (xp - dec['entry_price']) / dec['entry_price']
                    else:
                        pnl_pct = (dec['entry_price'] - xp) / dec['entry_price']
                    pnl_pct = pnl_pct - FEES_PCT - SLIPPAGE_PCT
                    
                r_unit = dec.get('r_unit', R_UNIT)
                expectancy_r = round(pnl_pct / r_unit, 2) if is_realized else 0.0
                time_to_outcome = xts - dec['entry_ts']

                await qve_db.insert_decision_evaluation({
                    "signal_id": dec['signal_id'],
                    "symbol": sym,
                    "entry_price": dec['entry_price'],
                    "entry_ts": dec['entry_ts'],
                    "exit_price": xp,
                    "exit_ts": xts,
                    "max_favorable": mf,
                    "max_adverse": ma,
                    "pnl_pct": pnl_pct,
                    "fees_pct": FEES_PCT,
                    "slippage_pct": SLIPPAGE_PCT,
                    "result_matrix": res,
                    "expectancy": pnl_pct,
                    "expectancy_r": expectancy_r,
                    "time_to_outcome": time_to_outcome,
                    "counterfactual_long_r": cfl_r,
                    "counterfactual_short_r": cfs_r,
                    "opportunity_cost_r": opp_cost_r,
                    "is_realized": is_realized,
                    "market_regime": dec['regime'],
                    "regime_transition": dec['regime_transition'],
                    "regime_duration": dec['regime_duration']
                })
                
                self.eval_count += 1
                print(f"[QVE Court] ⚖️ [{self.eval_count}] Evaluated {sym}: {dec['action']} -> {res} (Exp: {expectancy_r:+.2f}R | TTO: {time_to_outcome/60:.1f}m)")
                
                # 🚨 Milestone Alerts
                await self._check_milestone_alert(sym, dec, res, expectancy_r, cfl_r, cfs_r, opp_cost_r)
                
                del self.active_decisions[sym]
                
            await asyncio.sleep(30)

    # ══════════════════════════════════════════════
    # Milestone Alert System
    # ══════════════════════════════════════════════
    async def _check_milestone_alert(self, symbol, dec, result, expectancy_r, cfl_r, cfs_r, opp_cost_r):
        """Send instant Telegram alerts for critical milestones"""
        
        # 🏆 FIRST GOOD_ENTRY — the most awaited milestone
        if result == "GOOD_ENTRY" and "first_good_entry" not in self.milestones_fired:
            self.milestones_fired.add("first_good_entry")
            msg = "🏆🏆🏆 MILESTONE: FIRST GOOD ENTRY! 🏆🏆🏆\n"
            msg += "━━━━━━━━━━━━━━━\n"
            msg += f"Symbol: {symbol}\n"
            msg += f"Direction: {dec['direction']}\n"
            msg += f"Score: {dec['score']}\n"
            msg += f"Expectancy: {expectancy_r:+.2f}R\n"
            msg += f"Regime: {dec['regime']}\n"
            msg += f"Entry: ${dec['entry_price']:.2f}\n"
            msg += "━━━━━━━━━━━━━━━\n"
            msg += "HORUS has proven it can ATTACK.\n"
            await self.send_telegram(msg)
        
        # ⚔️ Every GOOD_ENTRY after the first
        elif result == "GOOD_ENTRY":
            msg = f"⚔️ GOOD ENTRY — {symbol}\n"
            msg += f"Direction: {dec['direction']} | Exp: {expectancy_r:+.2f}R\n"
            msg += f"Score: {dec['score']} | Regime: {dec['regime']}\n"
            await self.send_telegram(msg)
        
        # ❌ BAD_ENTRY — always report
        elif result == "BAD_ENTRY":
            msg = f"❌ BAD ENTRY — {symbol}\n"
            msg += f"Direction: {dec['direction']} | Exp: {expectancy_r:+.2f}R\n"
            msg += f"Score: {dec['score']} | Regime: {dec['regime']}\n"
            await self.send_telegram(msg)
        
        # 🚨 Large MISSED_OPPORTUNITY (> 3R) - logged internally without Telegram spam
        elif result == "MISSED_OPPORTUNITY" and opp_cost_r >= 3.0:
            logger.info(f"🚨 LARGE MISSED OPPORTUNITY — {symbol} (Cost: {opp_cost_r:.2f}R | CF Long: {cfl_r:+.1f}R | CF Short: {cfs_r:+.1f}R)")

    # ══════════════════════════════════════════════
    # Dual Layer Evidence Court & Reporting
    # ══════════════════════════════════════════════
    async def daily_report_loop(self):
        while True:
            now = datetime.now()
            # Send report at 23:55 daily
            if now.hour == 23 and now.minute == 55:
                await self.generate_human_report()
                await self.generate_truth_dashboard()
                await asyncio.sleep(60)
            await asyncio.sleep(30)
            
    async def generate_human_report(self):
        """Real SQL-backed daily summary — no mock data"""
        import sqlite3
        conn = sqlite3.connect(str(DATA_DIR / "qve_court.db"), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        
        good_entries = cur.execute("SELECT COUNT(*) as c FROM decision_evaluations WHERE result_matrix='GOOD_ENTRY' AND entry_ts >= ?", (today_start,)).fetchone()['c']
        bad_entries = cur.execute("SELECT COUNT(*) as c FROM decision_evaluations WHERE result_matrix='BAD_ENTRY' AND entry_ts >= ?", (today_start,)).fetchone()['c']
        good_avoidance = cur.execute("SELECT COUNT(*) as c FROM decision_evaluations WHERE result_matrix='GOOD_AVOIDANCE' AND entry_ts >= ?", (today_start,)).fetchone()['c']
        missed_opp = cur.execute("SELECT COUNT(*) as c FROM decision_evaluations WHERE result_matrix='MISSED_OPPORTUNITY' AND entry_ts >= ?", (today_start,)).fetchone()['c']
        no_edge = cur.execute("SELECT COUNT(*) as c FROM decision_evaluations WHERE result_matrix='NO_EDGE' AND entry_ts >= ?", (today_start,)).fetchone()['c']
        total_signals = cur.execute("SELECT COUNT(*) as c FROM signals WHERE ts >= ?", (today_start,)).fetchone()['c']
        
        total_evals = good_entries + bad_entries + good_avoidance + missed_opp + no_edge
        if total_evals == 0:
            logger.info("QVE Daily Summary: 0 evaluations recorded, skipping Telegram dispatch.")
            conn.close()
            return

        action_rate = ((good_entries + bad_entries) / total_signals * 100) if total_signals > 0 else 0
        avoidance_pct = (good_avoidance / (good_avoidance + missed_opp) * 100) if (good_avoidance + missed_opp) > 0 else 0
        
        msg = "⚖️ *HORUS QVE — Daily Summary*\n"
        msg += "━━━━━━━━━━━━━━━\n"
        msg += f"📡 Signals: `{total_signals}` | Evaluations: `{total_evals}`\n"
        msg += f"⚡ Action Rate: `{action_rate:.1f}%`\n\n"
        msg += "📊 *Decision Matrix:*\n"
        msg += f"• ⚔️ Good Entries: `{good_entries}`\n"
        msg += f"• ❌ Bad Entries: `{bad_entries}`\n"
        msg += f"• 🛡️ Good Avoidance: `{good_avoidance}`\n"
        msg += f"• 🚨 Missed Opportunities: `{missed_opp}`\n"
        msg += f"• ⚪ No Edge: `{no_edge}`\n\n"
        msg += f"🎯 Avoidance Accuracy: `{avoidance_pct:.0f}%`\n"
        msg += "━━━━━━━━━━━━━━━\n"
        await self.send_telegram(msg)
        conn.close()
        
    async def generate_truth_dashboard(self):
        """Real SQL-backed Truth Dashboard — Realized vs Counterfactual"""
        import sqlite3
        conn = sqlite3.connect(str(DATA_DIR / "qve_court.db"), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        today_start = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        
        # Realized Expectancy (only actual entries)
        realized = cur.execute(
            "SELECT AVG(expectancy_r) as avg_r, SUM(expectancy_r) as sum_r, COUNT(*) as c FROM decision_evaluations WHERE is_realized=1 AND entry_ts >= ?",
            (today_start,)
        ).fetchone()
        realized_avg = realized['avg_r'] or 0.0
        realized_sum = realized['sum_r'] or 0.0
        realized_count = realized['c'] or 0

        if realized_count == 0:
            logger.info("QVE Truth Dashboard: 0 realized trades, skipping Telegram dispatch.")
            conn.close()
            return
        
        # Profit Factor (realized only)
        wins_r = cur.execute("SELECT SUM(expectancy_r) as s FROM decision_evaluations WHERE is_realized=1 AND expectancy_r > 0 AND entry_ts >= ?", (today_start,)).fetchone()['s'] or 0.0
        losses_r = abs(cur.execute("SELECT SUM(expectancy_r) as s FROM decision_evaluations WHERE is_realized=1 AND expectancy_r < 0 AND entry_ts >= ?", (today_start,)).fetchone()['s'] or -0.01)
        profit_factor = wins_r / losses_r if losses_r > 0 else 0.0
        
        # Avoidance Stats
        good_av = cur.execute("SELECT COUNT(*) as c FROM decision_evaluations WHERE result_matrix='GOOD_AVOIDANCE' AND entry_ts >= ?", (today_start,)).fetchone()['c']
        missed = cur.execute("SELECT COUNT(*) as c FROM decision_evaluations WHERE result_matrix='MISSED_OPPORTUNITY' AND entry_ts >= ?", (today_start,)).fetchone()['c']
        avoidance_pct = (good_av / (good_av + missed) * 100) if (good_av + missed) > 0 else 0
        
        avg_opp_cost = cur.execute("SELECT AVG(opportunity_cost_r) as a FROM decision_evaluations WHERE result_matrix='MISSED_OPPORTUNITY' AND entry_ts >= ?", (today_start,)).fetchone()['a'] or 0.0
        max_opp_cost = cur.execute("SELECT MAX(opportunity_cost_r) as m FROM decision_evaluations WHERE result_matrix='MISSED_OPPORTUNITY' AND entry_ts >= ?", (today_start,)).fetchone()['m'] or 0.0
        
        # R saved by avoidance
        saved_rows = cur.execute("SELECT counterfactual_long_r, counterfactual_short_r FROM decision_evaluations WHERE result_matrix='GOOD_AVOIDANCE' AND entry_ts >= ?", (today_start,)).fetchall()
        total_saved = sum(abs(min(r['counterfactual_long_r'] or 0, r['counterfactual_short_r'] or 0)) for r in saved_rows)
        net_r_advantage = total_saved - (avg_opp_cost * missed)
        
        # TTO stats
        avg_tto = cur.execute("SELECT AVG(time_to_outcome) as a FROM decision_evaluations WHERE entry_ts >= ?", (today_start,)).fetchone()['a'] or 0.0
        
        # Regime distribution today
        regimes = cur.execute("SELECT market_regime, COUNT(*) as c FROM signals WHERE ts >= ? GROUP BY market_regime ORDER BY c DESC LIMIT 3", (today_start,)).fetchall()
        regime_str = " | ".join(f"`{r['market_regime']}`: {r['c']}" for r in regimes) if regimes else "No data"
        
        msg = "🔬 *HORUS QVE — Truth Dashboard*\n"
        msg += "━━━━━━━━━━━━━━━\n"
        msg += "📉 *Realized Edge:*\n"
        msg += f"• Trades: `{realized_count}` | Avg: `{realized_avg:+.2f}R`\n"
        msg += f"• Total P/L: `{realized_sum:+.2f}R`\n"
        msg += f"• Profit Factor: `{profit_factor:.2f}`\n\n"
        
        msg += "⚖️ *Avoidance Intelligence:*\n"
        msg += f"• Success Rate: `{avoidance_pct:.0f}%` ({good_av}/{good_av+missed})\n"
        msg += f"• R Saved: `{total_saved:.1f}R`\n"
        msg += f"• Avg Miss Cost: `{avg_opp_cost:.1f}R`\n"
        msg += f"• Max Miss Cost: `{max_opp_cost:.1f}R`\n"
        msg += f"• Net Advantage: `{net_r_advantage:+.1f}R`\n\n"
        
        msg += "⏱ *Timing:*\n"
        msg += f"• Avg TTO: `{avg_tto/60:.1f}m`\n\n"
        
        msg += "🌍 *Regime:*\n"
        msg += f"• {regime_str}\n"
        msg += "━━━━━━━━━━━━━━━\n"
        await self.send_telegram(msg)
        conn.close()
        
    async def send_telegram(self, text: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            # Try Markdown first, fallback to plain text if parsing fails
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
            async with self.session.post(url, json=payload, timeout=5) as r:
                if r.status != 200:
                    # Fallback: send without Markdown parsing
                    payload_plain = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
                    async with self.session.post(url, json=payload_plain, timeout=5) as r2:
                        if r2.status == 200:
                            print(f"[QVE Telegram] ✅ Sent (plain text fallback)")
                        else:
                            resp = await r2.text()
                            print(f"[QVE Telegram] ❌ Failed: {resp[:100]}")
                else:
                    print(f"[QVE Telegram] ✅ Sent")
        except Exception as e:
            print(f"[QVE Telegram] ❌ Error: {e}")

if __name__ == "__main__":
    engine = QVEEngine()
    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        print("\n[QVE Terminated]")
