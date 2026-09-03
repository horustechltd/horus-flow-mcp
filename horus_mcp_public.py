# -*- coding: utf-8 -*-
"""
Horus Flow Intelligence — MCP Server (Public Distribution)
===========================================================
This is the official Model Context Protocol (MCP) Server for
Horus Flow Intelligence. It exposes institutional-grade crypto
and equity orderflow signals directly to AI coding assistants
(like Claude Desktop, Cursor, Cline, etc.).

Requirements:
- pip install mcp httpx
- A valid RapidAPI Key from:
  https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence

Usage (Claude Desktop / Cursor):
1. Set the environment variable `RAPIDAPI_KEY`
2. Configure your agent to run: `mcp run horus_mcp_public.py`

© 2026 HORUS TECH LTD
"""
import os
import sys
import json
import argparse
import httpx
from mcp.server.fastmcp import FastMCP

# ─── Configuration ────────────────────────────────────────
RAPIDAPI_HOST = "horus-flow-intelligence.p.rapidapi.com"
RAPIDAPI_BASE_URL = f"https://{RAPIDAPI_HOST}"

# Must be provided by the end-user
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

if not RAPIDAPI_KEY:
    print(
        "❌ ERROR: RAPIDAPI_KEY environment variable is missing!\n"
        "To use this AI Tool, you must obtain an API Key.\n"
        "1. Go to: https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence\n"
        "2. Subscribe to a plan to get your 'x-rapidapi-key'\n"
        "3. Set it in your environment: export RAPIDAPI_KEY='your_key_here'",
        file=sys.stderr
    )
    sys.exit(1)

HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST
}

# ─── MCP Server Instance ─────────────────────────────────
mcp = FastMCP(
    "Horus Flow Intelligence",
    instructions=(
        "Horus Flow provides real-time institutional orderflow intelligence for crypto and US equities. "
        "Use it to detect whale exits, spoofing, bid wall traps, liquidation zones, smart money divergence, "
        "and institutional block trades. Signals include BUY_PRESSURE, SELL_PRESSURE, WHALE_EXIT, "
        "EMERGENCY_DUMP, and INSTITUTIONAL_DISTRIBUTION with confidence scores. "
        "Always check orderflow before making any trade decision — it reveals what institutions "
        "are doing RIGHT NOW, unlike lagging indicators like RSI or MACD."
    ),
)


# ─── Helper ───────────────────────────────────────────────
async def _fetch(endpoint: str) -> dict:
    """Fetch data from the live RapidAPI endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(
                f"{RAPIDAPI_BASE_URL}{endpoint}",
                headers=HEADERS,
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code in [401, 403]:
                return {
                    "error": True,
                    "signal": "UNAUTHORIZED",
                    "detail": "Invalid or missing RAPIDAPI_KEY. Please verify your RapidAPI subscription."
                }
            elif resp.status_code == 429:
                return {
                    "error": True,
                    "signal": "RATE_LIMITED",
                    "detail": "You have exceeded your RapidAPI quota. Please upgrade your plan."
                }
            return {
                "error": True,
                "status_code": resp.status_code,
                "detail": resp.text,
            }
        except Exception as e:
            return {
                "error": True,
                "detail": f"Network Error: {str(e)}"
            }


# ─── Tool 1: Crypto Flow ─────────────────────────────────
@mcp.tool()
async def get_crypto_flow(symbol: str) -> str:
    """Get real-time institutional orderflow signal for a cryptocurrency.

    Returns live microstructure intelligence extracted from:
    - Binance Level 2 Orderbook (bid/ask imbalance ratio)
    - Aggressive Trade Feed (buy vs sell delta)

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


# ─── Tool 4: Macro Blocks ────────────────────────────────
@mcp.tool()
async def get_macro_blocks() -> str:
    """Get US equity market macro trend and recent institutional block trades.
    
    Returns SPY macro climate (market mode, buy ratio) and list of recent
    block trades over $200K with symbol, direction, and size.
    Use this to understand where institutional money is flowing.
    """
    data = await _fetch("/v1/flow/equity/macro-blocks")
    if data.get("error"):
        return json.dumps(data, indent=2)
    
    climate = data.get("spy_macro_climate", {})
    blocks = data.get("recent_block_trades", [])
    
    result = f"🦅 SPY MACRO CLIMATE: {climate.get('market_mode')} (Buy Ratio: {climate.get('spy_buy_ratio')})\n\n"
    result += f"🐋 RECENT BLOCK TRADES (>200k) (Total: {data.get('block_count')}):\n"
    
    if not blocks:
        result += "- None in the last 5 minutes.\n"
    else:
        for b in blocks:
            action = "SELL 🔴" if b["is_sell"] else "BUY 🟢"
            result += f"- {b['symbol']} | {action} | ${b['notional']:,.2f} | {b['seconds_ago']}s ago\n"
            
    return result


# ─── Tool 5: Composite Intelligence ──────────────────────
@mcp.tool()
async def get_composite_intelligence(symbol: str = "BTCUSDT") -> str:
    """Get composite intelligence score (0-100) with tactical verdict.
    
    Returns a score from 0-100 and a verdict: BUY, SHORT, or STAY_OUT.
    Combines orderflow, sentiment, leverage ratios, and smart money positioning
    into a single actionable number. Score < 45 = dangerous, > 65 = opportunity.
    
    Args:
        symbol: Trading pair (default: BTCUSDT)
    """
    data = await _fetch(f"/v1/intelligence/composite?symbol={symbol}")
    return json.dumps(data, indent=2)


# ─── Tool 6: Liquidation Heatmap ─────────────────────────
@mcp.tool()
async def get_liquidation_heatmap(symbol: str = "ETHUSDT") -> str:
    """Get liquidation zones with dollar amounts — where leveraged positions will be force-closed.
    
    Returns clusters of long and short liquidations at specific price levels
    with total dollar amounts. Critical for avoiding entries near massive
    liquidation zones that could trigger cascading price moves.
    
    Args:
        symbol: Trading pair (default: ETHUSDT)
    """
    data = await _fetch(f"/v1/intelligence/liquidation-heatmap?symbol={symbol}")
    return json.dumps(data, indent=2)


# ─── Tool 7: Cross-Exchange Flow ─────────────────────────
@mcp.tool()
async def get_cross_exchange_flow(symbol: str = "BTCUSDT") -> str:
    """Get Futures/Spot ratio, speculation index, and smart money divergence.
    
    Reveals whether the market is driven by speculation (Futures) or real demand (Spot).
    Futures/Spot > 8x = HYPER_SPECULATION (vulnerable to flush).
    Also shows smart money divergence: are top traders positioned opposite to the crowd?
    
    Args:
        symbol: Trading pair (default: BTCUSDT)
    """
    data = await _fetch(f"/v1/intelligence/cross-exchange-flow?symbol={symbol}")
    return json.dumps(data, indent=2)


# ─── Tool 8: Market Climate ──────────────────────────────
@mcp.tool()
async def get_market_climate() -> str:
    """Get current market mode and health status.
    
    Returns market mode (CHOP, TREND, RANGE) and health (HEALTHY, FRAGILE).
    CHOP = only scalps work, TREND = directional trades, RANGE = mean-reversion.
    If health is FRAGILE, reduce all position sizes.
    """
    data = await _fetch("/v1/intelligence/climate")
    return json.dumps(data, indent=2)


# ─── Tool 9: Ignition Detection ──────────────────────────
@mcp.tool()
async def get_ignitions() -> str:
    """Detect volatility ignition events — potential explosive price moves.
    
    Returns ignition state (DORMANT, RISING, IGNITED) and directional bias.
    IGNITED = imminent large move, reduce or exit positions.
    RISING = pressure building, prepare for breakout.
    """
    data = await _fetch("/v1/intelligence/ignitions")
    return json.dumps(data, indent=2)


# ─── Tool 10: Unified Market Intelligence ────────────────
@mcp.tool()
async def get_market_intelligence(symbol: str = "BTCUSDT") -> str:
    """Get complete market intelligence in a single call — combines all endpoints.
    
    Returns orderflow signal, composite score, liquidation zones, cross-exchange
    analysis, climate, and ignition state in one unified response. Use this
    for a comprehensive pre-trade check.
    
    Args:
        symbol: Trading pair (default: BTCUSDT)
    """
    data = await _fetch(f"/v1/intelligence/market-intelligence?symbol={symbol}")
    return json.dumps(data, indent=2)


# ─── Tool 11: Horus Cortex Cognitive Brain ────────────────
@mcp.tool()
async def get_horus_cortex() -> str:
    """
    Get the sovereign cognitive brain synthesis (Horus Cortex Symphony v3.0).
    Fuses 7 forensic evidence families with a real-time contradiction engine:
    1. Price Structure & 15m/1h momentum returns
    2. Dynamic Volume-Weighted Support & Resistance boundaries
    3. Orderflow aggressive taker imbalance
    4. Moving Average lagging confirmations
    5. Cycle Memory & boundary touch fatigue
    6. Market Breadth & Global Ignition
    7. Microstructure Spoofing and Absorption Anomaly Detection
    
    Returns:
    - regime_state: Current market regime (TRANSITION, EXPANSION, EXHAUSTION, BREAKDOWN)
    - trust_score: 0-100 penalized confidence score
    - action_policy: Exact autonomous bot sizing directives (ignition_multiplier, trend_multiplier, reversal_multiplier)
    - execution_boundaries: Exact USD invalidation support and breakout resistance levels
    - active_contradictions: Active conflicts between price and orderflow
    - narrative: Deterministic institutional Arabic & English narrative
    """
    data = await _fetch("/v1/intelligence/cortex")
    return json.dumps(data, indent=2)


# ─── Resource: API Info ───────────────────────────────────
@mcp.resource("horus://info")
async def get_api_info() -> str:
    """Information about the Horus Flow Intelligence system."""
    return json.dumps({
        "name": "Horus Flow & Cortex Intelligence",
        "version": "3.0.0",
        "provider": "HORUS TECH LTD",
        "mcp_name": "pro.horustek/horus-flow-mcp",
        "description": "Cognitive Market Brain and orderflow physics for Autonomous AI Agents",
        "supported_crypto": "All USDT pairs on Binance (BTC, ETH, SOL, BNB, XRP, etc.)",
        "supported_equities": "US stocks via IEX (SPY, AAPL, TSLA, NVDA, MSFT, AMZN, META, GOOGL)",
        "capabilities": [
            "Level 4 Horus Cortex Cognitive Brain",
            "Real-time Contradiction Engine (Price vs Flow)",
            "Whale detection and exit signals",
            "Spoofing and bid wall trap detection",
            "Liquidation heatmaps with dollar amounts",
            "Smart money divergence analysis",
            "Cross-exchange flow (Futures/Spot ratios)",
            "Market climate classification",
            "Volatility ignition detection",
            "Composite intelligence scoring (0-100)"
        ],
        "pricing": "Explorer (Free), Trader ($49/mo), Professional ($149/mo), Institutional ($499/mo)",
        "links": {
            "portal": "https://flow.horustek.pro",
            "rapidapi": "https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence",
            "pypi": "https://pypi.org/project/horus-flow-mcp/",
            "mcp_registry": "https://registry.modelcontextprotocol.io/?q=horus"
        }
    }, indent=2)


# ─── Entry Point ──────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Horus Flow MCP Server (Public)")
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="Transport mode: stdio (Claude Desktop) or sse"
    )
    parser.add_argument(
        "--port", type=int, default=8012,
        help="Port for SSE transport (default: 8012)"
    )
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", host="0.0.0.0", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
