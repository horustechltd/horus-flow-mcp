# How to Install Horus Flow MCP Server

## Quick Install (All Platforms)

```bash
pip install horus-flow-mcp
```

Or run directly without installing:

```bash
uvx horus-flow-mcp
```

## Required Environment Variable

```
RAPIDAPI_KEY=your_key_here
```

Get your free API key at: https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence

## Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "horus-flow": {
      "command": "uvx",
      "args": ["horus-flow-mcp"],
      "env": {
        "RAPIDAPI_KEY": "your_key_here"
      }
    }
  }
}
```

Config location:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

## Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "horus-flow": {
      "command": "uvx",
      "args": ["horus-flow-mcp"],
      "env": {
        "RAPIDAPI_KEY": "your_key_here"
      }
    }
  }
}
```

## VS Code (GitHub Copilot)

Add to VS Code `settings.json`:

```json
{
  "github.copilot.chat.mcp.servers": {
    "horus-flow": {
      "command": "uvx",
      "args": ["horus-flow-mcp"],
      "env": {
        "RAPIDAPI_KEY": "your_key_here"
      }
    }
  }
}
```

## Windsurf / Other MCP Clients

Command: `uvx horus-flow-mcp`
Environment: `RAPIDAPI_KEY=your_key_here`
Transport: stdio

## Verify Installation

After setup, ask your AI assistant:
> "What is the current BTC orderflow signal?"

It should return a real-time signal with confidence score and market flags.

## Available Tools

| Tool | What It Does |
|------|-------------|
| `get_crypto_flow` | Crypto orderflow signal (BTC, ETH, SOL...) |
| `get_equity_flow` | US equity orderflow (SPY, AAPL, TSLA...) |
| `scan_crypto_flow` | Scan multiple crypto pairs at once |
| `get_macro_blocks` | SPY trend + institutional block trades |
| `get_composite_intelligence` | Score (0-100) + BUY/SHORT/STAY_OUT |
| `get_liquidation_heatmap` | Where leveraged positions will be liquidated |
| `get_cross_exchange_flow` | Futures/Spot ratio + smart money divergence |
| `get_market_climate` | Market mode: CHOP/TREND/RANGE |
| `get_ignitions` | Volatility breakout detection |
| `get_market_intelligence` | All intelligence in one call |
