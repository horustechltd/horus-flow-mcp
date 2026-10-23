<div align="center">
  <h1>🦅 HORUS CORTEX & FLOW</h1>
  <h3>The Cognitive Market Brain for Autonomous AI Trading Agents</h3>

  <p>
    <a href="https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp"><img src="https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp/badges/card.svg" alt="Glama Verified"></a>
    <a href="https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp"><img src="https://glama.ai/mcp/servers/horustechltd/horus-flow-mcp/badges/score.svg" alt="Glama Score"></a>
    <a href="https://aiagentslisting.com/mcp/horus-flow-mcp"><img src="https://aiagentslisting.com/horus-flow-mcp/badge.svg" alt="AI Agents Listing Verified"></a>
  </p>

  <p>
    <img src="https://img.shields.io/badge/Protocol-FastMCP%202.0-purple?style=for-the-badge&logo=anthropic" alt="FastMCP">
    <a href="https://flow.horustek.pro/status.html"><img src="https://img.shields.io/badge/Status-live%20page-brightgreen?style=for-the-badge" alt="Status"></a>
    <img src="https://img.shields.io/badge/Python-3.12+-blue?style=for-the-badge&logo=python" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License">
  </p>

  <p>
    <strong>Don't let your AI trading agents trade on lagging candlestick echoes. Give them the whale's eyes and an institutional cognitive mind.</strong>
  </p>
</div>

---

## 🤖 The Zero-Human Decision Loop in Action

When you connect **Claude Desktop**, **Cursor**, or an autonomous **LangChain / AutoGen** agent to Horus Cortex, your agent stops hallucinating and begins executing with Wall Street risk rigor:

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│  Autonomous Quant Agent (Claude 3.5 Sonnet / Cursor IDE) 🤖                                │
│                                                                                             │
│  Prompt: "BTC is pumping. Should we execute a 3x breakout long entry?"                      │
│                                                                                             │
│  AI Calls Tool: `get_horus_cortex()`                                                        │
│  ◀  Horus Cortex Returns:                                                                   │
│     {                                                                                       │
│       "regime_state": "TRANSITION",                                                         │
│       "trust_score": 26.5,                                                                  │
│       "action_policy": {                                                                    │
│         "directive": "Deteriorating Transition: Capital Preservation Lock (0.0x)",          │
│         "trend_allowed": false,                                                             │
│         "ignition_allowed": false                                                           │
│       },                                                                                    │
│       "market_vitals": { "taker_ratio": 0.24, "global_ignition": 0.08 },                    │
│       "active_contradictions": [                                                            │
│         { "id": "BULLISH_PRICE_vs_HOLLOW_BREADTH", "severity": "MEDIUM" }                   │
│       ],                                                                                    │
│       "execution_boundaries": {                                                             │
│         "invalidation_support": 77052.0,                                                    │
│         "breakout_resistance": 78608.0                                                      │
│       }                                                                                     │
│     }                                                                                       │
│                                                                                             │
│  AI Final Output:                                                                           │
│  "⛔ TRADE ABORTED — CAPITAL PRESERVATION ENFORCED.                                        │
│   Although spot price is making local highs, Horus Cortex flags a severe divergence:        │
│   1. Taker Buy/Sell ratio collapsed to 0.24 (Aggressive seller absorption).                 │
│   2. Global market breadth is dormant (0.08) indicating an isolated, hollow squeeze.        │
│   3. Cortex Trust Score is 26.5/100 with active trend locks enabled.                        │
│   Action: Standing aside. Re-evaluating only if price confirms above $78,608 with volume."  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛑 Stop Predicting Candles. Start Measuring Gravity.

Retail traders rely on lagging indicators (RSI, MACD, Moving Averages) which calculate what *has already happened*. 

**Horus is predictive, not reactive:**
1. **Level 1-2 Physics (The Eye):** Measures sub-second limit orderbook depth, spoofed liquidity walls, and aggressive taker execution delta before candlesticks print.
2. **Level 3 Forensics (The Radar):** Tracks Liquidation Cascades (Gravity Direction) and Spot vs. Futures Speculation Ratios.
3. **Level 4 Cortex (The Mind):** Synthesizes **7 independent evidence families** with a real-time **Contradiction Engine** to output machine-executable position sizing multipliers and USD invalidation boundaries.

---

## 🏗️ Architecture

```mermaid
graph TD
    %% Styling
    classDef crypto_stream fill:#F3BA2F,stroke:#000,color:#000,stroke-width:2px;
    classDef equity_stream fill:#000,stroke:#09b533,color:#09b533,stroke-width:2px;
    classDef compute fill:#1A1F36,stroke:#00D6FF,color:#fff,stroke-width:2px;
    classDef level3 fill:#1A1F36,stroke:#FF6B00,color:#fff,stroke-width:2px;
    classDef cortex fill:#4A154B,stroke:#FFD700,color:#fff,stroke-width:3px;
    classDef mcp fill:#632CA6,stroke:#fff,color:#fff,stroke-width:2px;
    classDef client fill:#FF3366,stroke:#fff,color:#fff,stroke-width:2px;

    %% Ingestion
    subgraph Data_Pipelines [Websocket Ingestion]
        B[Binance WSS <br/> L1/L2 Book]:::crypto_stream
        A[Alpaca WSS <br/> IEX Equities - sample]:::equity_stream
        BF[Binance Futures <br/> OI / Funding / Liquidations]:::crypto_stream
    end

    %% Level 1-2 Engine
    subgraph Core_Engine [Level 1-2: Microstructure Physics]
        IC[Imbalance Calculator <br/> Bid/Ask Walls]:::compute
        FC[Flow Calculator <br/> Tape Deltas]:::compute
        BC[Behavioral Court <br/> Spoofing & Absorption Rules]:::compute
    end

    %% Level 3 Intelligence
    subgraph L3_Engine [Level 3: Institutional Intelligence]
        LH[Liquidation Heatmap <br/> Gravity Zones]:::level3
        XF[Cross-Exchange Flow <br/> Spot ↔ Futures]:::level3
        CI[Composite Intelligence <br/> 4-Layer Verdict]:::level3
    end

    %% Level 4 Cognitive Cortex
    subgraph L4_Cortex [Level 4: The Sovereign Cognitive Cortex]
        HC[Horus Cortex Symphony 3.0 <br/> 7 Forensic Families + Contradiction Engine]:::cortex
        TS[Penalized Trust Score 0-100]:::compute
        EB[Execution Boundaries USD]:::compute
        AP[Action Policy Multipliers for Bots]:::compute
    end

    %% Output
    subgraph Output_Layer [Data Delivery & Agent Integration]
        MCP[AI Agent FastMCP Server <br/> 8 Sovereign Tools]:::mcp
        API[FastAPI REST Gateway <br/> 13 Endpoints]:::client
        Dash[Real-Time Portal <br/> Live Microstructure]:::client
    end

    B --> IC
    A --> IC
    B --> FC
    A --> FC
    BF --> LH
    BF --> XF

    IC --> BC
    FC --> BC
    LH --> CI
    XF --> CI
    BC --> CI

    CI --> HC
    HC --> TS
    HC --> EB
    HC --> AP

    HC --> MCP
    HC --> API
    BC --> Dash
```

---

## 📡 Complete API Catalog

### Level 1-2: Orderflow Microstructure
| Endpoint | Method | Description | Tier |
|:---|:---|:---|:---|
| `/v1/flow/crypto/{symbol}` | `GET` | Order book imbalance (top 20 levels) and taker flow from Binance's public stream. Any TRADING spot pair | Free: BTCUSDT, ETHUSDT · Builder: all pairs |
| `/v1/flow/crypto/{symbol}/history` | `GET` | Snapshots every 15s with price, deltas and ratios | Builder: 60 min · Pro: 24 h |
| `/v1/flow/equity/{symbol}` | `GET` | US equity flow from the IEX feed (about 3% of US volume, a sample) | Builder |
| `/v1/flow/equity/macro-blocks` | `GET` | SPY buy/sell skew and IEX prints of $200k or more | Free |
| `/v1/status` | `GET` | Freshness and uptime of every data source (no key) | Public |

### Level 3: Forensic Market Intelligence
| Endpoint | Method | Description | Tier |
|:---|:---|:---|:---|
| `/v1/intelligence/climate` | `GET` | WiseMan BTC regime and health | Builder |
| `/v1/intelligence/ignitions` | `GET` | Volatility breakout scanner across ~750 assets, refreshed every minute | Builder |
| `/v1/intelligence/liquidation-heatmap` | `GET` | Crowd positioning vs its 24h median and estimated liquidation levels (BTC, ETH, SOL) | Pro |
| `/v1/intelligence/cross-exchange-flow` | `GET` | Futures/spot volume ratio vs its 7-day median, premium, funding, OI velocity | Pro |
| `/v1/intelligence/composite` | `GET` | 0-100 score from climate, ignition, positioning and futures/spot flow | Pro |
| `/v1/intelligence/market-intelligence` | `GET` | All of the above for BTC, ETH and SOL in one call | Pro |

Every Level 3 document carries a `method` field with its exact formula. Endpoints return `503 data_stale` instead of serving data older than their freshness limit.

### Level 4: The Sovereign Cognitive Cortex
| Endpoint | Method | Description | Tier |
|:---|:---|:---|:---|
| `/v1/intelligence/cortex` | `GET` | Regime state, trust score, contradictions, execution boundaries and action policy | Pro |
| `/v1/intelligence/maestro` | `GET` | Backward-compatible alias for the Cortex endpoint | Pro |

---

## 🤖 Model Context Protocol (MCP) Setup

Horus provides an official FastMCP server compatible with **Claude Desktop**, **Cursor IDE**, and any MCP client:

### 1. Claude Desktop Configuration
Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "horus-cortex": {
      "command": "python3",
      "args": ["/absolute/path/to/horus_flow_api/horus_mcp.py", "--transport", "stdio"],
      "env": {
        "FLOW_MCP_KEY": "YOUR_HORUS_API_KEY"
      }
    }
  }
}
```

### 2. Available Sovereign Tools for AI Agents
1. `get_horus_cortex()`: 🧠 **Primary Cognitive Tool** — Full consensus, trust score (0-100), boundaries ($), and bot action multipliers.
2. `get_crypto_flow(symbol)`: Sub-second L2 orderflow and aggressive trade delta.
3. `get_equity_flow(symbol)`: US Equity block trades and tape prints.
4. `scan_crypto_flow(symbols)`: Batch scanner for active whale positioning.
5. `get_liquidation_heatmap(symbol)`: Liquidation cascade zones and gravitational pull.
6. `get_cross_exchange_flow(symbol)`: Spot vs Futures volume ratio and funding rate risk.
7. `get_composite_intelligence(symbol)`: 4-layer composite verdict (0-100).
8. `get_full_market_intelligence()`: Macro overview of all monitored instruments.

---

## ⚡ 60-Second Quant Bot Quickstart (Python)

```python
import requests

HEADERS = {"X-API-Key": "your_horus_api_key"}
BASE_URL = "https://flow.horustek.pro"

# 1. Query Horus Cortex for the Sovereign Market State
res = requests.get(f"{BASE_URL}/v1/intelligence/cortex", headers=HEADERS).json()

trust_score = res["trust_score"]
policy = res["action_policy"]
boundaries = res["execution_boundaries"]

print(f"🧠 Market State: {res['regime_state']} | Trust: {trust_score}/100")
print(f"🛡️ Action Directive: {policy['directive']}")
print(f"🎯 Support Invalidation: ${boundaries['invalidation_support']:,.0f} | Breakout Target: ${boundaries['breakout_resistance']:,.0f}")

# 2. Enforce Autonomous Risk Rules
if not policy["trend_allowed"]:
    print("⛔ Trade Rejected: Cortex forbids trend breakouts during transitions.")
else:
    position_multiplier = policy["trend_multiplier"]
    # execute_trade(multiplier=position_multiplier, stop_loss=boundaries["invalidation_support"])
```

---

## 💎 Institutional Subscription Tiers

| Feature | Explorer (Free) | Trader ($49/mo) | Professional ($149/mo) | Institutional ($499/mo) |
|:---|:---:|:---:|:---:|:---:|
| **Daily API Quota** | 100 calls/day | 1,000 calls/day | 5,000 calls/day | Unlimited |
| **Microstructure L2 Flow** | Top 3 Symbols | All Crypto Symbols | All Crypto + US Equity | All Instruments |
| **Whale Tape & Imbalances** | Basic | Real-Time | Real-Time Sub-ms | Priority Dedicated Socket |
| **Level 3 Intelligence** | ❌ | ❌ | ✅ Full Access | ✅ Full Access |
| **🧠 Level 4 Horus Cortex** | ❌ | ❌ | ✅ **Full Cognitive Brain** | ✅ **Full Cognitive Brain** |
| **Autonomous Bot Multipliers** | ❌ | ❌ | ✅ | ✅ |
| **AI Agent MCP Server** | Community | Community | ✅ Full FastMCP Access | ✅ Dedicated Private Server |
| **SLA & Support** | Community | Standard | Priority | 24/7 Dedicated Quant Desk |

---

## 🌐 Live Real-Time Dashboard
Explore the live institutional orderflow visualizer at [flow.horustek.pro/dash/](https://flow.horustek.pro/dash/).

---

*Engineered with mathematical rigor for Autonomous AI Agents and Quantitative Traders.*  
**© 2026 Horus Tech Ltd.** 🦅

---

*mcp-name: pro.horustek/horus-flow-mcp*
