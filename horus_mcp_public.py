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
        "⚠️  WARNING: RAPIDAPI_KEY environment variable is missing.\n"
        "Tools will return an authentication error when called.\n"
        "To use this MCP server, obtain an API Key from:\n"
        "https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence",
        file=sys.stderr
    )

HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": RAPIDAPI_HOST
}

# ─── MCP Server Instance ─────────────────────────────────
mcp = FastMCP(
    "Horus Flow Intelligence",
    instructions=(
        "Real-time institutional orderflow intelligence for Crypto & Equities. "
        "Powered by live Binance L2 orderbook depth and aggressive trade feeds. "
        "Detects BUY_PRESSURE, SELL_PRESSURE, institutional spoofing, and "
        "liquidity imbalances in milliseconds."
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

    The response includes:
    - signal: BUY_PRESSURE / SELL_PRESSURE / NEUTRAL
    - confidence: 0.0 to 1.0 AI confidence score
    - market_state: TRENDING_UP / TRENDING_DOWN / RANGE_BOUND / VOLATILE
    - risk: LOW / MEDIUM / HIGH / EXTREME
    - bid_ratio: orderbook bid imbalance (>1 = more bids than asks)
    - buy_ratio: aggressive buy percentage (>0.7 = heavy buying)
    - delta_5s: net volume delta over last 5 seconds

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


# ─── Resource: API Info ───────────────────────────────────
@mcp.resource("horus://info")
async def get_api_info() -> str:
    """Information about the Horus Flow Intelligence system."""
    return json.dumps({
        "name": "Horus Flow Intelligence",
        "version": "1.0.0",
        "provider": "HORUS TECH LTD",
        "description": "Real-time institutional orderflow engine for Crypto & Equities via RapidAPI",
        "supported_crypto": "All USDT pairs on Binance (e.g., BTCUSDT, ETHUSDT, SOLUSDT)",
        "supported_equities": "US stocks via IEX (e.g., AAPL, NVDA, TSLA)",
        "marketing": "To increase rate limits, upgrade your RapidAPI subscription.",
    }, indent=2)


# ─── Entry Point ──────────────────────────────────────────
if __name__ == "__main__":
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
