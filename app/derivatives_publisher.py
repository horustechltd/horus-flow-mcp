# -*- coding: utf-8 -*-
"""
Horus Flow API — Derivatives Intelligence Publisher
====================================================
Rebuilds the data behind /v1/intelligence/cross-exchange-flow,
/liquidation-heatmap, /composite and /market-intelligence.

Every PUBLISH_INTERVAL seconds, for each symbol, it reads Binance public data
(spot + USD-M futures), computes three documents and writes them to Redis
with a TTL, so stale data expires instead of being served forever:

  horus:api:xflow:{SYMBOL}        spot vs futures activity, premium, funding, OI velocity
  horus:api:liq_heatmap:{SYMBOL}  crowd positioning and estimated liquidation levels
  horus:api:composite:{SYMBOL}    0-100 score combining climate, ignition, heatmap, xflow
  + one :summary key per family

These keys are owned by the API. The legacy horus:xflow:* / horus:liq_heatmap:* /
horus:composite:* keys read by the trading platform are NOT touched.

All formulas are documented in the "method" field of each document.
"""
import asyncio
import json
import logging
import math
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("API.DerivativesPublisher")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PUBLISH_INTERVAL = 60          # seconds between refreshes
KEY_TTL = 300                  # documents expire 5 min after the last refresh

KEY_XFLOW = "horus:api:xflow:{}"
KEY_HEATMAP = "horus:api:liq_heatmap:{}"
KEY_COMPOSITE = "horus:api:composite:{}"
KEY_PUBLISHER_HEARTBEAT = "horus:api:derivatives_publisher:heartbeat"

SPOT = "https://api.binance.com"
FAPI = "https://fapi.binance.com"


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _round_price(p: float) -> float:
    if p >= 1000:
        return round(p, 1)
    if p >= 10:
        return round(p, 2)
    if p >= 1:
        return round(p, 4)
    return round(p, 6)


def _pct(new: float, old: float) -> float:
    return (new - old) / old * 100 if old else 0.0


# ═══════════════════════════════════════════════════════════════
# Pure computations (unit-testable, no I/O)
# ═══════════════════════════════════════════════════════════════

def daily_ratio_baseline(spot_1d: List[list], fut_1d: List[list]) -> Optional[float]:
    """Median futures/spot quote-volume ratio over the last complete daily candles."""
    spot = {int(k[0]): _f(k[7]) for k in spot_1d[:-1]}   # drop today's partial candle
    fut = {int(k[0]): _f(k[7]) for k in fut_1d[:-1]}
    ratios = [fut[t] / spot[t] for t in spot if t in fut and spot[t] > 0]
    return statistics.median(ratios) if len(ratios) >= 3 else None


def compute_xflow(symbol: str, raw: Dict[str, Any], now: float) -> Dict[str, Any]:
    fut_qv = _f(raw["fut24"].get("quoteVolume"))
    spot_qv = _f(raw["spot24"].get("quoteVolume"))
    ratio = fut_qv / spot_qv if spot_qv > 0 else 0.0

    baseline = daily_ratio_baseline(raw.get("spot_1d", []), raw.get("fut_1d", []))
    rel = ratio / baseline if baseline else None
    if rel is None:
        market_type = "BALANCED"
    elif rel >= 1.5:
        market_type = "HYPER_SPECULATION"
    elif rel <= 0.67:
        market_type = "SPOT_DRIVEN"
    else:
        market_type = "BALANCED"

    mark = _f(raw["premium"].get("markPrice"))
    index = _f(raw["premium"].get("indexPrice"))
    premium_pct = _pct(mark, index)
    premium_bias = "BULLISH" if premium_pct >= 0.05 else "BEARISH" if premium_pct <= -0.05 else "NEUTRAL"
    funding = _f(raw["premium"].get("lastFundingRate"))

    oi_contracts = _f(raw["oi"].get("openInterest"))
    oi_usd = oi_contracts * mark
    hist_vals = [_f(x.get("sumOpenInterestValue")) for x in raw["oi_hist"]]
    oi_10m = _pct(hist_vals[-1], hist_vals[-3]) if len(hist_vals) >= 3 else 0.0
    oi_30m = _pct(hist_vals[-1], hist_vals[0]) if len(hist_vals) >= 7 else 0.0
    closes = [_f(k[4]) for k in raw["klines"]]
    px_10m = _pct(closes[-1], closes[-3]) if len(closes) >= 3 else 0.0

    if oi_10m <= -2.0:
        positioning = "MASS_DELEVERAGING"
    elif oi_10m >= 1.0 and px_10m >= 0.2:
        positioning = "AGGRESSIVE_POSITIONING_LONG"
    elif oi_10m >= 1.0 and px_10m <= -0.2:
        positioning = "AGGRESSIVE_POSITIONING_SHORT"
    else:
        positioning = "STABLE"

    if positioning == "MASS_DELEVERAGING":
        risk = f"EXTREME — Open interest fell {abs(oi_10m):.1f}% in 10 minutes; positions are being forced out."
    elif market_type == "HYPER_SPECULATION":
        risk = f"HIGH — Futures/spot volume ratio is {rel:.1f}x its 7-day median; the move is derivatives-led."
    elif market_type == "SPOT_DRIVEN":
        risk = f"LOW — Spot activity is leading; futures/spot ratio is {rel:.2f}x its 7-day median."
    elif baseline is None:
        risk = "MEDIUM — Not enough daily history to classify the futures/spot ratio."
    else:
        risk = "MEDIUM — Spot and futures activity are within their normal 7-day range."
    if abs(funding) >= 0.0005:
        risk += f" Funding is extreme ({funding * 100:+.3f}% per 8h)."

    return {
        "symbol": symbol,
        "futures_volume_24h": round(fut_qv, 2),
        "spot_volume_24h": round(spot_qv, 2),
        "futures_spot_volume_ratio": round(ratio, 3),
        "ratio_baseline_7d": round(baseline, 3) if baseline else None,
        "ratio_vs_baseline": round(rel, 3) if rel else None,
        "market_type": market_type,
        "premium_discount_pct": round(premium_pct, 4),
        "premium_bias": premium_bias,
        "funding_rate": funding,
        "oi_current": round(oi_usd, 2),
        "oi_velocity_10m_pct": round(oi_10m, 3),
        "oi_change_30m_pct": round(oi_30m, 3),
        "price_change_10m_pct": round(px_10m, 3),
        "positioning_signal": positioning,
        "risk_assessment": risk,
        "source": "Binance spot + USD-M futures public API",
        "method": (
            "market_type compares the futures/spot 24h volume ratio with its median over the last 7 complete days "
            "(>=1.5x HYPER_SPECULATION, <=0.67x SPOT_DRIVEN). premium_bias uses mark vs index "
            "(+/-0.05%). positioning_signal uses 10-minute open-interest change (+1% with price +/-0.2%, "
            "or -2% for MASS_DELEVERAGING)."
        ),
        "timestamp": now,
    }


def compute_heatmap(symbol: str, raw: Dict[str, Any], observed_liq: Dict[str, float], xflow: Dict[str, Any], now: float) -> Dict[str, Any]:
    price = _f(raw["premium"].get("markPrice"))
    gls_series = [_f(x.get("longShortRatio"), 1.0) for x in (raw["global_ls"] or []) if _f(x.get("longShortRatio")) > 0] or [1.0]
    tls_series = [_f(x.get("longShortRatio"), 1.0) for x in (raw["top_ls"] or []) if _f(x.get("longShortRatio")) > 0] or [1.0]
    gls, tls = gls_series[-1], tls_series[-1]
    gls_base, tls_base = statistics.median(gls_series), statistics.median(tls_series)
    taker = _f((raw["taker"] or [{}])[-1].get("buySellRatio"), 1.0) or 1.0

    # Binance's global account ratio sits structurally above 1 (retail leans long),
    # so the crowd is judged against its own 24h median, not against 1.0.
    crowd_rel = gls / gls_base if gls_base > 0 else 1.0
    top_rel = tls / tls_base if tls_base > 0 else 1.0
    if crowd_rel >= 1.35:
        crowd = "OVERLEVERAGED_LONG"
    elif crowd_rel >= 1.15:
        crowd = "LONG_HEAVY"
    elif crowd_rel <= 0.74:
        crowd = "OVERLEVERAGED_SHORT"
    elif crowd_rel <= 0.87:
        crowd = "SHORT_HEAVY"
    else:
        crowd = "BALANCED"

    smd = (crowd_rel >= 1.10 and top_rel <= 0.95) or (crowd_rel <= 0.91 and top_rel >= 1.05)

    crowd_tilt = _clamp(abs(math.log(crowd_rel)) / math.log(1.5))
    taker_tilt = _clamp(abs(taker - 1.0) / 0.5)
    oi_build = _clamp(max(_f(xflow.get("oi_change_30m_pct")), 0.0) / 3.0)
    score = round(0.5 * crowd_tilt + 0.3 * taker_tilt + 0.2 * oi_build, 3)

    if score < 0.3 or crowd == "BALANCED":
        gravity = "NEUTRAL"
    else:
        gravity = "DOWN" if crowd_rel > 1.0 else "UP"

    levs = (100, 50, 25, 10)
    long_zones = [_round_price(price * (1 - 1 / L)) for L in levs]
    short_zones = [_round_price(price * (1 + 1 / L)) for L in levs]
    nearest = long_zones[0] if gravity != "UP" else short_zones[0]

    if "OVERLEVERAGED" in crowd:
        risk = f"HIGH — Crowd is {crowd.replace('_', ' ').lower()}: global long/short {gls:.2f} vs 24h median {gls_base:.2f}; liquidation levels on that side are exposed."
    elif smd:
        risk = f"HIGH — Top traders ({top_rel:.2f}x their median) are moving against the crowd ({crowd_rel:.2f}x its median)."
    elif score >= 0.5:
        risk = f"MEDIUM — Positioning pressure {score:.2f} points {gravity}."
    else:
        risk = "LOW — Positioning is not stretched."

    return {
        "symbol": symbol,
        "current_price": _round_price(price),
        "gravity_direction": gravity,
        "gravity_score": score,
        "crowd_bias": crowd,
        "long_short_ratio_global": round(gls, 4),
        "long_short_ratio_top_traders": round(tls, 4),
        "long_short_ratio_global_median_24h": round(gls_base, 4),
        "long_short_ratio_top_traders_median_24h": round(tls_base, 4),
        "crowd_vs_median": round(crowd_rel, 3),
        "smart_money_divergence": bool(smd),
        "taker_buy_sell_ratio": round(taker, 4),
        "oi_change_30m_pct": xflow.get("oi_change_30m_pct", 0.0),
        "oi_current": xflow.get("oi_current", 0.0),
        "estimated_liquidation_zones": {
            "leverage": list(levs),
            "long_zones": long_zones,
            "short_zones": short_zones,
            "nearest_liq_price": nearest,
        },
        "observed_liquidations_5m": observed_liq,
        "risk_assessment": risk,
        "source": "Binance USD-M futures public API (5m ratios) + forceOrder stream",
        "method": (
            "crowd_bias compares the global long/short account ratio with its own 24h median (>=1.15x LONG_HEAVY, "
            ">=1.35x OVERLEVERAGED_LONG, mirrored for shorts). gravity_score = 0.5*crowd tilt (|ln(ratio vs median)| / ln 1.5) "
            "+ 0.3*taker imbalance (|buy/sell-1| / 0.5) "
            "+ 0.2*30-min OI build-up (/3%), each capped at 1. gravity_direction points at the crowded side's "
            "liquidation levels (DOWN when the crowd is long) and is NEUTRAL below 0.3 or when the crowd is BALANCED. Liquidation zones are "
            "approximate liquidation prices for positions opened at the current price with 100x/50x/25x/10x leverage."
        ),
        "timestamp": now,
    }


_MODE_W = {"TREND": 1.0, "TRENDING": 1.0, "BULLISH": 1.0, "RANGE": 0.6, "RANGING": 0.6,
           "CHOP": 0.35, "NO_TRADE": 0.0, "DUMP": 0.0, "UNKNOWN": 0.3}
_HEALTH_W = {"HEALTHY": 1.0, "ROBUST": 1.0, "NORMAL": 0.85, "DECAYING": 0.7, "FRAGILE": 0.6,
             "CRITICAL": 0.3, "UNKNOWN": 0.7}
_XFLOW_W = {"SPOT_DRIVEN": 1.0, "BALANCED": 0.75, "HYPER_SPECULATION": 0.4}


def compute_composite(symbol: str, climate: Optional[Dict[str, Any]], ignition: Optional[Dict[str, Any]],
                      heatmap: Dict[str, Any], xflow: Dict[str, Any], now: float) -> Dict[str, Any]:
    climate = climate or {}
    ignition = ignition or {}
    mode = str(climate.get("market_mode", "UNKNOWN")).upper()
    health = str(climate.get("health", "UNKNOWN")).upper()
    climate_score = 25 * _MODE_W.get(mode, 0.3) * _HEALTH_W.get(health, 0.7)

    ign = _f(ignition.get("global_ignition"), 0.0)
    ignition_score = 25 * _clamp(ign)

    gscore = _f(heatmap.get("gravity_score"))
    heatmap_score = 25 * (1 - gscore)
    if heatmap.get("smart_money_divergence"):
        heatmap_score *= 0.7
    if "OVERLEVERAGED" in str(heatmap.get("crowd_bias", "")):
        heatmap_score *= 0.6

    mt = xflow.get("market_type", "BALANCED")
    xflow_score = 25 * _XFLOW_W.get(mt, 0.75)
    if xflow.get("positioning_signal") == "MASS_DELEVERAGING":
        xflow_score *= 0.4
    if abs(_f(xflow.get("funding_rate"))) >= 0.0005:
        xflow_score *= 0.6

    total = round(climate_score + ignition_score + heatmap_score + xflow_score, 1)
    if total >= 80:
        verdict = "FULL_CONVICTION"
    elif total >= 60:
        verdict = "PARTIAL_CONVICTION"
    elif total >= 40:
        verdict = "NEUTRAL"
    else:
        verdict = "STAY_OUT"

    votes = 0
    votes += {"UP": 1, "DOWN": -1}.get(heatmap.get("gravity_direction"), 0)
    votes += {"BULLISH": 1, "BEARISH": -1}.get(xflow.get("premium_bias"), 0)
    votes += {"AGGRESSIVE_POSITIONING_LONG": 1, "AGGRESSIVE_POSITIONING_SHORT": -1}.get(xflow.get("positioning_signal"), 0)
    taker = _f(heatmap.get("taker_buy_sell_ratio"), 1.0)
    votes += 1 if taker >= 1.1 else -1 if taker <= 0.9 else 0
    direction = "LONG" if votes >= 2 else "SHORT" if votes <= -2 else "NEUTRAL"

    tags = []
    crowd = heatmap.get("crowd_bias", "BALANCED")
    if crowd != "BALANCED":
        tags.append(crowd.replace("_", " ").title())
    if mt != "BALANCED":
        tags.append(mt.replace("_", " ").title())
    if heatmap.get("gravity_direction") in ("UP", "DOWN"):
        tags.append(f"Gravity {heatmap['gravity_direction']}")
    word = {"LONG": "LONG", "SHORT": "SHORT"}.get(direction, "FLAT")
    one_liner = f"{word} {symbol} — " + (" + ".join(tags) if tags else "No stretched positioning")

    return {
        "symbol": symbol,
        "composite_score": total,
        "verdict": verdict,
        "direction": direction,
        "breakdown": {
            "climate_score": round(climate_score, 1),
            "ignition_score": round(ignition_score, 1),
            "heatmap_score": round(heatmap_score, 1),
            "xflow_score": round(xflow_score, 1),
        },
        "details": {
            "climate": f"{mode}/{health}(conf={int(_f(climate.get('confidence')) * 100)}%)",
            "ignition": f"{ignition.get('regime', 'UNKNOWN')}(ign={ign:.2f})",
            "heatmap": f"grav={heatmap.get('gravity_direction')}({gscore:.2f}),crowd={crowd},smd={heatmap.get('smart_money_divergence')}",
            "xflow": f"{mt},{xflow.get('positioning_signal')},fund={_f(xflow.get('funding_rate')):+.5f}",
        },
        "one_liner": one_liner,
        "method": (
            "Four components of 0-25 each. climate: WiseMan mode x health weight. ignition: global ignition x 25. "
            "heatmap: 25 x (1 - gravity_score), x0.7 on smart-money divergence, x0.6 when overleveraged. "
            "xflow: SPOT_DRIVEN 25, BALANCED 18.75, HYPER_SPECULATION 10, x0.4 on mass deleveraging, x0.6 on extreme funding. "
            "direction needs at least 2 net votes from gravity, premium, positioning and taker flow."
        ),
        "timestamp": now,
    }


# ═══════════════════════════════════════════════════════════════
# I/O
# ═══════════════════════════════════════════════════════════════

async def _get(session: aiohttp.ClientSession, url: str):
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} for {url.split('?')[0]}")
        return await r.json()


async def fetch_raw(session: aiohttp.ClientSession, symbol: str) -> Dict[str, Any]:
    urls = {
        "spot24": f"{SPOT}/api/v3/ticker/24hr?symbol={symbol}",
        "fut24": f"{FAPI}/fapi/v1/ticker/24hr?symbol={symbol}",
        "premium": f"{FAPI}/fapi/v1/premiumIndex?symbol={symbol}",
        "oi": f"{FAPI}/fapi/v1/openInterest?symbol={symbol}",
        "oi_hist": f"{FAPI}/futures/data/openInterestHist?symbol={symbol}&period=5m&limit=7",
        "global_ls": f"{FAPI}/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=5m&limit=288",
        "top_ls": f"{FAPI}/futures/data/topLongShortPositionRatio?symbol={symbol}&period=5m&limit=288",
        "spot_1d": f"{SPOT}/api/v3/klines?symbol={symbol}&interval=1d&limit=8",
        "fut_1d": f"{FAPI}/fapi/v1/klines?symbol={symbol}&interval=1d&limit=8",
        "taker": f"{FAPI}/futures/data/takerlongshortRatio?symbol={symbol}&period=5m&limit=1",
        "klines": f"{FAPI}/fapi/v1/klines?symbol={symbol}&interval=5m&limit=7",
    }
    names = list(urls)
    results = await asyncio.gather(*[_get(session, urls[n]) for n in names])
    return dict(zip(names, results))


def observed_liquidations(symbol: str) -> Dict[str, float]:
    """Liquidations seen on the forceOrder stream in the last 5 minutes."""
    try:
        from app.engines.derivatives_engine import derivatives_engine
        events = list(derivatives_engine._liquidations.get(symbol, []))
    except Exception:
        events = []
    now = time.time()
    recent = [e for e in events if now - e.timestamp <= 300]
    return {
        "long_liquidated_usd": round(sum(e.notional for e in recent if e.side == "SELL"), 2),
        "short_liquidated_usd": round(sum(e.notional for e in recent if e.side == "BUY"), 2),
        "count": len(recent),
    }


async def _read_json(redis, key: str) -> Optional[Dict[str, Any]]:
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _fresh(doc: Optional[Dict[str, Any]], max_age: float) -> Optional[Dict[str, Any]]:
    """Return doc only if its timestamp is recent enough."""
    if not doc:
        return None
    ts = doc.get("timestamp_epoch", doc.get("timestamp"))
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    if not isinstance(ts, (int, float)) or time.time() - ts > max_age:
        return None
    return doc


async def publish_once(redis, session: aiohttp.ClientSession) -> Dict[str, str]:
    """Compute and write every document once. Returns per-symbol status."""
    status: Dict[str, str] = {}
    now = time.time()
    iso = datetime.now(timezone.utc).isoformat()
    climate = _fresh(await _read_json(redis, "hta:state:wiseman_climate"), 900)
    ignition = _fresh(await _read_json(redis, "horus:global_ignition_state"), 600)

    summaries = {"xflow": {}, "heatmap": {}, "composite": {}}
    for sym in SYMBOLS:
        try:
            raw = await fetch_raw(session, sym)
            xflow = compute_xflow(sym, raw, now)
            heatmap = compute_heatmap(sym, raw, observed_liquidations(sym), xflow, now)
            composite = compute_composite(sym, climate, ignition, heatmap, xflow, now)

            pipe = redis.pipeline()
            pipe.set(KEY_XFLOW.format(sym), json.dumps(xflow), ex=KEY_TTL)
            pipe.set(KEY_HEATMAP.format(sym), json.dumps(heatmap), ex=KEY_TTL)
            pipe.set(KEY_COMPOSITE.format(sym), json.dumps(composite), ex=KEY_TTL)
            await pipe.execute()

            summaries["xflow"][sym] = {"market_type": xflow["market_type"], "premium_bias": xflow["premium_bias"],
                                       "positioning": xflow["positioning_signal"], "funding": xflow["funding_rate"],
                                       "risk": xflow["risk_assessment"]}
            summaries["heatmap"][sym] = {"gravity_direction": heatmap["gravity_direction"],
                                         "gravity_score": heatmap["gravity_score"], "crowd_bias": heatmap["crowd_bias"],
                                         "smart_money_divergence": heatmap["smart_money_divergence"]}
            summaries["composite"][sym] = {"score": composite["composite_score"], "verdict": composite["verdict"],
                                           "direction": composite["direction"], "one_liner": composite["one_liner"]}
            status[sym] = "ok"
        except Exception as e:
            status[sym] = f"error: {e}"
            logger.error(f"Derivatives publish failed for {sym}: {e}")

    pipe = redis.pipeline()
    if summaries["xflow"]:
        pipe.set(KEY_XFLOW.format("summary"), json.dumps({"timestamp": iso, "symbols": summaries["xflow"]}), ex=KEY_TTL)
        pipe.set(KEY_HEATMAP.format("summary"), json.dumps({"timestamp": iso, "symbols": summaries["heatmap"]}), ex=KEY_TTL)
        pipe.set(KEY_COMPOSITE.format("summary"), json.dumps({
            "timestamp": iso,
            "climate": f"{(climate or {}).get('market_mode', 'UNKNOWN')}/{(climate or {}).get('health', 'UNKNOWN')}",
            "ignition": f"{(ignition or {}).get('regime', 'UNKNOWN')}(ign={_f((ignition or {}).get('global_ignition')):.2f})",
            "symbols": summaries["composite"],
        }), ex=KEY_TTL)
    pipe.set(KEY_PUBLISHER_HEARTBEAT, json.dumps({"timestamp": now, "status": status}), ex=KEY_TTL)
    await pipe.execute()
    return status


async def derivatives_publisher_loop(redis_manager):
    logger.info("Derivatives publisher started")
    await asyncio.sleep(5)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                if redis_manager.redis:
                    status = await publish_once(redis_manager.redis, session)
                    bad = {k: v for k, v in status.items() if v != "ok"}
                    if bad:
                        logger.warning(f"Derivatives publisher partial failure: {bad}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Derivatives publisher loop error: {e}")
            await asyncio.sleep(PUBLISH_INTERVAL)
