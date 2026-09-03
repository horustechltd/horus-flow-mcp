# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — Extracted imbalance.py
Extracted directly from HORUS (horus_trade_advisor.py).
Pure math only, no side-effects.
"""
import time
from typing import Dict, List, Optional
from collections import deque

class ImbalanceCalculator:
    """
    Reads orderbook snapshots and computes bid/ask imbalance.
    """
    
    def __init__(self, history_size: int = 300):
        self._snapshots: Dict[str, deque] = {}   # {symbol: deque of snapshots}
        self._history_size = history_size
    
    def feed(self, symbol: str, bids: List[List[float]], asks: List[List[float]], timestamp: float = None):
        """
        Feed an orderbook snapshot.
        """
        if not bids or not asks:
            return
        
        ts = timestamp or time.time()
        
        # Ensure we only process floats (WS data might come as strings)
        bids = [[float(p), float(q)] for p, q in bids]
        asks = [[float(p), float(q)] for p, q in asks]
        
        bid_volume = sum(b[1] for b in bids)
        ask_volume = sum(a[1] for a in asks)
        
        # Wall detection: any single order > 30% of total side
        bid_wall = any(b[1] > bid_volume * 0.30 for b in bids) if bid_volume > 0 else False
        ask_wall = any(a[1] > ask_volume * 0.30 for a in asks) if ask_volume > 0 else False
        
        # Spread
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        spread_pct = ((best_ask - best_bid) / best_bid * 100) if best_bid > 0 else 0
        
        snapshot = {
            "ts": ts,
            "bid_vol": bid_volume,
            "ask_vol": ask_volume,
            "ratio": bid_volume / ask_volume if ask_volume > 0 else 999,
            "bid_wall": bid_wall,
            "ask_wall": ask_wall,
            "spread_pct": spread_pct,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "top5_bid": sum(b[1] for b in bids[:5]),
            "top5_ask": sum(a[1] for a in asks[:5]),
        }
        
        if symbol not in self._snapshots:
            self._snapshots[symbol] = deque(maxlen=self._history_size)
        self._snapshots[symbol].append(snapshot)
        
    def feed_quote(self, symbol: str, bid_price: float, bid_size: float, ask_price: float, ask_size: float, timestamp: float = None):
        """
        Feed an L1 top-of-book quote (used for Equities).
        We simulate a depth snapshot using top-of-book values.
        """
        if bid_price <= 0 or ask_price <= 0 or bid_size <= 0 or ask_size <= 0:
            return
            
        ts = timestamp or time.time()
        
        spread_pct = ((ask_price - bid_price) / bid_price * 100)
        
        # In L1, the "wall" is just the top size, we don't have true wall detection without L2
        snapshot = {
            "ts": ts,
            "bid_vol": bid_size,
            "ask_vol": ask_size,
            "ratio": bid_size / ask_size if ask_size > 0 else 999,
            "bid_wall": False,
            "ask_wall": False,
            "spread_pct": spread_pct,
            "best_bid": bid_price,
            "best_ask": ask_price,
            "top5_bid": bid_size,  # Proxy
            "top5_ask": ask_size,  # Proxy
        }
        
        if symbol not in self._snapshots:
            self._snapshots[symbol] = deque(maxlen=self._history_size)
        self._snapshots[symbol].append(snapshot)
    
    def get_imbalance(self, symbol: str) -> Optional[Dict]:
        """
        Get current imbalance state for a symbol.
        """
        if symbol not in self._snapshots or len(self._snapshots[symbol]) < 2:
            return None
        
        snapshots = self._snapshots[symbol]
        current = snapshots[-1]
        prev = snapshots[-2]
        
        # Depth change velocity (rolling avg over last 5)
        recent_5 = list(snapshots)[-6:-1] if len(snapshots) >= 6 else list(snapshots)[:-1]
        
        avg_bid = sum(s["top5_bid"] for s in recent_5) / len(recent_5) if recent_5 else 0
        cur_bid = current["top5_bid"]
        bid_depth_change_pct = ((cur_bid - avg_bid) / avg_bid * 100) if avg_bid > 0 else 0
        
        avg_ask = sum(s["top5_ask"] for s in recent_5) / len(recent_5) if recent_5 else 0
        cur_ask = current["top5_ask"]
        ask_depth_change_pct = ((cur_ask - avg_ask) / avg_ask * 100) if avg_ask > 0 else 0
        
        # Wall side
        wall_side = None
        if current["bid_wall"]:
            wall_side = "BID"
        elif current["ask_wall"]:
            wall_side = "ASK"
        
        # Average ratio over last 5 snapshots for stability
        recent = list(snapshots)[-5:]
        avg_ratio = sum(s["ratio"] for s in recent) / len(recent)
        
        # top5 imbalance (distance-weighted proxy)
        top5_bid = current["top5_bid"]
        top5_ask = current["top5_ask"]
        top5_total = top5_bid + top5_ask
        top5_imbalance = top5_bid / top5_total if top5_total > 0 else 0.5
        
        # Imbalance Stability (spoof detection)
        recent_bids = [s["bid_vol"] for s in recent]
        if len(recent_bids) >= 2:
            changes = [abs(recent_bids[i] - recent_bids[i-1]) / max(recent_bids[i-1], 1e-8) 
                       for i in range(1, len(recent_bids))]
            imb_stability = sum(changes) / len(changes)
        else:
            imb_stability = 0.0
        
        refill_ratio = current["ask_vol"] / max(prev["ask_vol"], 1e-8)
        
        return {
            "ratio": current["ratio"],
            "avg_ratio": avg_ratio,
            "bid_depth_change_pct": bid_depth_change_pct,
            "ask_depth_change_pct": ask_depth_change_pct,
            "wall_side": wall_side,
            "spread_pct": current["spread_pct"],
            "bid_vol": current["bid_vol"],
            "ask_vol": current["ask_vol"],
            "top5_bid": top5_bid,
            "top5_ask": top5_ask,
            "top5_imbalance": round(top5_imbalance, 4),
            "imb_stability": round(imb_stability, 4),
            "refill_ratio": round(refill_ratio, 4),
            "best_bid": current["best_bid"],
            "best_ask": current["best_ask"],
        }
