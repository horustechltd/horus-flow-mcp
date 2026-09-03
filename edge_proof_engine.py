"""
HORUS Edge Proof Engine
━━━━━━━━━━━━━━━━━━━━━━━
Proves whether Horus Flow's RAW orderflow signals predict price direction.

Instead of trying to be a trading bot, this engine measures statistical
accuracy of each signal type across multiple time horizons.

Every 10 seconds:
  1. Fetch raw Horus Flow signal for each symbol
  2. If directional signal (not NEUTRAL) → record prediction + price
  3. Check pending predictions whose time horizon has elapsed
  4. Mark correct/wrong based on actual price movement

Daily report: hit rates per signal type at 1m/5m/15m/30m.
"""

import os
import time
import json
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone

from edge_proof_db import edge_proof_db

# ══════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "7649770299:AAEW3nO-ko1a63tQZSzreNF7RpjYjInRCi4")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1245603051")
API_KEY = "horus-demo-key-2026"
BASE_URL = "http://127.0.0.1:8011"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Signals that imply a directional prediction
BEARISH_SIGNALS = {
    "EMERGENCY_DUMP", "LIQUIDATION_CASCADE", "IMMINENT_DUMP_5M",
    "WHALE_DUMP", "SELL_SPIKE", "INSTITUTIONAL_DISTRIBUTION",
    "WHALE_EXIT", "SELL_PRESSURE", "STRONG_SELL_PRESSURE",
    "DEPTH_COLLAPSE",
}
BULLISH_SIGNALS = {
    "SHORT_SQUEEZE", "IMMINENT_PUMP_5M",
    "STRONG_BUY_PRESSURE", "BUY_PRESSURE",
}
NEUTRAL_SIGNALS = {"NEUTRAL", "BUY_ABSORPTION"}

# How often to check each horizon (seconds)
HORIZONS = [60, 300, 900, 1800]  # 1m, 5m, 15m, 30m

# Dedup: don't log same signal for same symbol within this window
DEDUP_WINDOW_SECONDS = 300  # 5 min cooldown per (symbol, direction)

# Polling
SIGNAL_POLL_INTERVAL = 10  # seconds
OUTCOME_CHECK_INTERVAL = 30  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | EdgeProof | %(message)s",
    handlers=[
        logging.FileHandler("/root/horus_flow_api/logs/edge_proof.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EdgeProof")


class EdgeProofEngine:
    def __init__(self):
        self.session = None
        self.predictions_recorded = 0
        self.outcomes_resolved = 0
        self.last_signal = {}  # {symbol: (signal, ts)} for dedup

    async def start(self):
        print("=" * 60)
        print("  HORUS Edge Proof Engine")
        print("  Measuring RAW Signal Predictive Accuracy")
        print("=" * 60)

        self.session = aiohttp.ClientSession()

        # Start concurrent tasks
        await asyncio.gather(
            self.poll_signals_loop(),
            self.check_outcomes_loop(),
            self.daily_report_loop(),
        )

    # ══════════════════════════════════════════════
    # Signal Collection
    # ══════════════════════════════════════════════
    async def poll_signals_loop(self):
        """Fetch raw Horus Flow signals and record directional predictions."""
        while True:
            try:
                for symbol in SYMBOLS:
                    await self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"Signal poll error: {e}")
            await asyncio.sleep(SIGNAL_POLL_INTERVAL)

    async def _process_symbol(self, symbol: str):
        """Fetch and potentially record a prediction for one symbol."""
        try:
            url = f"{BASE_URL}/v1/flow/crypto/{symbol}"
            async with self.session.get(url, params={"key": API_KEY}, timeout=10) as r:
                if r.status != 200:
                    return
                data = await r.json()
        except Exception as e:
            logger.error(f"Fetch error {symbol}: {e}")
            return

        signal = data.get("signal", "NEUTRAL")
        direction_bias = data.get("direction_bias", "NEUTRAL")
        confidence = data.get("confidence", 0)

        # Skip neutral / non-directional signals
        if signal in NEUTRAL_SIGNALS or direction_bias == "NEUTRAL":
            return

        # Dedup: only record a new prediction when direction CHANGES
        # for this symbol, or after cooldown expires.
        # This prevents logging 100+ identical BEARISH predictions per hour
        # when the signal oscillates between SELL_PRESSURE / INST_DISTRIBUTION.
        last = self.last_signal.get(symbol)
        now = time.time()
        if last and last[0] == direction_bias and (now - last[1]) < DEDUP_WINDOW_SECONDS:
            return

        # Additional dedup via DB (checks direction_bias, not signal name)
        recent_count = await edge_proof_db.get_prediction_count_last_n_seconds(
            symbol, direction_bias, DEDUP_WINDOW_SECONDS
        )
        if recent_count > 0:
            self.last_signal[symbol] = (direction_bias, now)
            return

        # Get current price from the signal data itself
        # The flow API response contains a timestamp but not always a price.
        # We'll fetch the latest price from Binance ticker.
        price = await self._get_current_price(symbol)
        if price <= 0:
            return

        # Extract whale intent if available
        whale = data.get("whale_intent")
        whale_dir = whale.get("direction") if whale else None

        # Record prediction
        pred_id = await edge_proof_db.insert_prediction(
            ts=now,
            symbol=symbol,
            signal=signal,
            direction_bias=direction_bias,
            confidence=confidence,
            price=price,
            whale_intent=whale_dir,
        )

        self.last_signal[symbol] = (direction_bias, now)
        self.predictions_recorded += 1

        logger.info(
            f"📡 {symbol} | {signal} | {direction_bias} | conf={confidence:.2f} "
            f"| price=${price:,.2f} | pred#{pred_id}"
        )

    async def _get_current_price(self, symbol: str) -> float:
        """Get current price from Binance ticker."""
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            async with self.session.get(url, timeout=5) as r:
                if r.status == 200:
                    data = await r.json()
                    return float(data.get("price", 0))
        except Exception:
            pass
        return 0.0

    # ══════════════════════════════════════════════
    # Outcome Checking
    # ══════════════════════════════════════════════
    async def check_outcomes_loop(self):
        """Periodically check if pending predictions have resolved."""
        while True:
            try:
                for horizon in HORIZONS:
                    await self._check_horizon(horizon)
            except Exception as e:
                logger.error(f"Outcome check error: {e}")
            await asyncio.sleep(OUTCOME_CHECK_INTERVAL)

    async def _check_horizon(self, horizon_seconds: int):
        """Check all pending predictions for a specific time horizon."""
        pending = await edge_proof_db.get_pending_predictions(horizon_seconds)
        if not pending:
            return

        horizon_label = {60: "1m", 300: "5m", 900: "15m", 1800: "30m"}[horizon_seconds]

        for pred in pending:
            try:
                # Get the price at the target time
                target_ts = pred["ts"] + horizon_seconds
                future_price = await self._get_price_at_time(pred["symbol"], target_ts)

                if future_price <= 0:
                    continue

                entry_price = pred["price_at_signal"]
                move_pct = (future_price - entry_price) / entry_price * 100

                # Was the prediction correct?
                direction = pred["direction_bias"]
                if direction == "BEARISH":
                    correct = move_pct < 0
                elif direction == "BULLISH":
                    correct = move_pct > 0
                else:
                    correct = False

                await edge_proof_db.update_outcome(
                    pred["id"], horizon_seconds, future_price, move_pct, correct
                )

                self.outcomes_resolved += 1
                icon = "✅" if correct else "❌"
                logger.debug(
                    f"{icon} {pred['symbol']} {pred['signal']} @{horizon_label} | "
                    f"move={move_pct:+.4f}% | dir={direction}"
                )
            except Exception as e:
                logger.error(f"Outcome check failed for pred#{pred['id']}: {e}")

    async def _get_price_at_time(self, symbol: str, target_ts: float) -> float:
        """Get the close price of the 1m candle containing target_ts."""
        try:
            # Binance kline: startTime = beginning of the 1m candle
            candle_start = int(target_ts * 1000)  # Convert to ms
            params = {
                "symbol": symbol,
                "interval": "1m",
                "startTime": candle_start - 60000,  # One candle before
                "limit": 2
            }
            async with self.session.get(BINANCE_KLINES_URL, params=params, timeout=5) as r:
                if r.status == 200:
                    klines = await r.json()
                    if klines:
                        # Use the close of the candle closest to target_ts
                        return float(klines[-1][4])  # close price
        except Exception:
            pass
        return 0.0

    # ══════════════════════════════════════════════
    # Daily Report
    # ══════════════════════════════════════════════
    async def daily_report_loop(self):
        """Send daily accuracy report at midnight UTC."""
        while True:
            now = datetime.now(timezone.utc)
            # Next midnight UTC
            tomorrow = now.replace(hour=0, minute=55, second=0, microsecond=0)
            if now.hour >= 0 and now.minute >= 55:
                tomorrow = tomorrow.replace(day=now.day + 1)

            seconds_until = (tomorrow - now).total_seconds()
            if seconds_until < 0:
                seconds_until = 3600  # fallback

            await asyncio.sleep(min(seconds_until, 3600))

            # Check if it's report time (00:55 UTC)
            now = datetime.now(timezone.utc)
            if now.hour == 0 and 50 <= now.minute <= 59:
                await self._send_daily_report()
                await asyncio.sleep(3600)  # Don't double-send

    async def _send_daily_report(self):
        """Generate and send the daily Edge Proof report focusing on high-conviction signals."""
        try:
            overall = await edge_proof_db.get_overall_accuracy(24)
            if not overall or overall.get("total", 0) == 0:
                logger.info("No resolved predictions for daily report")
                return

            signal_stats = await edge_proof_db.get_daily_accuracy(24)

            # Separate High-Conviction Institutional Signals from baseline micro-flow
            INSTITUTIONAL_KEYS = {
                "SELL_SPIKE", "WHALE_DUMP", "DEPTH_COLLAPSE", "STRONG_BUY_PRESSURE",
                "STRONG_SELL_PRESSURE", "EMERGENCY_DUMP", "INSTITUTIONAL_DISTRIBUTION", "WHALE_EXIT"
            }

            inst_signals = [s for s in signal_stats if s["signal"] in INSTITUTIONAL_KEYS]
            micro_signals = [s for s in signal_stats if s["signal"] not in INSTITUTIONAL_KEYS]

            msg = "📊 <b>HORUS EDGE PROOF — Institutional Performance (24h)</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            if inst_signals:
                msg += "🦅 <b>1. دقة الإشارات المؤسسية عالية الكثافة (High-Conviction Edge):</b>\n\n"
                for s in inst_signals:
                    total = s["total"]
                    r1 = s["resolved_1m"]
                    r5 = s["resolved_5m"]
                    r15 = s["resolved_15m"]
                    r30 = s["resolved_30m"]

                    pct_1m = f"{s['hit_1m']/r1*100:.0f}%" if r1 > 0 else "—"
                    pct_5m = f"{s['hit_5m']/r5*100:.0f}%" if r5 > 0 else "—"
                    pct_15m = f"{s['hit_15m']/r15*100:.0f}%" if r15 > 0 else "—"
                    pct_30m = f"{s['hit_30m']/r30*100:.0f}%" if r30 > 0 else "—"

                    badge = " 🔥 (High Edge)" if (r30 > 0 and s['hit_30m']/r30 >= 0.60) or (r5 > 0 and s['hit_5m']/r5 >= 0.60) else ""
                    msg += f"• <code>{s['signal']}</code> ({total}x){badge}\n"
                    msg += f"  1m: <b>{pct_1m}</b> | 5m: <b>{pct_5m}</b> | 15m: <b>{pct_15m}</b> | 30m: <b>{pct_30m}</b>\n"
            else:
                msg += "🦅 <b>1. الإشارات المؤسسية:</b> <i>السوق كان في حالة خمول وتذبذب ضيق دون تدفقات حيتان عنيفة.</i>\n"

            if micro_signals:
                msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                msg += "🌊 <b>2. تدفق السيولة المجهري العادي (Baseline Orderbook Noise):</b>\n"
                for s in micro_signals:
                    total = s["total"]
                    r5 = s["resolved_5m"]
                    pct_5m = f"{s['hit_5m']/r5*100:.0f}%" if r5 > 0 else "—"
                    r30 = s["resolved_30m"]
                    pct_30m = f"{s['hit_30m']/r30*100:.0f}%" if r30 > 0 else "—"
                    msg += f"• <code>{s['signal']}</code> ({total}x) ➔ 5m: {pct_5m} | 30m: {pct_30m} (ضوضاء تذبذب)\n"

            # SILENCED: Public Telegram dispatch disabled to prevent broadcasting noisy raw calibration data.
            # Edge proof runs as an internal diagnostic telemetry engine.
            logger.info("📊 Daily report compiled internally (Telegram public broadcast silenced).")
            logger.debug(f"Compiled report content:\n{msg}")

        except Exception as e:
            logger.error(f"Daily report error: {e}")

    # ══════════════════════════════════════════════
    # Hourly Mini-Report (lightweight status check)
    # ══════════════════════════════════════════════
    async def hourly_status_loop(self):
        """Log hourly status to console (not Telegram)."""
        while True:
            await asyncio.sleep(3600)
            try:
                overall = await edge_proof_db.get_overall_accuracy(1)
                if overall and overall.get("total", 0) > 0:
                    total = overall["total"]
                    r5 = overall.get("resolved_5m", 0)
                    if r5 > 0:
                        pct_5m = overall["hit_5m"] / r5 * 100
                        logger.info(
                            f"⏱ Hourly: {total} predictions | "
                            f"5m accuracy: {pct_5m:.1f}% ({r5} resolved)"
                        )
            except Exception as e:
                logger.error(f"Hourly status error: {e}")

    # ══════════════════════════════════════════════
    # Telegram
    # ══════════════════════════════════════════════
    async def send_telegram(self, text: str):
        if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            return
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
            async with self.session.post(url, json=payload, timeout=5) as r:
                if r.status == 200:
                    logger.info("[Telegram] ✅ Sent")
                else:
                    resp = await r.text()
                    logger.error(f"[Telegram] ❌ Failed: {resp[:100]}")
        except Exception as e:
            logger.error(f"[Telegram] ❌ Error: {e}")


if __name__ == "__main__":
    engine = EdgeProofEngine()
    try:
        asyncio.run(engine.start())
    except KeyboardInterrupt:
        print("\n[Edge Proof Engine Terminated]")
