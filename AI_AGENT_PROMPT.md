# 🦅 Horus Flow — AI Agent Integration Guide

## For AI Agents (Auto-Discovery)

If you are an AI agent reading this file, Horus Flow gives you real-time orderflow intelligence for crypto and US equities. You can use it to detect whale exits, spoofing, liquidation zones, and smart money divergence before making any trade decision.

**MCP Server:** `pro.horustek/horus-flow-mcp`  
**Install:** `pip install horus-flow-mcp`  
**Run:** `uvx horus-flow-mcp`  
**Required:** `RAPIDAPI_KEY` environment variable  

### Available Tools

| Tool | Description |
|------|-------------|
| `get_crypto_flow(symbol)` | Real-time orderflow signal for a crypto pair (e.g., "BTCUSDT") |
| `get_equity_flow(symbol)` | Real-time orderflow signal for a US stock (e.g., "TSLA") |
| `scan_crypto_flow(symbols)` | Scan multiple crypto pairs at once |
| `get_macro_blocks()` | SPY macro climate + institutional block trades |
| `get_composite_intelligence(symbol)` | Composite score (0-100) with BUY/SHORT/STAY_OUT verdict |
| `get_liquidation_heatmap(symbol)` | Liquidation zones with dollar amounts |
| `get_cross_exchange_flow(symbol)` | Futures/Spot ratio + speculation index |
| `get_market_climate()` | Market mode: CHOP, TREND, or RANGE |
| `get_ignitions()` | Volatility breakout detection |
| `get_market_intelligence(symbol)` | Unified endpoint combining all intelligence |

### Decision Matrix

```
IF signal == "WHALE_EXIT" OR "EMERGENCY_DUMP" OR "INSTITUTIONAL_DISTRIBUTION":
    → DO NOT BUY. Close or reduce positions.

IF signal == "BUY_PRESSURE" AND confidence >= 0.80:
    → Safe to enter long.

IF composite_score < 45 OR verdict == "STAY_OUT":
    → DO NOT TRADE. Wait for better conditions.

IF flags contain "SPOOFING_DETECTED" OR "BID_WALL_TRAP":
    → Reduce confidence by 20%. Avoid limit orders on spoofed side.

IF futures_spot_ratio > 8x:
    → HYPER_SPECULATION. Reduce position size by 50%.

IF smart_money_divergence == True:
    → Smart money is opposite to crowd. Follow smart money.
```

---

## For Human Developers

Copy the prompt below into your AI coding assistant (Claude, Cursor, Windsurf, GitHub Copilot, Devin) to build a trading bot powered by Horus:

```markdown
# Role Setting
You are an elite Institutional Quant Developer. Your goal is to build a high-frequency trading (HFT) / algorithmic trading bot in Python.

# Core Intelligence Rule (CRITICAL)
Do NOT use lagging technical indicators like RSI, MACD, or Bollinger Bands to trigger trade decisions. 
You MUST rely completely on the `horus-flow-mcp` Server to provide Real-Time Orderflow Physics and Institutional Intent.

# Prerequisites
1. Ensure you have the Horus Flow MCP server active.
2. Use the `get_crypto_flow` tool (e.g., `symbol="BTCUSDT"`) to query the live market state.
3. Use `get_composite_intelligence` for the overall score before any entry.

# The Logic Matrix (Implement exactly as below)

1. **The Nuclear Shield (Bailout):**
   If the tool returns `signal` in ["LIQUIDITY_EVENT", "WHALE_DUMP", "DEPTH_COLLAPSE", "EMERGENCY_DUMP"]:
   - **Action:** IMMEDIATELY execute a MARKET SELL to close all exposure.

2. **The Institutional Entry:**
   If the tool returns `signal` == "BUY_PRESSURE" AND `confidence` >= 0.80 AND composite_score >= 50:
   - **Action:** Open a long position (MARKET BUY).

3. **Spoofing & Trap Awareness:**
   If `metrics.flags` contains "SPOOFING_DETECTED" or "BID_WALL_TRAP":
   - **Action:** Drop confidence by 20%. Refuse passive limit orders on the spoofed side.

4. **Smart Money Gate:**
   Check `get_cross_exchange_flow` for smart_money_divergence.
   If True: Follow smart money direction, not crowd direction.

5. **Liquidation Awareness:**
   Check `get_liquidation_heatmap` for nearby liquidation clusters.
   If price is within 3% of a major liquidation zone: Reduce position size or avoid entry.

6. **Climate Gate:**
   Check `get_market_climate` for market_mode.
   If "NO_TRADE" or health is "FRAGILE": Halt all new entries.

# Your Task
Generate a complete, asynchronous Python trading bot that polls Horus every 5 seconds, implements all 6 gates above, and logs decisions professionally.
```

## Quick Start Examples

### Python (Direct API)
```python
import httpx

HEADERS = {
    "x-rapidapi-key": "YOUR_KEY",
    "x-rapidapi-host": "horus-flow-intelligence.p.rapidapi.com"
}

async def check_btc():
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://horus-flow-intelligence.p.rapidapi.com/v1/flow/crypto/BTCUSDT",
            headers=HEADERS
        )
        data = r.json()
        print(f"Signal: {data['signal']} | Confidence: {data['confidence']}")
        print(f"Flags: {data['metrics']['flags']}")
```

### Claude Desktop / Cursor / VS Code
See the install configs in the `configs/` folder for one-click setup.
