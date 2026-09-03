# 🦅 Horus Flow Intelligence — MCP Server

[![smithery badge](https://smithery.ai/badge/horus-flow-mcp)](https://smithery.ai)
[![RapidAPI](https://img.shields.io/badge/RapidAPI-Get_API_Key-blue.svg)](https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence)
[![Developer Portal](https://img.shields.io/badge/Developer_Portal-Horus_Flow-black.svg)](https://flow.horustek.pro)

An official [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that empowers AI coding assistants (like Claude Desktop, Cursor, and Cline) with **Institutional-Grade Crypto & Equity Orderflow Intelligence**.

Rather than relying on lagging indicators (RSI, MACD), this MCP server gives your AI agents direct access to live Level 2 Orderbook imbalances and aggressive trade deltas (BUY vs SELL pressure) in milliseconds.

## 🔮 The Edge: Candlesticks vs. Horus Prediction

If your Agent is waiting for a candlestick to close to execute a trade, **it is reading history**. 
Traditional indicators are purely mathematical derivatives of *past* price action. 

**Horus Flow is predictive, not reactive.** 
By measuring the sub-second physics of the orderbook—detecting limit order walls, tracking whale spoofing, and calculating momentum acceleration—Horus anticipates the directional movement **before** the candlestick is fully formed.

When Horus triggers a `STRONG_BUY_PRESSURE` signal, it means institutional capital is aggressively absorbing liquidity *right now*. This allows your AI to execute entries seconds or minutes before the retail market reacts and the candlestick finally turns green. Stop letting your AI guess the next candle; let it measure the gravity that creates it.

## 🚀 Features Exposed to AI

Your AI Agent can now autonomously use these tools when analyzing markets or building trading bots for you:

1. `get_crypto_flow(symbol)`: Returns real-time Microstructure AI verdicts (`BUY_PRESSURE`, `SELL_PRESSURE`) based on live Binance L2 depth for any USDT pair.
2. `get_equity_flow(symbol)`: Returns live orderflow metrics for US Equities via Alpaca IEX.
3. `scan_crypto_flow(symbols)`: Scans multiple assets simultaneously to find the exact coin with the highest institutional buying momentum.

---

## 🔑 Prerequisites (API Key)

To use this MCP server, you must provide your AI agent with a valid **RapidAPI Key** from Horus Tech Ltd.

1. Go to the [Horus Flow Intelligence on RapidAPI](https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence)
2. Subscribe to a tier (Free and Pro tiers available).
3. Copy your `x-rapidapi-key`.

---

## 💻 Installation

### Option A: Cursor IDE
1. Open Cursor Settings (`Cmd + Shift + J` or `Ctrl + Shift + J`).
2. Navigate to **Features** > **MCP Servers**.
3. Click **+ Add New MCP Server**.
4. Set Name: `HorusFlow`
5. Set Type: `command`
6. Set Command: `python3 /absolute/path/to/horus_mcp_public.py --transport stdio`
7. Under Environment Variables, add: `RAPIDAPI_KEY` = `your-rapidapi-key-here`

### Option B: Claude Desktop
Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "horus-flow": {
      "command": "python3",
      "args": [
        "/absolute/path/to/horus_mcp_public.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "RAPIDAPI_KEY": "YOUR_RAPIDAPI_KEY_HERE"
      }
    }
  }
}
```

### Option C: Smithery (CLI)
You can install the server globally using the Smithery CLI:
```bash
npx @smithery/cli install horus-flow-mcp
# The installer will prompt you to enter your RAPIDAPI_KEY
```

---

## 🛠️ How to Prompt your AI

Once installed, simply ask your AI (Claude / Cursor):
> *"Can you write a Binance trading bot in Python? But before generating the buy conditions, use the Horus Flow tool to check the current orderflow for BTCUSDT. Only buy if the flow shows BUY_PRESSURE."*

The AI will intelligently fetch the live data, verify the institutional delta, and write the code accordingly!

---
© 2026 HORUS TECH LTD - The Backbone of Quantitative Execution
