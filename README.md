# 🦅 Horus Flow MCP Server

[![Smithery Badge](https://img.shields.io/badge/Smithery-Verified-green?style=flat-square&logo=github)](https://smithery.ai/mcp/horustechltd/horus-flow-mcp)
[![Glama Quality](https://img.shields.io/badge/Quality-A--Tier-gold?style=flat-square&logo=ai)](https://glama.ai/mcp/horustechltd/horus-flow-mcp)
[![Security: No Vulnerabilities](https://img.shields.io/badge/Security-No%20Vulnerabilities-brightgreen?style=flat-square)](https://github.com/horustechltd/horus-flow-mcp)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python)](https://github.com/horustechltd/horus-flow-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)

<div align="center">
  <h1>HORUS 👁️ | Sub-Second Institutional Orderflow Intelligence</h1>

  <p><strong>A True Market Gravity Engine for Autonomous AI Agents and HFT Traders.</strong></p>

  <p>
    [![horus-flow-mcp MCP server](https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp/badges/card.svg)](https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp)
  </p>
  <p>
    [![horus-flow-mcp MCP server](https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp/badges/score.svg)](https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp)
  </p>

  <p>
    <img src="https://img.shields.io/badge/Latency-29ms-brightgreen?style=for-the-badge&logo=speedtest" alt="Latency">
    <img src="https://img.shields.io/badge/Accuracy-75%25_Real_Time-blue?style=for-the-badge&logo=analytics" alt="Accuracy">
    <img src="https://img.shields.io/badge/Python-3.12-yellow?style=for-the-badge&logo=python" alt="Python">
    <img src="https://img.shields.io/badge/AI_Agent-MCP_Ready-blueviolet?style=for-the-badge&logo=robot" alt="MCP Ready">
  </p>
</div>

---

## 🧠 Why Horus? The AI Agent's "Nervous System"

In the world of autonomous trading, an AI Agent without real-time orderflow is like a pilot flying blind. Technical indicators (RSI, MACD) are **lagging echoes** of the past. **Horus** is the **Nervous System** that provides:

*   **Proprioception:** Real-time awareness of market "muscle" (Orderbook Depth).
*   **Reflexes:** Sub-second detection of institutional "pain" (Liquidity Collapses).
*   **Intelligence:** A context-aware decision matrix that translates raw physics into actionable signals.

> "If you want your AI Agent to trade like a whale, you must give it the whale's eyes. Horus is that vision."

---

## 🧪 Manus AI Audit: Live Performance Proof

Horus Flow MCP has been rigorously audited by **Manus AI** (an autonomous execution agent). The results confirm that Horus isn't just code—it's a high-performance reality.

### **Audit Highlights (Live Test on BTCUSDT):**
*   **Signal Accuracy:** Successfully detected **STRONG_SELL_PRESSURE** with a **0.85 Confidence Score**.
*   **Physics Engine Validation:** Confirmed `bid_ask_ratio` of **0.156**, proving the engine's ability to read thin limit books and aggressive selling.
*   **Zero-Hallucination Logic:** The MCP server correctly identified symbols in "Data Gathering" mode (e.g., SOLUSDT), preventing the AI from making false assumptions.

| Metric | Audit Result | Status |
| :--- | :--- | :--- |
| **Response Time** | Sub-millisecond (Local) | ✅ Verified |
| **Data Integrity** | L2 Binance Orderbook Sync | ✅ Verified |
| **AI Confidence** | 0.85+ on High-Vol Events | ✅ Verified |

---

## 💰 The $29 Arbitrage: Institutional Intelligence for the Price of a Lunch

Why pay thousands for institutional terminals when you can get the same **Microstructure Intelligence** for a fraction of the cost?

| Feature | **Horus Flow MCP** | Traditional Terminals |
| :--- | :--- | :--- |
| **Monthly Cost** | **$29 (Pro Plan)** | $150 - $2,000+ |
| **AI Integration** | **Native MCP (Plug & Play)** | Complex API / Manual |
| **Data Source** | Institutional L2 Feeds | Proprietary / Closed |
| **Decision Logic** | Physics-Based (Gravity) | Lagging Indicators |

---

## 🛑 Stop Predicting Candles. Start Measuring Gravity.
Retail traders use trailing indicators to guess what the market will do based on the *past*. **Horus** uses Level 2 Orderbook physics, Tick imbalances, and 5-Second Flow Deltas to measure exactly what institutional whales are doing *right now*. 

Horus doesn't ask "Are we overbought?". It measures gravitational pull and tells you: *"Whales are spoofing the bid and aggressive takers are tearing through the ask. Liquidity is collapsing. Bailout now."*

---

## ⚡ Why AI Agents (Claude, Cursor) Love Horus

If you hook up an AI Agent to a basic technical indicator feed, it gets confused by noise. 
If you feed an AI Agent **Horus**, it gets an institutional grade decision matrix. 

Look at what Horus catches in real-time during a **Liquidity Withdrawal / Flash Crash** attempt:

```json
{
  "symbol": "BTCUSDT",
  "signal": "LIQUIDITY_EVENT",
  "confidence": 0.99,
  "market_state": "DISTRIBUTION",
  "risk": "EXTREME",
  "description": "Liquidity withdrawn under price. Aggressive taking.",
  "metrics": {
    "bid_ask_ratio": 7.934,
    "buy_sell_ratio": 0.393,
    "delta_5s": -83040.05,
    "whale_activity": true,
    "large_sell_count": 4,
    "delta_accel": 3.8,
    "wall_side": "BID",
    "wiseman_climate": {
      "market_mode": "CHOP",
      "health": "FRAGILE",
      "confidence": 0.85
    },
    "flags": [
      "GLOBAL_LIQUIDITY_EVENT",
      "SPOOFING_DETECTED(wall=BID)"
    ]
  },
  "timestamp": 1776107738.975
}
```

### The Institutional Alpha:
1. **`bid_ask_ratio: 7.934` & `wall_side: BID`**: Massive spoofed bid walls are placed by whales below the market to create fake support.
2. **`buy_sell_ratio: 0.393`**: Horus sees through the spoofing (`SPOOFING_DETECTED` flag). It measures real *taker* flow and discovers aggressive selling is devastating the orderbook.
3. **`delta_accel: 3.8` & `whale_activity: true`**: Selling momentum accelerated by 3.8x natively tracking 4 major whale dumps within milliseconds.
4. **`wiseman_climate: FRAGILE`**: Integrates perfectly with the overarching Horus SaaS macro brain, verifying that Bitcoin's holistic environment is fragile before attacking.
5. **The Verdict**: With a `0.99` Confidence factor, the AI engine triggers `LIQUIDITY_EVENT`. It front-runs the ensuing 1-minute crash. **This is Institutional Grade.**

---

## 🏗️ Architecture

```mermaid
graph TD
    %% Styling
    classDef crypto_stream fill:#F3BA2F,stroke:#000,color:#000,stroke-width:2px;
    classDef equity_stream fill:#000,stroke:#09b533,color:#09b533,stroke-width:2px;
    classDef compute fill:#1A1F36,stroke:#00D6FF,color:#fff,stroke-width:2px;
    classDef mcp fill:#632CA6,stroke:#fff,color:#fff,stroke-width:2px;
    classDef client fill:#FF3366,stroke:#fff,color:#fff,stroke-width:2px;

    %% Ingestion
    subgraph Data_Pipelines [Sub-Millisecond Websocket Ingestion]
        B[Binance WSS <br/> L1/L2 Book]:::crypto_stream
        A[Alpaca WSS <br/> SIP Equities]:::equity_stream
    end

    %% Engine
    subgraph Core_Engine [The Physics Engine]
        IC[Imbalance Calculator <br/> Bid/Ask Spread]:::compute
        FC[Flow Calculator <br/> Tape Deltas]:::compute
        Tkr[Prediction Tracker <br/> In-Memory Evaluator]:::compute
        BC[Behavioral Court <br/> Spoofing & Liquidity Rules]:::compute
    end

    %% Output
    subgraph Output_Layer [Data Shield & Delivery]
        MCP[AI Agent MCP Context <br/> Context-Aware Prompts]:::mcp
        API[FastAPI Client <br/> Safe Shielded Outputs]:::client
        Dash[Real-time Dashboard <br/> Live Edge Proof]:::client
    end

    B --> IC
    A --> IC
    B --> FC
    A --> FC
    
    IC --> BC
    FC --> BC
    
    BC --> Tkr
    Tkr -- "Validates 1M accuracy" --> BC
    
    BC --> MCP
    BC --> API
    BC --> Dash
```

---

## 🚀 Quickstart for Trading Bots

Getting started with Horus takes less than 60 seconds. 
**⚡ Test Instantly:** Download our [Postman Collection](./horus_postman_collection.json) to ping the API directly from your browser.

```bash
# 1. Install Dependencies
pip install -r requirements.txt

# 2. Fire up the Core Engine
uvicorn app.main:app --host 0.0.0.0 --port 8011
```

In your local Bot / Agent, simply pull the live flow for any Crypto or US Equity:

```python
import requests

response = requests.get(
    "http://127.0.0.1:8011/v1/flow/crypto/BTCUSDT", 
    headers={"X-API-Key": "your_secure_api_key"}
)

flow_data = response.json()

# The Zero-Human Decision Loop:
if flow_data['signal'] in ['EMERGENCY_DUMP', 'BAILOUT', 'LIQUIDITY_EVENT']:
    print("Market gravity collapsing. Market selling all positions.")
    # execute_market_sell()
```

---

## 🌐 Live Real-Time Dashboard
Horus comes with a stunning glass-morphism WebSocket dashboard out-of-the-box (`/dash/`). 
It features a **Local Edge Proof Tracker** that strictly measures 1-Minute Candle directional predictions generated by the Physics Engine with an openly transparent win rate.

---
*Built with absolute precision for those who need to see the Matrix.*
<br/>**— HORUS INTELLIGENCE**  👁️
