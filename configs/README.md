# Horus Flow MCP — One-Click Install Configs

## Prerequisites

1. Get your free API key from [RapidAPI](https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence)
2. Replace `YOUR_RAPIDAPI_KEY_HERE` with your actual key in the config file

---

## Claude Desktop

Copy `claude_desktop_config.json` content into your Claude Desktop config:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

Then restart Claude Desktop. You'll see "Horus Flow" in the MCP tools list.

---

## Cursor

Copy `cursor_mcp.json` content into your Cursor MCP config:

- Open Cursor Settings → MCP → Add Server
- Or manually edit `~/.cursor/mcp.json`

---

## VS Code (GitHub Copilot)

Add the content of `vscode_settings.json` to your VS Code `settings.json`:

- Open VS Code → `Cmd/Ctrl + Shift + P` → "Open User Settings (JSON)"
- Paste the `github.copilot.chat.mcp.servers` block

---

## Windsurf / Other MCP Clients

Use the same config format — the command is always:
```
uvx horus-flow-mcp
```
with `RAPIDAPI_KEY` as the environment variable.

---

## Verify It Works

After setup, ask your AI assistant:
> "What is the current BTC orderflow signal?"

It should call the `get_crypto_flow` tool and return a real-time signal like `BUY_PRESSURE`, `SELL_PRESSURE`, or `WHALE_EXIT`.
