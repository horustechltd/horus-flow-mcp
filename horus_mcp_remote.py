# -*- coding: utf-8 -*-
"""
Horus Flow — Remote MCP server (Streamable HTTP)
================================================
Endpoint:  https://flow.horustek.pro/mcp
Auth:      RapidAPI subscribers send `X-RapidAPI-Key: <key>` (calls go through RapidAPI and its plans).
           Horus keys go as `X-API-Key: <key>` or `Authorization: Bearer <key>`.
           Without a key the server answers on the free tier (order flow for any pair,
           public track record, US session context, first 3 scanner results).

Every tool is read-only and proxies the local Horus Flow API with the caller's key,
so plans and rate limits apply per caller. Outputs are compact JSON built for LLM
context windows.

Run: python horus_mcp_remote.py   (listens on 127.0.0.1:8013, nginx proxies /mcp)
"""
import contextvars
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

API = os.getenv("HORUS_API_BASE", "http://127.0.0.1:8011")
PORT = int(os.getenv("HORUS_MCP_REMOTE_PORT", "8013"))
PUBLIC_HOSTS = ["flow.horustek.pro", "www.flow.horustek.pro"]


def _env_from_file(name: str) -> str:
    if os.getenv(name):
        return os.getenv(name)
    try:
        for line in (Path(__file__).parent / ".env").read_text().splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


ANON_KEY = _env_from_file("FLOW_MCP_KEY")  # free-tier key used when the caller sends none
_caller_key: contextvars.ContextVar[str] = contextvars.ContextVar("caller_key", default="")

INSTRUCTIONS = """Horus Flow gives you live crypto market microstructure and US equity session context.

How to use it well:
- To find where to look, call scan_market (about 190 markets ranked by buyers, sellers, volume surge, breakouts).
- Start with get_market_overview for BTC, ETH and 8 other majors, or get_crypto_flow for one pair.
- Every directional reading carries `reliability`: its measured hit rate from the live track record.
  Many signals score close to 50%, a coin flip. Treat them as context for your own reasoning, never as
  an instruction to trade. get_track_record shows the full numbers.
- Before acting on US stocks call get_us_market_session (hours, holidays, halts). US equity flow is an
  IEX sample (about 3% of volume).
- get_recent_events returns what changed since your last check (liquidation cascades, regime changes,
  new halts). Pass the last id you saw.
- Data refreshes: order flow live, derivatives every 60s, Cortex every few seconds. Every response says
  how old it is.
- On free plans, paid tools return a reduced live preview with an `upgrade` block (what is limited,
  which plan unlocks it, where to subscribe). Tell the user when a preview limits your answer.
This is market data, not financial advice."""

mcp = FastMCP(
    "Horus Flow",
    instructions=INSTRUCTIONS,
    website_url="https://flow.horustek.pro",
    host="127.0.0.1",
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=PUBLIC_HOSTS + ["127.0.0.1:*", "localhost:*"],
        allowed_origins=["https://flow.horustek.pro", "http://127.0.0.1:*", "http://localhost:*"],
    ),
)

RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


def _key_from(ctx: Optional[Context]) -> str:
    try:
        req = ctx.request_context.request if ctx else None
        if req is not None:
            k = req.headers.get("x-api-key") or ""
            auth = req.headers.get("authorization") or ""
            if not k and auth.lower().startswith("bearer "):
                k = auth[7:].strip()
            if k:
                return k
    except Exception:
        pass
    return _caller_key.get() or ANON_KEY


RAPIDAPI_HOST = "horus-flow-intelligence.p.rapidapi.com"
RAPIDAPI_LISTING = "https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence"


def _rapidapi_key_from(ctx: Optional[Context]) -> str:
    """RapidAPI subscribers send their RapidAPI key; we route their calls through RapidAPI
    so their plan and billing stay on RapidAPI."""
    try:
        req = ctx.request_context.request if ctx else None
        return (req.headers.get("x-rapidapi-key") or "").strip() if req is not None else ""
    except Exception:
        return ""


async def _get(ctx: Optional[Context], path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rapid_key = _rapidapi_key_from(ctx)
    if rapid_key:
        base, headers = f"https://{RAPIDAPI_HOST}", {"x-rapidapi-key": rapid_key, "x-rapidapi-host": RAPIDAPI_HOST}
    else:
        key = _key_from(ctx)
        base, headers = API, ({"X-API-Key": key} if key else {})
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(f"{base}{path}", params={k: v for k, v in (params or {}).items() if v is not None}, headers=headers)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:500]}
    if r.status_code == 200:
        return body
    detail = body.get("detail", body) if isinstance(body, dict) else body
    out = {"error": True, "status": r.status_code, "detail": detail}
    if r.status_code in (401, 403):
        out["hint"] = ("Your plan does not include this, or the key is not valid. Without a key you are on the free tier. "
                       f"Subscribe on RapidAPI ({RAPIDAPI_LISTING}) and send your key as the X-RapidAPI-Key header, "
                       "or use a Horus key as X-API-Key.")
    elif r.status_code == 404 and rapid_key:
        out["hint"] = "This endpoint is not enabled on the RapidAPI listing yet."
    elif r.status_code == 503:
        out["hint"] = "The upstream data is stale or loading; Horus refuses to serve old data. Retry in a minute."
    elif r.status_code == 202:
        out["hint"] = "Symbol was just added to live tracking. Retry in 5 seconds."
    raise ToolError(json.dumps(out))


def _pick(d: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    return {k: d.get(k) for k in keys if k in d}


# ─────────────────────────── tools ───────────────────────────
@mcp.tool(annotations=RO, structured_output=True)
async def get_crypto_flow(symbol: str = "BTCUSDT", ctx: Context = None) -> dict[str, Any]:
    """Live order flow for one Binance spot pair: signal, direction, 30-second buy/sell delta in USD,
    order book depth ratio, large sells in the last 5 minutes, and the signal's measured hit rate.
    Use for "what is the market doing right now in X". Symbols like BTCUSDT, ETHUSDT, SOLUSDT."""
    return await _get(ctx, f"/v1/flow/crypto/{symbol.upper().replace('/', '').replace('-', '')}", {"view": "compact"})


@mcp.tool(annotations=RO, structured_output=True)
async def get_flow_history(symbol: str = "BTCUSDT", minutes: int = 60, ctx: Context = None) -> dict[str, Any]:
    """Recent order-flow snapshots (every 15s) for a crypto pair with a summary: signal counts, price change,
    cumulative 30s delta. Use to see whether pressure is building or fading. minutes up to 60 (TRADER / RapidAPI PRO) or 1440 (PRO / RapidAPI ULTRA); free plans get the last 15 minutes."""
    r = await _get(ctx, f"/v1/flow/crypto/{symbol.upper()}/history", {"minutes": minutes})
    if r.get("error"):
        return r
    hist = r.get("history", [])
    prices = [h.get("price") for h in hist if h.get("price")]
    counts: Dict[str, int] = {}
    for h in hist:
        counts[h.get("signal")] = counts.get(h.get("signal"), 0) + 1
    step = max(1, len(hist) // 30)
    return {
        "symbol": r.get("symbol"), "minutes": minutes, "snapshots": len(hist),
        "summary": {
            "price_first": prices[0] if prices else None, "price_last": prices[-1] if prices else None,
            "price_change_pct": round((prices[-1] / prices[0] - 1) * 100, 3) if len(prices) > 1 else None,
            "signal_counts": counts,
            "sum_delta_30s_usd": round(sum(h.get("delta_30s") or 0 for h in hist), 0),
        },
        "sampled": [_pick(h, "_ts", "signal", "direction_bias", "price", "delta_30s", "buy_sell_ratio") for h in hist[::step]][-30:],
    }


@mcp.tool(annotations=RO, structured_output=True)
async def get_market_overview(ctx: Context = None) -> dict[str, Any]:
    """One call for the crypto market: BTC climate, ignition regime, Cortex regime, and for 10 majors the
    composite score, derivatives positioning (crowd vs its 24h median, liquidation gravity), futures/spot
    activity and open interest across Binance, Bybit and OKX. Full: PRO / RapidAPI ULTRA; lower plans get a BTCUSDT preview."""
    r = await _get(ctx, "/v1/intelligence/market-intelligence")
    if r.get("error"):
        return r
    syms = {}
    for s, d in (r.get("symbols") or {}).items():
        c, x, h = d.get("composite", {}), d.get("xflow", {}), d.get("heatmap", {})
        syms[s] = {
            "composite_score": c.get("composite_score"), "verdict": c.get("verdict"), "direction": c.get("direction"),
            "crowd_bias": h.get("crowd_bias"), "gravity": h.get("gravity_direction"), "price": h.get("current_price"),
            "market_type": x.get("market_type"), "funding_rate": x.get("funding_rate"),
            "oi_change_30m_pct": x.get("oi_change_30m_pct"),
            "total_oi_usd_3_venues": (x.get("cross_venue") or {}).get("total_oi_usd"),
        }
    cl, ig, cx = r.get("climate") or {}, r.get("ignition") or {}, r.get("cortex") or {}
    return {
        "generated_utc": r.get("timestamp_utc"),
        "btc_climate": _pick(cl, "market_mode", "health", "confidence"),
        "ignition": _pick(ig, "regime", "regime_bias", "global_ignition"),
        "cortex": {"state": cx.get("state"), "trust_score": cx.get("trust_score")},
        "symbols": syms,
        "stale_excluded": r.get("stale_excluded"),
    }


@mcp.tool(annotations=RO, structured_output=True)
async def get_derivatives(symbol: str = "BTCUSDT", ctx: Context = None) -> dict[str, Any]:
    """Derivatives positioning for one of 10 majors: funding (per venue and OI-weighted), open interest and its
    10/30-minute change, futures/spot volume vs its 7-day median, crowd long/short vs its 24h median, top-trader
    divergence, estimated liquidation levels, liquidations seen in the last 5 minutes. Full: PRO / RapidAPI ULTRA; lower plans get a BTCUSDT preview."""
    s = symbol.upper()
    x = await _get(ctx, "/v1/intelligence/cross-exchange-flow", {"symbol": s})
    if x.get("error"):
        return x
    try:
        h = await _get(ctx, "/v1/intelligence/liquidation-heatmap", {"symbol": s})
    except ToolError:
        h = {"error": True}
    return {
        "symbol": s,
        "futures_spot": _pick(x, "market_type", "futures_spot_volume_ratio", "ratio_baseline_7d", "premium_discount_pct", "premium_bias"),
        "funding_rate": x.get("funding_rate"),
        "open_interest": _pick(x, "oi_current", "oi_velocity_10m_pct", "oi_change_30m_pct", "positioning_signal"),
        "cross_venue": x.get("cross_venue"),
        "positioning": None if h.get("error") else _pick(h, "crowd_bias", "crowd_vs_median", "long_short_ratio_global",
                                                          "long_short_ratio_top_traders", "smart_money_divergence",
                                                          "gravity_direction", "gravity_score", "taker_buy_sell_ratio"),
        "liquidation_levels": None if h.get("error") else h.get("estimated_liquidation_zones"),
        "liquidations_5m": None if h.get("error") else h.get("observed_liquidations_5m"),
        "risk": x.get("risk_assessment"),
        "freshness_ms": x.get("freshness_ms"),
    }


@mcp.tool(annotations=RO, structured_output=True)
async def get_cortex(ctx: Context = None) -> dict[str, Any]:
    """Horus Cortex: the BTC market regime, trust score (0-100), active contradictions between evidence
    families, invalidation and breakout levels, and position-size multipliers by strategy type. Full: PRO / RapidAPI ULTRA; lower plans get regime, trust score and headline."""
    r = await _get(ctx, "/v1/intelligence/cortex")
    if r.get("error"):
        return r
    n = r.get("narrative") or {}
    return {
        "regime_state": r.get("regime_state"), "transition_direction": r.get("transition_direction"),
        "trust_score": r.get("trust_score"), "headline": n.get("headline_en"),
        "summary": n.get("summary_english"),
        "action_policy": r.get("action_policy"), "execution_boundaries": r.get("execution_boundaries"),
        "contradictions": [{"id": c.get("contradiction_id"), "severity": c.get("severity"), "description": c.get("description_en")}
                           for c in (r.get("active_contradictions") or [])][:5],
        "market_vitals": r.get("market_vitals"), "freshness_ms": r.get("freshness_ms"),
    }


@mcp.tool(annotations=RO, structured_output=True)
async def get_ignitions(limit: int = 10, ctx: Context = None) -> dict[str, Any]:
    """Volatility-breakout scanner across ~750 crypto assets, refreshed every minute: global regime and the
    assets with the highest ignition score (0-1). A ranking of breakout conditions, not a probability. Full: TRADER / RapidAPI PRO; free plans get the top 3."""
    r = await _get(ctx, "/v1/intelligence/ignitions")
    if r.get("error"):
        return r
    return {"regime": r.get("regime"), "regime_bias": r.get("regime_bias"),
            "global_ignition_score": r.get("global_ignition_score"), "summary": r.get("summary"),
            "top": (r.get("top_ignitions") or [])[:max(1, min(limit, 20))]}


@mcp.tool(annotations=RO, structured_output=True)
async def scan_market(preset: str = "buyers_in_control", limit: int = 10, min_volume_24h_usd: float = 5_000_000,
                      ctx: Context = None) -> dict[str, Any]:
    """Scan about 190 Binance perpetual markets in one call and get a ranked list. preset is one of:
    buyers_in_control, sellers_in_control, volume_surge, breakout_candidates, crowded_funding, top_movers.
    Each row: price, 15m and 1h change, aggressive buy share, net taker flow in USD, volume surge, funding,
    ignition score, and Horus live flow with its measured hit rate where Horus tracks the pair.
    Use it to find where to look before calling get_crypto_flow or get_derivatives on a specific market.
    Rankings of current conditions, not predictions. Free plans: 3 rows; TRADER / RapidAPI PRO and above: up to 100."""
    r = await _get(ctx, "/v1/scan", {"preset": preset, "limit": max(1, min(limit, 50)), "min_volume_24h": min_volume_24h_usd})
    return {k: r[k] for k in ("preset", "criteria", "coverage", "count", "results", "note", "upgrade") if k in r}


@mcp.tool(annotations=RO, structured_output=True)
async def get_track_record(signal: Optional[str] = None, window: str = "30d", ctx: Context = None) -> dict[str, Any]:
    """Measured hit rates of Horus signals at 1, 5, 15 and 30 minutes (window 30d or all), from every signal
    recorded live since August 2026. Pass a signal name (e.g. STRONG_BUY_PRESSURE) for just that signal.
    Use this to decide how much weight to give a reading. Free."""
    r = await _get(ctx, "/v1/track-record", {"window": window})
    if r.get("error"):
        return r
    if signal:
        return {"signal": signal, "window": window, "stats": (r.get("by_signal") or {}).get(signal.upper()),
                "coin_flip": 0.5, "method": r.get("method")}
    return {"window": window, "ledger": r.get("ledger"), "overall_5m": (r.get("overall") or {}).get("5m"),
            "by_signal_5m": {k: v.get("5m") for k, v in (r.get("by_signal") or {}).items()},
            "by_confidence_5m": {k: v.get("5m") for k, v in (r.get("by_confidence") or {}).items()},
            "coin_flip": 0.5, "method": r.get("method")}


@mcp.tool(annotations=RO, structured_output=True)
async def get_signal_ledger(symbol: str = "BTCUSDT", start: Optional[str] = None, end: Optional[str] = None,
                            limit: int = 200, ctx: Context = None) -> dict[str, Any]:
    """Point-in-time ledger: every signal Horus emitted for BTCUSDT, ETHUSDT or SOLUSDT between start and end
    (ISO dates, max 31 days), with the price and what the market did 1/5/15/30 minutes later. For backtesting. Full: TRADER / RapidAPI PRO; free plans get 20 signals from the last 24 hours."""
    return await _get(ctx, "/v1/track-record/signals", {"symbol": symbol.upper(), "start": start, "end": end, "limit": min(limit, 1000)})


@mcp.tool(annotations=RO, structured_output=True)
async def get_recent_events(since_id: int = 0, types: Optional[str] = None, limit: int = 50, ctx: Context = None) -> dict[str, Any]:
    """What changed since your last check: liquidation cascades, strong flow signals, composite changes, Cortex
    regime changes, climate changes, ignition alerts, US session changes, new US trading halts. Pass the last
    event id you saw as since_id. types is a comma-separated filter. Full: TRADER / RapidAPI PRO; free plans get the last 3 events, 15 minutes late."""
    return await _get(ctx, "/v1/events", {"since_id": since_id, "types": types, "limit": min(limit, 200)})


@mcp.tool(annotations=RO, structured_output=True)
async def get_us_market_session(ctx: Context = None) -> dict[str, Any]:
    """US equity market right now: session phase (pre-market, regular, after-hours, closed), holidays and early
    closes, next open and close in New York time, minutes to close, and currently active trading halts.
    Call this before reasoning about US stock trades. Free."""
    return await _get(ctx, "/v1/equity/session")


@mcp.tool(annotations=RO, structured_output=True)
async def get_cross_asset(ctx: Context = None) -> dict[str, Any]:
    """BTC order flow side by side with US equities flow (SPY, QQQ) and crypto-linked stocks and ETFs
    (COIN, MSTR, IBIT): are crypto and stocks risk-on together, risk-off together, or diverging? When US
    markets are closed, says so and keeps BTC as the live gauge. Equity flow is an IEX sample. Full: TRADER / RapidAPI PRO; free plans get SPY and QQQ only."""
    return await _get(ctx, "/v1/cross-asset")


@mcp.tool(annotations=RO, structured_output=True)
async def get_equity_flow(symbol: str = "SPY", ctx: Context = None) -> dict[str, Any]:
    """Order flow for one US stock or ETF from the IEX feed (about 3% of US volume, a sample): signal, buy/sell
    ratio, delta, large IEX prints. Extreme verdicts are capped because of the sample size. Full: TRADER / RapidAPI PRO; free plans get SPY and QQQ."""
    r = await _get(ctx, f"/v1/flow/equity/{symbol.upper()}")
    if r.get("error"):
        return r
    m = r.get("metrics") or {}
    return {**_pick(r, "symbol", "signal", "direction_bias", "confidence", "risk", "explanation", "timestamp_utc"),
            "buy_sell_ratio_30s": m.get("buy_sell_ratio"), "delta_30s_usd": m.get("delta_30s"), "flags": m.get("flags"),
            "data_source": r.get("data_source")}


@mcp.tool(annotations=RO, structured_output=True)
async def get_service_status(ctx: Context = None) -> dict[str, Any]:
    """Freshness and uptime of every Horus data source. Check this if a tool returns data_stale. Free."""
    r = await _get(ctx, "/v1/status")
    if r.get("error"):
        return r
    return {"overall": r.get("overall"),
            "components": [_pick(c, "name", "status", "age_seconds", "uptime_24h_pct") for c in r.get("components", [])]}


INFO = {
    "name": "Horus Flow MCP server",
    "transport": "streamable-http",
    "endpoint": "https://flow.horustek.pro/mcp",
    "auth": ("RapidAPI subscribers: header X-RapidAPI-Key: <your RapidAPI key>. Horus keys: X-API-Key or "
             "Authorization: Bearer. Without a key the free tier applies."),
    "subscribe": "https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence",
    "connect": {
        "claude_code": "claude mcp add --transport http horus-flow https://flow.horustek.pro/mcp --header \"X-RapidAPI-Key: YOUR_RAPIDAPI_KEY\"",
        "mcp_json": {"mcpServers": {"horus-flow": {"type": "http", "url": "https://flow.horustek.pro/mcp",
                                                    "headers": {"X-RapidAPI-Key": "YOUR_RAPIDAPI_KEY"}}}},
    },
    "tools": ["scan_market", "get_crypto_flow", "get_flow_history", "get_market_overview", "get_derivatives", "get_cortex",
              "get_ignitions", "get_track_record", "get_signal_ledger", "get_recent_events", "get_us_market_session",
              "get_cross_asset", "get_equity_flow", "get_service_status"],
    "docs": "https://flow.horustek.pro/llms.txt",
    "track_record": "https://flow.horustek.pro/v1/track-record",
    "status": "https://flow.horustek.pro/status.html",
    "note": "This URL speaks the MCP protocol. Open it from an MCP client, not a browser.",
}

INFO_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Horus Flow MCP</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--text:#1d1d1b;--muted:#6b6b66;--line:#e4e3df;--code:#f0efeb}
@media (prefers-color-scheme:dark){:root{--bg:#0e0f12;--panel:#16181d;--text:#ecebe7;--muted:#9a9890;--line:#2a2d34;--code:#1f2228}}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 16px 48px}h1{font-size:22px;margin:0 0 6px}
p{color:var(--muted)}section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}
h2{font-size:15px;margin:0 0 8px}pre{background:var(--code);padding:10px 12px;border-radius:8px;overflow-x:auto;font-size:13px;margin:6px 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}a{color:inherit}ul{margin:6px 0;padding-left:18px}
</style></head><body><main>
<h1>Horus Flow MCP server</h1>
<p>This address speaks the Model Context Protocol (Streamable HTTP). Add it to an MCP client; a browser cannot use it directly.</p>
<section><h2>Endpoint</h2><pre><code>https://flow.horustek.pro/mcp</code></pre>
<p>RapidAPI subscribers: add the header <code>X-RapidAPI-Key: YOUR_RAPIDAPI_KEY</code>. Your RapidAPI plan applies.
Horus keys: <code>X-API-Key: YOUR_KEY</code>. Without a key you get the free tier.
<a href="https://rapidapi.com/horus-tech-ltd-horus-tech-ltd-default/api/horus-flow-intelligence">Subscribe on RapidAPI</a>.</p></section>
<section><h2>Claude Code</h2><pre><code>claude mcp add --transport http horus-flow https://flow.horustek.pro/mcp --header "X-RapidAPI-Key: YOUR_RAPIDAPI_KEY"</code></pre></section>
<section><h2>Any MCP client</h2><pre><code>{
  "mcpServers": {
    "horus-flow": {
      "type": "http",
      "url": "https://flow.horustek.pro/mcp",
      "headers": { "X-RapidAPI-Key": "YOUR_RAPIDAPI_KEY" }
    }
  }
}</code></pre></section>
<section><h2>14 read-only tools</h2><ul>
<li>Market scanner across about 190 perpetual markets</li>
<li>Crypto order flow, flow history, market overview, derivatives across Binance, Bybit and OKX, Cortex, ignitions</li>
<li>Track record and point-in-time signal ledger</li>
<li>Recent events, US market session and halts, cross-asset view, US equity flow, service status</li></ul>
<p><a href="/llms.txt">llms.txt</a> · <a href="/v1/track-record">Track record</a> · <a href="/status.html">Status</a></p></section>
</main></body></html>"""


class FriendlyGet:
    """Plain GET/HEAD on /mcp without text/event-stream (a browser, curl, a link checker) gets a description
    instead of the protocol's 406. MCP traffic (POST, or GET accepting text/event-stream) is untouched."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD") and scope["path"].rstrip("/") == "/mcp":
            accept = dict((k.decode().lower(), v.decode()) for k, v in scope["headers"]).get("accept", "")
            if "text/event-stream" not in accept:
                html = "text/html" in accept
                body = (INFO_HTML if html else json.dumps(INFO, indent=2)).encode()
                ctype = b"text/html; charset=utf-8" if html else b"application/json"
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", ctype), (b"cache-control", b"no-store"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})
                return
        await self.inner(scope, receive, send)


app = FriendlyGet(mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info", proxy_headers=True, forwarded_allow_ips="127.0.0.1")
