# -*- coding: utf-8 -*-
"""
Horus Flow Intelligence — MCP Server (Public Distribution)
===========================================================
This is the official Model Context Protocol (MCP) Server for
Horus Flow Intelligence. It exposes institutional-grade crypto
and equity orderflow signals directly to AI coding assistants.

Requirements:
- pip install mcp httpx
- A valid RapidAPI Key

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
    """Get real-time institutional orderflow signal for a cryptocurrency."""
    clean = symbol.replace("/", "").replace("-", "").upper()
    data = await _fetch(f"/v1/flow/crypto/{clean}")
    return json.dumps(data, indent=2)


# ─── Tool 2: Equity Flow ─────────────────────────────────
@mcp.tool()
async def get_equity_flow(symbol: str) -> str:
    """Get real-time institutional orderflow signal for a US equity stock."""
    clean = symbol.upper()
    data = await _fetch(f"/v1/flow/equity/{clean}")
    return json.dumps(data, indent=2)


# ─── Tool 3: Multi-Symbol Scanner ────────────────────────
@mcp.tool()
async def scan_crypto_flow(symbols: str = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT") -> str:
    """Scan multiple cryptocurrencies for orderflow signals simultaneously."""
    import asyncio
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    
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
        "strongest_buy": next((r["symbol"] for r in results if r.get("signal") == "BUY_PRESSURE"), None),
        "strongest_sell": next((r["symbol"] for r in results if r.get("signal") == "SELL_PRESSURE"), None),
        "results": results,
    }
    return json.dumps(summary, indent=2)

@mcp.tool()
async def get_macro_blocks() -> str:
    """
    Get the overall US Equity Market Macro Trend (based on SPY orderflow) and recent Institutional Block Trades (Whales).
    Use this to understand market sentiment and where big money is flowing in the US Stock Market.
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


# ─── Resource: API Info ───────────────────────────────────
@mcp.resource("horus://info")
async def get_api_info() -> str:
    """Information about the Horus Flow Intelligence system."""
    return json.dumps({
        "name": "Horus Flow Intelligence",
        "version": "1.0.0",
        "provider": "HORUS TECH LTD",
        "description": "Real-time institutional orderflow engine for Crypto & Equities via RapidAPI",
        "supported_crypto": "All USDT pairs on Binance",
        "supported_equities": "US stocks via IEX"
    }, indent=2)


# ─── Entry Point (FIXED SSE VERSION) ──────────────────────
def main():
    parser = argparse.ArgumentParser(description="Horus Flow MCP Server (Public)")
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="Transport mode: stdio (Claude Desktop) or sse"
    )
    # ملاحظة: FastMCP يتعامل مع المنفذ والـ host داخلياً أو عبر متغيرات البيئة
    args = parser.parse_args()

    if args.transport == "sse":
        # تم إصلاح الخطأ هنا: إزالة host و port لتوافق مكتبة mcp الحديثة
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
