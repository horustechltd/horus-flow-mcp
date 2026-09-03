# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — Extracted market_stress.py
"""
import time
from typing import Dict
from collections import deque
from enum import Enum

from .imbalance import ImbalanceCalculator
from .flow_detector import FlowDetector

class MarketState(str, Enum):
    NORMAL = "NORMAL"
    PRESSURE = "PRESSURE"
    LIQUIDITY_EVENT = "LIQUIDITY_EVENT"

class MarketStressIndex:
    """
    Global market regime detection from BTC real-time flow.
    """
    
    BTC_SYMBOL = "BTCUSDT"
    
    def __init__(self, imbalance_calc: ImbalanceCalculator, flow_detector: FlowDetector):
        # We share instances so the feed logic doesn't double-count
        self._imbalance = imbalance_calc
        self._flow = flow_detector
        self._state = MarketState.NORMAL
        self._state_since = time.time()
        self._last_update = 0
        
        self._delta_history: deque = deque(maxlen=120)
    
    @property
    def state(self) -> MarketState:
        return self._state
    
    def evaluate(self) -> MarketState:
        now = time.time()
        
        if now - self._last_update < 0.5:
            return self._state
        self._last_update = now
        
        imb = self._imbalance.get_imbalance(self.BTC_SYMBOL)
        flow = self._flow.get_delta(self.BTC_SYMBOL)
        
        if not imb or not flow:
            return self._state
        
        self._delta_history.append(flow["delta_5s"])
        
        if len(self._delta_history) < 10:
            return self._state
        
        deltas = list(self._delta_history)
        mean_delta = sum(deltas) / len(deltas)
        variance = sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)
        sigma = variance ** 0.5 if variance > 0 else 1.0
        
        z_score = (flow["delta_5s"] - mean_delta) / sigma if sigma > 0 else 0
        
        # Safely access snapshots
        snapshots = self._imbalance._snapshots.get(self.BTC_SYMBOL, [])
        if len(snapshots) >= 10:
            avg_spread = sum(s["spread_pct"] for s in list(snapshots)[-10:]) / 10
        else:
            avg_spread = imb["spread_pct"]
            
        spread_ratio = imb["spread_pct"] / avg_spread if avg_spread > 0 else 1.0
        
        depth_drop = imb["bid_depth_change_pct"] < -20
        severe_depth_drop = imb["bid_depth_change_pct"] < -40
        
        is_liquidity_event = (
            z_score < -3.0 and
            (spread_ratio > 2.0 or severe_depth_drop)
        )
        
        is_pressure = (
            z_score < -2.0 or
            spread_ratio > 1.5 or
            depth_drop or
            flow["sell_spike"] or
            flow["large_sell_count"] >= 2
        )
        
        new_state = MarketState.NORMAL
        if is_liquidity_event:
            new_state = MarketState.LIQUIDITY_EVENT
        elif is_pressure:
            new_state = MarketState.PRESSURE
        
        if new_state.value == MarketState.LIQUIDITY_EVENT.value and self._state.value != MarketState.LIQUIDITY_EVENT.value:
            self._state = new_state
            self._state_since = now
        elif new_state.value == MarketState.PRESSURE.value and self._state.value == MarketState.NORMAL.value:
            self._state = new_state
            self._state_since = now
        elif new_state.value == self._state.value:
            pass
        else:
            # De-escalate
            if now - self._state_since > 10:
                self._state = new_state
                self._state_since = now
        
        return self._state
