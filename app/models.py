# -*- coding: utf-8 -*-
"""
Horus Flow Intelligence — Response Models v2.1
================================================
Strict schema with machine-parseable enums for:
  signal, action, direction_bias, risk, market_regime

All existing fields are preserved for backward compatibility.

© 2026 HORUS TECH LTD
"""
from enum import Enum
from pydantic import BaseModel, ConfigDict
from typing import Optional, List


# ═══════════════════════════════════════════════════════════════
# Strict Enums — The Institutional Standard
# ═══════════════════════════════════════════════════════════════

class SignalType(str, Enum):
    """What is the market doing? (observation)"""
    NEUTRAL = "NEUTRAL"
    BUY_PRESSURE = "BUY_PRESSURE"
    STRONG_BUY_PRESSURE = "STRONG_BUY_PRESSURE"
    SELL_PRESSURE = "SELL_PRESSURE"
    STRONG_SELL_PRESSURE = "STRONG_SELL_PRESSURE"
    BUY_ABSORPTION = "BUY_ABSORPTION"
    WHALE_DUMP = "WHALE_DUMP"
    WHALE_EXIT = "WHALE_EXIT"
    SELL_SPIKE = "SELL_SPIKE"
    DEPTH_COLLAPSE = "DEPTH_COLLAPSE"
    INSTITUTIONAL_DISTRIBUTION = "INSTITUTIONAL_DISTRIBUTION"
    LIQUIDATION_CASCADE = "LIQUIDATION_CASCADE"
    SHORT_SQUEEZE = "SHORT_SQUEEZE"
    EMERGENCY_DUMP = "EMERGENCY_DUMP"
    IMMINENT_DUMP_5M = "IMMINENT_DUMP_5M"
    IMMINENT_PUMP_5M = "IMMINENT_PUMP_5M"


class ActionType(str, Enum):
    """What should the bot do? (recommendation)"""
    WAIT = "WAIT"
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    BLOCK_LONG = "BLOCK_LONG"
    BLOCK_SHORT = "BLOCK_SHORT"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"
    FULL_EXIT = "FULL_EXIT"


class DirectionBias(str, Enum):
    """Which way is the market leaning?"""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class RiskLevel(str, Enum):
    """Risk assessment level."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class MarketRegime(str, Enum):
    """Structural market phase."""
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    CHOP = "CHOP"
    VOLATILE = "VOLATILE"
    LIQUIDITY_EVENT = "LIQUIDITY_EVENT"
    NO_TRADE = "NO_TRADE"


# ═══════════════════════════════════════════════════════════════
# Engine Version
# ═══════════════════════════════════════════════════════════════

ENGINE_VERSION = "2.1.0"


# ═══════════════════════════════════════════════════════════════
# Metrics Model
# ═══════════════════════════════════════════════════════════════

class FlowMetrics(BaseModel):
    """Full-spectrum orderflow metrics — synced with HTA brain."""
    model_config = ConfigDict(extra='ignore')
    
    # Core ratios
    bid_ask_ratio: float = 1.0
    buy_sell_ratio: float = 1.0
    delta_5s: float = 0.0
    delta_30s: float = 0.0
    imbalance_stability: float = 1.0
    # Whale & Spike Intelligence
    whale_activity: bool = False
    large_sell_count: int = 0
    sell_spike: bool = False
    # Momentum Physics
    delta_accel: float = 0.0
    # Orderbook Microstructure
    wall_side: Optional[str] = None
    top5_imbalance: float = 0.5
    spread_pct: float = 0.0
    refill_ratio: float = 1.0
    # Depth Dynamics
    bid_depth_change_pct: float = 0.0
    ask_depth_change_pct: float = 0.0
    # Global Macros
    wiseman_climate: dict = {}
    # Event Flags
    flags: List[str] = []


# ═══════════════════════════════════════════════════════════════
# Flow Response Model — v2.1 Strict Schema
# ═══════════════════════════════════════════════════════════════

class FlowResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    # === NEW: Strict Schema (machine-parseable) ===
    symbol: str
    signal: str                           # SignalType enum value
    action: str = "WAIT"                  # NEW — ActionType enum
    direction_bias: str = "NEUTRAL"       # NEW — DirectionBias enum
    confidence: float
    risk: str                             # RiskLevel enum
    market_regime: str = "RANGING"        # NEW — MarketRegime enum
    
    # === NEW: Metadata ===
    engine_version: str = ENGINE_VERSION  # Semantic version
    freshness_ms: int = 0                 # Data age in milliseconds
    timestamp_utc: str = ""               # ISO 8601 UTC
    explanation: str = ""                 # Clean one-liner reason
    
    # === Existing fields (backward compatible) ===
    market_state: str                     # KEPT for backward compat
    description: str                      # KEPT for human consumers
    metrics: FlowMetrics
    
    # 🐋 HTA Whale Intent (from trading soldiers via Redis)
    whale_intent: Optional[dict] = None
    
    timestamp: float                      # KEPT for backward compat
