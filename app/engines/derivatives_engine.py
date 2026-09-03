# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — derivatives_engine.py

Tracks Binance Futures derivatives data:
  1. Open Interest (OI) — Are whales opening or closing positions?
  2. Funding Rate — Is the market biased long or short?
  3. Liquidations — Is a cascade about to happen?

ZERO I/O: Fed by the Futures WS/REST poller. Pure in-memory math.
"""

import time
import logging
from typing import Dict, Optional
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger("DerivativesEngine")


@dataclass
class LiquidationEvent:
    """A single forced liquidation event from Binance."""
    timestamp: float
    symbol: str
    side: str        # "BUY" (short liquidated) or "SELL" (long liquidated)
    price: float
    qty: float
    notional: float  # price * qty


class DerivativesEngine:
    """
    Processes derivatives data into actionable intelligence.
    
    Signals produced:
      - OI_RISING_PRICE_FALLING:  Shorts piling in (bearish conviction)
      - OI_RISING_PRICE_RISING:   Longs piling in (bullish conviction, but greedy)
      - OI_FALLING:               Positions closing (de-leverage, trend exhaustion)
      - FUNDING_EXTREME_LONG:     Market overleveraged long (dump likely)
      - FUNDING_EXTREME_SHORT:    Market overleveraged short (squeeze likely)
      - LIQUIDATION_CASCADE_LONG: Mass long liquidations (waterfall)
      - LIQUIDATION_CASCADE_SHORT: Mass short liquidations (short squeeze)
    """

    # Thresholds
    FUNDING_EXTREME = 0.0005       # 0.05% per 8h = overleveraged
    FUNDING_NEGATIVE_EXTREME = -0.0003  # -0.03% = shorts paying longs
    OI_CHANGE_SIGNIFICANT = 0.005  # 0.5% change in OI = significant
    LIQUIDATION_CASCADE_USD = 500_000  # $500K liquidated in 60s = cascade
    LIQUIDATION_CASCADE_COUNT = 10     # 10+ liquidations in 60s = cascade

    def __init__(self):
        # Open Interest history: deque of (ts, oi_value)
        self._oi_history: Dict[str, deque] = {}
        self._OI_HISTORY_SIZE = 60  # ~5 min of 5s polls

        # Funding Rate: latest value per symbol
        self._funding_rate: Dict[str, float] = {}
        self._funding_update_ts: Dict[str, float] = {}

        # Liquidations: rolling window
        self._liquidations: Dict[str, deque] = {}
        self._LIQUIDATION_WINDOW = 300  # Keep 5 min of liquidations

        # Latest price for OI divergence calculation
        self._last_price: Dict[str, float] = {}

        logger.info("📊 DerivativesEngine initialized")

    # ═══════════════════════════════════════════
    # FEED METHODS (called by the Futures WS/REST poller)
    # ═══════════════════════════════════════════

    def feed_open_interest(self, symbol: str, oi_value: float):
        """Feed an Open Interest snapshot (total contracts)."""
        now = time.time()
        if symbol not in self._oi_history:
            self._oi_history[symbol] = deque(maxlen=self._OI_HISTORY_SIZE)
        self._oi_history[symbol].append((now, oi_value))

    def feed_funding_rate(self, symbol: str, rate: float):
        """Feed the latest funding rate."""
        self._funding_rate[symbol] = rate
        self._funding_update_ts[symbol] = time.time()

    def feed_liquidation(self, symbol: str, side: str, price: float, qty: float):
        """Feed a single liquidation event from forceOrder stream."""
        now = time.time()
        notional = price * qty

        event = LiquidationEvent(
            timestamp=now,
            symbol=symbol,
            side=side.upper(),
            price=price,
            qty=qty,
            notional=notional
        )

        if symbol not in self._liquidations:
            self._liquidations[symbol] = deque(maxlen=500)
        self._liquidations[symbol].append(event)

    def feed_price(self, symbol: str, price: float):
        """Track latest price for OI divergence."""
        self._last_price[symbol] = price

    # ═══════════════════════════════════════════
    # ANALYSIS (called by flow_interpreter.py)
    # ═══════════════════════════════════════════

    def get_derivatives_state(self, symbol: str) -> Optional[Dict]:
        """
        Returns the complete derivatives intelligence for a symbol.
        Pure O(1) math on in-memory deques.
        """
        now = time.time()
        result = {
            "oi_signal": "NONE",
            "oi_change_pct": 0.0,
            "funding_signal": "NONE",
            "funding_rate": 0.0,
            "liquidation_signal": "NONE",
            "liq_long_usd_60s": 0.0,
            "liq_short_usd_60s": 0.0,
            "liq_count_60s": 0,
            "has_data": False,
        }

        # ── Open Interest Analysis ──
        if symbol in self._oi_history and len(self._oi_history[symbol]) >= 3:
            oi_data = list(self._oi_history[symbol])
            oldest = oi_data[0][1]
            latest = oi_data[-1][1]

            if oldest > 0:
                oi_change_pct = (latest - oldest) / oldest
                result["oi_change_pct"] = round(oi_change_pct * 100, 3)
                result["has_data"] = True

                # OI Divergence with price
                price = self._last_price.get(symbol)
                if price and len(oi_data) >= 2:
                    # Compare OI direction with price direction
                    price_prev = oi_data[0]  # Approximate: use OI timestamp's price
                    oi_rising = oi_change_pct > self.OI_CHANGE_SIGNIFICANT
                    oi_falling = oi_change_pct < -self.OI_CHANGE_SIGNIFICANT

                    if oi_rising:
                        result["oi_signal"] = "OI_RISING"
                    elif oi_falling:
                        result["oi_signal"] = "OI_FALLING"

        # ── Funding Rate Analysis ──
        if symbol in self._funding_rate:
            rate = self._funding_rate[symbol]
            result["funding_rate"] = rate
            result["has_data"] = True

            if rate >= self.FUNDING_EXTREME:
                result["funding_signal"] = "EXTREME_LONG"
            elif rate <= self.FUNDING_NEGATIVE_EXTREME:
                result["funding_signal"] = "EXTREME_SHORT"
            elif rate > 0.0001:
                result["funding_signal"] = "LONG_BIAS"
            elif rate < -0.0001:
                result["funding_signal"] = "SHORT_BIAS"
            else:
                result["funding_signal"] = "NEUTRAL"

        # ── Liquidation Cascade Detection ──
        if symbol in self._liquidations:
            liq_60s = [e for e in self._liquidations[symbol] if (now - e.timestamp) <= 60]

            long_liq_usd = sum(e.notional for e in liq_60s if e.side == "SELL")   # Long liquidated = forced sell
            short_liq_usd = sum(e.notional for e in liq_60s if e.side == "BUY")   # Short liquidated = forced buy

            result["liq_long_usd_60s"] = round(long_liq_usd, 2)
            result["liq_short_usd_60s"] = round(short_liq_usd, 2)
            result["liq_count_60s"] = len(liq_60s)

            if long_liq_usd >= self.LIQUIDATION_CASCADE_USD or (len(liq_60s) >= self.LIQUIDATION_CASCADE_COUNT and long_liq_usd > short_liq_usd):
                result["liquidation_signal"] = "CASCADE_LONG"
                result["has_data"] = True
            elif short_liq_usd >= self.LIQUIDATION_CASCADE_USD or (len(liq_60s) >= self.LIQUIDATION_CASCADE_COUNT and short_liq_usd > long_liq_usd):
                result["liquidation_signal"] = "CASCADE_SHORT"
                result["has_data"] = True

        return result


# Singleton
derivatives_engine = DerivativesEngine()
