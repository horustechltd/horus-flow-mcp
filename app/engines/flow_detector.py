# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — Extracted flow_detector.py
Extracted directly from HORUS (horus_trade_advisor.py).
Pure math only, no side-effects.
"""
import time
from typing import Dict, Optional
from collections import deque

class FlowDetector:
    """
    Tracks aggressive trades (taker fills) and computes buy/sell delta.
    
    Rolling windows:
      - 5-second burst delta
      - 30-second trend delta
      - 60-second baseline (for normalization)
    """
    
    def __init__(self):
        self._trades: Dict[str, deque] = {}   # {symbol: deque of trade records}
        self._max_history = 5000               # Keep last 5000 trades per symbol (covers ~5 mins of heavy flow)
        # 24h quote volume per symbol (USD), refreshed by the WS manager.
        # Used to size the "large trade" threshold relative to each market.
        self._quote_volume_24h: Dict[str, float] = {}

    # A trade counts as "large" when it exceeds 1/20,000 of the symbol's 24h volume,
    # clamped to [$10K, $250K]. Without volume data the legacy $50K threshold applies.
    LARGE_TRADE_VOLUME_FRACTION = 1 / 20000
    LARGE_TRADE_MIN_USD = 10_000
    LARGE_TRADE_MAX_USD = 250_000
    LARGE_TRADE_DEFAULT_USD = 50_000
    LARGE_SELL_WINDOW_S = 300

    def set_quote_volumes(self, volumes: Dict[str, float]):
        if volumes:
            self._quote_volume_24h = dict(volumes)

    def large_trade_threshold(self, symbol: str) -> float:
        vol = self._quote_volume_24h.get(symbol)
        if not vol:
            return float(self.LARGE_TRADE_DEFAULT_USD)
        thr = vol * self.LARGE_TRADE_VOLUME_FRACTION
        return float(min(max(thr, self.LARGE_TRADE_MIN_USD), self.LARGE_TRADE_MAX_USD))

    def last_price(self, symbol: str) -> float:
        trades = self._trades.get(symbol)
        return trades[-1]["price"] if trades else 0.0
    
    def feed(self, symbol: str, price: float, qty: float, is_buyer_maker: bool, timestamp: float = None):
        """
        Feed an aggressive trade.
        """
        ts = timestamp or time.time()
        
        # is_buyer_maker=True means the buyer was the maker (limit order),
        # so the taker was the SELLER (aggressive sell).
        # is_buyer_maker=False means the taker was the BUYER (aggressive buy).
        
        notional = price * qty
        
        trade_record = {
            "ts": ts,
            "price": price,
            "qty": qty,
            "notional": notional,
            "is_sell": is_buyer_maker,   # True = aggressive sell
        }
        
        if symbol not in self._trades:
            self._trades[symbol] = deque(maxlen=self._max_history)
        self._trades[symbol].append(trade_record)
    
    def get_delta(self, symbol: str) -> Optional[Dict]:
        """
        Get trade flow delta for a symbol.
        """
        if symbol not in self._trades or len(self._trades[symbol]) < 3:
            return None
        
        now = time.time()
        trades = list(self._trades[symbol])
        large_thr = self.large_trade_threshold(symbol)
        
        # Calculate deltas over windows
        delta_5s = 0.0
        delta_30s = 0.0
        delta_60s = 0.0
        delta_5m = 0.0
        buy_vol_30s = 0.0
        sell_vol_30s = 0.0
        large_sell_count = 0
        sell_notional_5s = 0.0
        total_count_30s = 0
        prices_30s = []  # prices inside the 30 s window, in arrival order

        # One pass (it runs for every symbol about once a second; it was three passes)
        for t in trades:
            age = now - t["ts"]
            if age > 300:
                continue
            is_sell = t["is_sell"]
            notional = t["notional"]
            notional_signed = -notional if is_sell else notional  # sell = negative, buy = positive
            delta_5m += notional_signed

            if age <= 60:
                delta_60s += notional_signed

            if age <= 30:
                delta_30s += notional_signed
                total_count_30s += 1
                prices_30s.append(t["price"])
                if is_sell:
                    sell_vol_30s += notional
                else:
                    buy_vol_30s += notional

                if age <= 5:
                    delta_5s += notional_signed
                    if is_sell:
                        sell_notional_5s += notional

            # Large sell: single trade above the symbol's size threshold, last 5 minutes
            if is_sell and notional > large_thr:
                large_sell_count += 1

        total_vol_30s = buy_vol_30s + sell_vol_30s
        buy_ratio = buy_vol_30s / total_vol_30s if total_vol_30s > 0 else 0.5

        # Avg trade size (for execution intensity calculation)
        avg_trade_size = total_vol_30s / total_count_30s if total_count_30s > 0 else 0.0

        # Price change over 30s window (Averaged for smoothness)
        if len(prices_30s) >= 10:
            price_change_30s = sum(prices_30s[-5:]) / 5 - sum(prices_30s[:5]) / 5
        elif len(prices_30s) >= 2:
            price_change_30s = prices_30s[-1] - prices_30s[0]
        else:
            price_change_30s = 0.0

        # Price change pct over 30s
        price_change_30s_pct = (price_change_30s / prices_30s[0]) * 100 if len(prices_30s) >= 2 and prices_30s[0] > 0 else 0.0

        # ICEBERG DETECTION (Dynamic CVD Divergence)
        # HFT speed detection using 30s delta against price action
        macro_divergence = "NONE"
        
        # Dynamic volume threshold: 15x the average 5s volume, minimum 50k
        avg_5s_vol = total_vol_30s / 6 if total_vol_30s > 0 else 1
        dynamic_threshold = max(avg_5s_vol * 15, 50000)
        
        # Bullish Absorption (Iceberg Bids): Heavy aggressive selling, but price doesn't drop
        if delta_30s < -dynamic_threshold and price_change_30s_pct >= -0.02:
            macro_divergence = "BULLISH_ABSORPTION"
            
        # Bearish Absorption (Iceberg Asks): Heavy aggressive buying, but price doesn't pump
        elif delta_30s > dynamic_threshold and price_change_30s_pct <= 0.02:
            macro_divergence = "BEARISH_ABSORPTION"
        
        # Sell spike detection: 5s sell volume > 5x average 5s window
        avg_5s_vol = total_vol_30s / 6 if total_vol_30s > 0 else 1  # 30s / 6 windows
        sell_spike = sell_notional_5s > (avg_5s_vol * 5) if avg_5s_vol > 0 else False
        
        # Delta trend: is 30s delta declining compared to 60s?
        delta_declining = delta_30s < (delta_60s * 0.3) if delta_60s > 0 else False
        
        # Delta Acceleration: is pressure BUILDING or fading?
        # Use total_vol_30s as the baseline to prevent division-by-near-zero explosions
        # when delta_30s ≈ 0 (quiet market), which causes fake 100x+ Gamma readings
        vol_baseline = max(total_vol_30s / 6, 1000)  # Minimum $1K/5s to prevent explosion
        delta_accel = min(abs(delta_5s) / vol_baseline, 10.0)  # Hard cap at 10x
        
        return {
            "delta_5s": delta_5s,
            "delta_30s": delta_30s,
            "delta_60s": delta_60s,
            "delta_5m": delta_5m,
            "macro_divergence": macro_divergence,
            "buy_ratio": buy_ratio,
            "sell_spike": sell_spike,
            "large_sell_count": large_sell_count,
            "large_trade_threshold_usd": round(large_thr, 0),
            "large_sell_window_s": self.LARGE_SELL_WINDOW_S,
            "delta_declining": delta_declining,
            "trade_count_30s": total_count_30s,
            "avg_trade_size": avg_trade_size,
            "price_change_30s": price_change_30s,
            "delta_accel": round(delta_accel, 2),
        }
