# -*- coding: utf-8 -*-
"""
Horus Flow Intelligence — MCP Server
=====================================
Exposes Horus orderflow data as AI-native tools via the
Model Context Protocol (MCP).

Architecture: Lightweight proxy → local FastAPI (port 8011).
No duplicate WebSockets. No extra Binance connections.

Usage:
  stdio  (Claude Desktop / Cursor):
    python horus_mcp.py

  SSE  (MCP Marketplaces / remote agents):
    python horus_mcp.py --transport sse --port 8012

© 2026 HORUS TECH LTD
"""
import sys
import json
import argparse
import httpx
from mcp.server.fastmcp import FastMCP

# ─── Parse args early ─────────────────────────────────────
_parser = argparse.ArgumentParser(description="Horus Flow MCP Server")
_parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
_parser.add_argument("--port", type=int, default=8012)
_args = _parser.parse_args()

# ─── Configuration ────────────────────────────────────────
HORUS_API_BASE = "http://127.0.0.1:8011"
HORUS_API_KEY = "horus-demo-key-2026"
HEADERS = {"X-API-Key": HORUS_API_KEY}

# ─── MCP Server Instance ─────────────────────────────────
mcp = FastMCP(
    "Horus Flow Intelligence",
    instructions=(
        "Real-time institutional orderflow intelligence for Crypto & Equities. "
        "Powered by live Binance L2 orderbook depth, aggressive trade feeds, "
        "and live HTA whale intent from institutional trading infrastructure. "
        "Detects BUY_PRESSURE, SELL_PRESSURE, institutional spoofing, whale "
        "direction (LONG/SHORT), and liquidity imbalances in milliseconds."
    ),
    host="0.0.0.0",
    port=_args.port,
)


# ─── Helper ───────────────────────────────────────────────
async def _fetch(endpoint: str) -> dict:
    """Fetch data from the local Horus Flow API."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{HORUS_API_BASE}{endpoint}",
            headers=HEADERS,
        )
        if resp.status_code == 200:
            return resp.json()
        return {
            "error": True,
            "status_code": resp.status_code,
            "detail": resp.text,
        }


# ─── Tool 1: Crypto Flow ─────────────────────────────────
@mcp.tool()
async def get_crypto_flow(symbol: str) -> str:
    """Get real-time institutional orderflow signal for a cryptocurrency.

    Returns live microstructure intelligence extracted from:
    - Binance Level 2 Orderbook (bid/ask imbalance ratio)
    - Aggressive Trade Feed (buy vs sell delta)
    - HTA Whale Intent (live institutional direction from trading soldiers)

    The response includes strict machine-parseable fields:
    - signal: BUY_PRESSURE / SELL_PRESSURE / NEUTRAL / WHALE_DUMP / DEPTH_COLLAPSE / etc.
    - action: WAIT / ENTER_LONG / ENTER_SHORT / BLOCK_LONG / EXIT_LONG / FULL_EXIT / etc.
    - direction_bias: BULLISH / BEARISH / NEUTRAL
    - confidence: 0.0 to 1.0 AI confidence score
    - risk: LOW / MEDIUM / HIGH / EXTREME
    - market_regime: TRENDING / RANGING / CHOP / VOLATILE / LIQUIDITY_EVENT / NO_TRADE
    - engine_version: semantic version string
    - freshness_ms: data age in milliseconds
    - timestamp_utc: ISO 8601 UTC timestamp
    - explanation: clean one-liner reasoning
    - metrics: full orderflow metrics (bid_ratio, buy_ratio, delta_5s, etc.)
    - whale_intent: (when available) live whale direction

    Bots should use 'action' for trade decisions instead of parsing 'description'.

    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT, ETHUSDT, SOLUSDT)

    Example usage:
        get_crypto_flow("BTCUSDT")
    """
    clean = symbol.replace("/", "").replace("-", "").upper()
    data = await _fetch(f"/v1/flow/crypto/{clean}")
    return json.dumps(data, indent=2)


# ─── Tool 2: Equity Flow ─────────────────────────────────
@mcp.tool()
async def get_equity_flow(symbol: str) -> str:
    """Get real-time institutional orderflow signal for a US equity stock.

    Returns live microstructure intelligence from Alpaca IEX feed:
    - signal: BUY_PRESSURE / SELL_PRESSURE / NEUTRAL
    - confidence: 0.0 to 1.0 AI confidence score
    - market_state: TRENDING_UP / TRENDING_DOWN / RANGE_BOUND / VOLATILE
    - risk: LOW / MEDIUM / HIGH / EXTREME
    - bid_ratio: orderbook bid imbalance
    - buy_ratio: aggressive buy percentage
    - delta_5s: net volume delta over last 5 seconds

    Note: US equity data is available during market hours (14:30-21:00 UTC).

    Args:
        symbol: US stock ticker (e.g., AAPL, NVDA, TSLA, MSFT)

    Example usage:
        get_equity_flow("NVDA")
    """
    clean = symbol.upper()
    data = await _fetch(f"/v1/flow/equity/{clean}")
    return json.dumps(data, indent=2)


# ─── Tool 3: Multi-Symbol Scanner ────────────────────────
@mcp.tool()
async def scan_crypto_flow(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT") -> str:
    """Scan multiple cryptocurrencies for orderflow signals simultaneously.

    Useful for finding the strongest buy/sell pressure across
    multiple assets at once. Returns a sorted summary.

    Args:
        symbols: Comma-separated list of trading pairs
                 (default: BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT)

    Example usage:
        scan_crypto_flow("BTCUSDT,ETHUSDT,SOLUSDT")
    """
    import asyncio
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    
    # Fetch all symbols in parallel
    tasks = [_fetch(f"/v1/flow/crypto/{sym}") for sym in symbol_list]
    raw_results = await asyncio.gather(*tasks)
    
    results = []
    for sym, data in zip(symbol_list, raw_results):
        if not data.get("error"):
            results.append(data)
        else:
            results.append({"symbol": sym, "signal": "UNAVAILABLE", "error": data.get("detail", "No data")})

    # Sort by confidence (strongest signals first)
    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    summary = {
        "scanned": len(symbol_list),
        "available": len([r for r in results if r.get("signal") != "UNAVAILABLE"]),
        "strongest_buy": next(
            (r["symbol"] for r in results if r.get("signal") == "BUY_PRESSURE"), None
        ),
        "strongest_sell": next(
            (r["symbol"] for r in results if r.get("signal") == "SELL_PRESSURE"), None
        ),
        "results": results,
    }

    return json.dumps(summary, indent=2)


# ─── Tool 4: Liquidation Heatmap ─────────────────────────
@mcp.tool()
async def get_liquidation_heatmap(symbol: str = "BTCUSDT") -> str:
    """Get liquidation gravity map showing where price is forced to go.

    Reveals where leveraged positions are clustered and estimates
    liquidation cascade zones using Binance Futures data.

    Returns:
    - gravity_direction: DOWN (longs will get liquidated) / UP (shorts squeezed)
    - gravity_score: 0.0 to 1.0 intensity
    - crowd_bias: OVERLEVERAGED_LONG / OVERLEVERAGED_SHORT / BALANCED
    - smart_money_divergence: true = top traders disagree with crowd
    - estimated_liquidation_zones: exact price levels for long/short cascades
    - risk_assessment: human-readable risk summary

    Args:
        symbol: Trading pair (BTCUSDT, ETHUSDT, SOLUSDT)
    """
    clean = symbol.replace("/", "").replace("-", "").upper()
    data = await _fetch(f"/v1/intelligence/liquidation-heatmap?symbol={clean}")
    return json.dumps(data, indent=2)


# ─── Tool 5: Cross-Exchange Flow ─────────────────────────
@mcp.tool()
async def get_cross_exchange_flow(symbol: str = "BTCUSDT") -> str:
    """Analyze Spot vs Futures flow to detect real vs speculative moves.

    Compares Spot volume with Futures volume, tracks Premium/Discount,
    and monitors Open Interest velocity.

    Returns:
    - market_type: SPOT_DRIVEN (real move) / HYPER_SPECULATION (dangerous)
    - premium_bias: BULLISH / BEARISH / NEUTRAL
    - positioning_signal: AGGRESSIVE_POSITIONING_LONG/SHORT / MASS_DELEVERAGING
    - futures_spot_volume_ratio: how much bigger Futures is than Spot
    - risk_assessment: human-readable summary

    Args:
        symbol: Trading pair (BTCUSDT, ETHUSDT, SOLUSDT)
    """
    clean = symbol.replace("/", "").replace("-", "").upper()
    data = await _fetch(f"/v1/intelligence/cross-exchange-flow?symbol={clean}")
    return json.dumps(data, indent=2)


# ─── Tool 6: Composite Intelligence ─────────────────────
@mcp.tool()
async def get_composite_intelligence(symbol: str = "BTCUSDT") -> str:
    """Get the final verdict combining ALL intelligence layers.

    Combines 4 layers into ONE actionable score (0-100):
      - Climate (WiseMan): Is the market worth trading?
      - Ignition (VBE): Is volatility about to explode?
      - Heatmap (Liquidations): Where is price forced to go?
      - XFlow (Spot↔Futures): Is the move real or speculative?

    Returns strict machine-parseable fields:
    - action: WAIT / ENTER_LONG / ENTER_SHORT
    - direction_bias: BULLISH / BEARISH / NEUTRAL
    - risk: LOW / MEDIUM / HIGH / EXTREME
    - market_regime: TRENDING / RANGING / CHOP / VOLATILE / NO_TRADE
    - composite_score: 0-100
    - verdict: FULL_CONVICTION / PARTIAL_CONVICTION / NEUTRAL / STAY_OUT

    Args:
        symbol: Trading pair (BTCUSDT, ETHUSDT, SOLUSDT)
    """
    clean = symbol.replace("/", "").replace("-", "").upper()
    data = await _fetch(f"/v1/intelligence/composite?symbol={clean}")
    return json.dumps(data, indent=2)


# ─── Tool 7: Full Market Intelligence ────────────────────
@mcp.tool()
async def get_full_market_intelligence() -> str:
    """Get ALL intelligence layers for ALL tracked symbols in one call.

    Returns the complete Horus Level 3 intelligence dashboard:
    - Climate (BTC market mode)
    - Ignition (volatility breakout scanner)
    - Liquidation Heatmap (per symbol)
    - Cross-Exchange Flow (per symbol)
    - Composite Score (per symbol)
    - action_summary: per-symbol quick lookup with action/direction_bias/risk

    This is the ultimate tool for AI agents needing full market context.
    No arguments needed — returns everything.
    """
    data = await _fetch("/v1/intelligence/market-intelligence")
    return json.dumps(data, indent=2)


# ─── Tool 8: Horus Cortex Cognitive Intelligence ─────────
@mcp.tool()
async def get_horus_cortex() -> str:
    """Get the highest-tier cognitive intelligence from the Horus Cortex engine.

    Fuses 7 independent evidence families into an authoritative consensus:
      - Price Structure (15m/1h momentum, high/low structures)
      - Dynamic S/R Map (Volume-weighted structural invalidation boundaries)
      - Orderflow (Taker buy/sell aggressive ratio)
      - Breadth & RS (Global ignition, altcoin gravity)
      - Contradiction Engine (Catches divergences like Price-Up vs Flow-Down)
      - Penalized Trust Score (0-100)
      - Action Policy with Position Sizing Multipliers for Autonomous Bots

    Returns:
    - regime_state: BUILDING / EXPANSION / HEALTHY_CONSOLIDATION / TRANSITION / EXHAUSTION / BREAKDOWN
    - trust_score: 0-100 penalized confidence
    - action_policy: multipliers for ignition/trend/reversal and operational directive
    - execution_boundaries: exact invalidation support & breakout resistance in USD
    - active_contradictions: explicit conflicts between price and flow
    - narrative: deterministic institutional Arabic & English market narrative with
      exact 'what_improves' and 'what_worsens' conditions.
    """
    data = await _fetch("/v1/intelligence/cortex")
    return json.dumps(data, indent=2)


# ─── Resource: API Info ───────────────────────────────────
@mcp.resource("horus://info")
async def get_api_info() -> str:
    """Information about the Horus Flow Intelligence system."""
    return json.dumps({
        "name": "Horus Flow Intelligence",
        "version": "2.0.0",
        "provider": "HORUS TECH LTD",
        "description": "Real-time institutional orderflow engine with Level 3 market intelligence",
        "supported_crypto": "All USDT pairs on Binance (e.g., BTCUSDT, ETHUSDT, SOLUSDT)",
        "supported_equities": "US stocks via IEX (e.g., AAPL, NVDA, TSLA)",
        "data_sources": [
            "Binance L2 Orderbook (@depth20@100ms)",
            "Binance Aggressive Trades (@aggTrade)",
            "HTA Whale Intent (live institutional direction via Redis)",
            "Alpaca IEX Feed (US Equities)",
            "Binance Futures OI + Long/Short Ratios + Top Trader Positioning",
            "Binance Futures Premium Index + Funding Rate",
            "Binance Spot vs Futures Volume Comparison",
        ],
        "intelligence_layers": {
            "level_1": "Orderflow (bid/ask imbalance, trade delta)",
            "level_2": "Whale Detection (icebergs, spoofing, depth collapse)",
            "level_3": "Liquidation Heatmap + Cross-Exchange Flow + Composite Score",
        },
        "signals": ["BUY_PRESSURE", "SELL_PRESSURE", "NEUTRAL", "WHALE_EXIT", "DEPTH_COLLAPSE"],
        "verdicts": ["FULL_CONVICTION", "PARTIAL_CONVICTION", "NEUTRAL", "STAY_OUT"],
    }, indent=2)


# ─── Entry Point ──────────────────────────────────────────
if __name__ == "__main__":
    mcp.run(transport=_args.transport)

