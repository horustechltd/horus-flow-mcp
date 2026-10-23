# -*- coding: utf-8 -*-
"""
Horus Flow — Remote MCP server (Streamable HTTP)
================================================
Endpoint:  https://flow.horustek.pro/mcp
Auth:      send your Horus key as `X-API-Key: <key>` or `Authorization: Bearer <key>`.
           Without a key the server answers on the free tier (BTCUSDT and ETHUSDT flow,
           public track record, US session context).

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


async def _get(ctx: Optional[Context], path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = _key_from(ctx)
    headers = {"X-API-Key": key} if key else {}
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(f"{API}{path}", params={k: v for k, v in (params or {}).items() if v is not None}, headers=headers)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:500]}
    if r.status_code == 200:
        return body
    detail = body.get("detail", body) if isinstance(body, dict) else body
    out = {"error": True, "status": r.status_code, "detail": detail}
    if r.status_code == 403:
        out["hint"] = ("Your plan does not include this. Without a key you are on the free tier. "
                       "Plans and keys: https://flow.horustek.pro")
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
    cumulative 30s delta. Use to see whether pressure is building or fading. minutes up to 60 (BUILDER) or 1440 (PRO)."""
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
    activity and open interest across Binance, Bybit and OKX. PRO plan."""
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
    divergence, estimated liquidation levels, liquidations seen in the last 5 minutes. PRO plan."""
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
    families, invalidation and breakout levels, and position-size multipliers by strategy type. PRO plan."""
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
    assets with the highest ignition score (0-1). A ranking of breakout conditions, not a probability. BUILDER plan."""
    r = await _get(ctx, "/v1/intelligence/ignitions")
    if r.get("error"):
        return r
    return {"regime": r.get("regime"), "regime_bias": r.get("regime_bias"),
            "global_ignition_score": r.get("global_ignition_score"), "summary": r.get("summary"),
            "top": (r.get("top_ignitions") or [])[:max(1, min(limit, 20))]}


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
    (ISO dates, max 31 days), with the price and what the market did 1/5/15/30 minutes later. For backtesting. BUILDER plan."""
    return await _get(ctx, "/v1/track-record/signals", {"symbol": symbol.upper(), "start": start, "end": end, "limit": min(limit, 1000)})


@mcp.tool(annotations=RO, structured_output=True)
async def get_recent_events(since_id: int = 0, types: Optional[str] = None, limit: int = 50, ctx: Context = None) -> dict[str, Any]:
    """What changed since your last check: liquidation cascades, strong flow signals, composite changes, Cortex
    regime changes, climate changes, ignition alerts, US session changes, new US trading halts. Pass the last
    event id you saw as since_id. types is a comma-separated filter. BUILDER plan."""
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
    markets are closed, says so and keeps BTC as the live gauge. Equity flow is an IEX sample. BUILDER plan."""
    return await _get(ctx, "/v1/cross-asset")


@mcp.tool(annotations=RO, structured_output=True)
async def get_equity_flow(symbol: str = "SPY", ctx: Context = None) -> dict[str, Any]:
    """Order flow for one US stock or ETF from the IEX feed (about 3% of US volume, a sample): signal, buy/sell
    ratio, delta, large IEX prints. Extreme verdicts are capped because of the sample size. BUILDER plan."""
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


app = mcp.streamable_http_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info", proxy_headers=True, forwarded_allow_ips="127.0.0.1")
