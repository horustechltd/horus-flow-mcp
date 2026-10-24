"""
Offline tests for the Horus Flow API upgrade.
No network to production services, no shared Redis: an in-memory FakeRedis
replaces redis_manager.redis and market data is synthetic.
Run:  WORK=<copy of horus_flow_api> python3 -m pytest -q test_upgrade.py
"""
import asyncio
import fnmatch
import json
import os
import sys
import time
from pathlib import Path

import pytest

WORK = Path(os.environ["WORK"]).resolve()
TESTS = Path(__file__).resolve().parent

KEYS = {
    "demo": "demo-public-key",
    "free": "free-key-123",
    "mcp": "mcp-public-key",
    "builder": "builder-key-123",
    "pro": "pro-key-123",
    "admin": "admin-internal-key",
}
os.environ.update({
    "FLOW_API_KEY_1": KEYS["demo"], "FLOW_API_TIER_1": "demo",
    "FLOW_API_KEY_2": KEYS["admin"], "FLOW_API_TIER_2": "admin",
    "FLOW_API_KEY_3": KEYS["mcp"], "FLOW_API_TIER_3": "mcp_public",
    "FLOW_API_KEY_4": KEYS["free"], "FLOW_API_TIER_4": "free",
    "FLOW_API_KEY_5": KEYS["builder"], "FLOW_API_TIER_5": "builder",
    "FLOW_API_KEY_6": KEYS["pro"], "FLOW_API_TIER_6": "pro",
    "RAPIDAPI_PROXY_SECRET": "test-proxy-secret",
    "HORUS_TEST_INSTANCE": "1",
    "HORUS_DB_PATH": str(TESTS / "test_subscribers.db"),
    "OPS_TELEGRAM_CHAT_ID": "",
})
for k in ("FLOW_API_KEY_7", "FLOW_API_KEY_8"):
    os.environ.pop(k, None)

os.chdir(WORK)
sys.path.insert(0, str(WORK))

from fastapi.testclient import TestClient  # noqa: E402
import app.main as main  # noqa: E402
from app import auth  # noqa: E402
from app.redis_client import redis_manager  # noqa: E402
from app.feeds.binance_ws import ws_manager  # noqa: E402
from app.feeds.alpaca_ws import alpaca_ws_manager  # noqa: E402
import app.feeds.binance_ws as binance_ws_mod  # noqa: E402
try:
    from app import derivatives_publisher as dp  # noqa: E402
except ImportError:  # baseline code: lets the suite run to show which behaviours change
    import types
    dp = types.SimpleNamespace(KEY_XFLOW="horus:api:xflow:{}", KEY_HEATMAP="horus:api:liq_heatmap:{}",
                               KEY_COMPOSITE="horus:api:composite:{}", KEY_TTL=300)


# ─────────────────────────── Fake Redis ───────────────────────────
class FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def __getattr__(self, name):
        def call(*a, **kw):
            self.ops.append((name, a, kw))
            return self
        return call

    async def execute(self):
        out = []
        for name, a, kw in self.ops:
            out.append(await getattr(self.r, name)(*a, **kw))
        self.ops = []
        return out


class FakeRedis:
    def __init__(self):
        self.kv, self.ttl, self.hashes, self.zsets, self.lists = {}, {}, {}, {}, {}

    def _alive(self, k):
        exp = self.ttl.get(k)
        if exp and exp < time.time():
            self.kv.pop(k, None)
            self.ttl.pop(k, None)
        return k in self.kv

    async def get(self, k):
        return self.kv[k] if self._alive(k) else None

    async def set(self, k, v, ex=None, nx=False):
        if nx and self._alive(k):
            return None
        self.kv[k] = v if isinstance(v, str) else str(v)
        if ex:
            self.ttl[k] = time.time() + ex
        else:
            self.ttl.pop(k, None)
        return True

    async def setex(self, k, ex, v):
        return await self.set(k, v, ex=ex)

    async def hgetall(self, k):
        return dict(self.hashes.get(k, {}))

    async def hincrby(self, k, f, n=1):
        h = self.hashes.setdefault(k, {})
        h[f] = str(int(h.get(f, 0)) + n)
        return int(h[f])

    async def pfadd(self, k, *vals):
        self.lists.setdefault(k, [])
        for v in vals:
            if v not in self.lists[k]:
                self.lists[k].append(v)

    async def pfcount(self, k):
        return len(self.lists.get(k, []))

    async def scan_iter(self, pattern="*", count=None):
        for k in list(self.kv) + list(self.hashes):
            if fnmatch.fnmatch(k, pattern):
                yield k

    async def type(self, k):
        return "hash" if k in self.hashes else "string" if k in self.kv else "none"

    async def zadd(self, k, mapping):
        self.zsets.setdefault(k, {}).update(mapping)

    async def zrangebyscore(self, k, lo, hi):
        hi = float("inf") if hi == "+inf" else hi
        items = sorted(self.zsets.get(k, {}).items(), key=lambda x: x[1])
        return [m for m, s in items if lo <= s <= hi]

    async def zremrangebyscore(self, k, lo, hi):
        z = self.zsets.get(k, {})
        for m in [m for m, s in z.items() if lo <= s <= hi]:
            del z[m]

    async def zcard(self, k):
        return len(self.zsets.get(k, {}))

    async def zremrangebyrank(self, k, a, b):
        z = self.zsets.get(k, {})
        items = sorted(z.items(), key=lambda x: x[1])
        for m, _ in items[a:b + 1]:
            del z[m]

    async def expire(self, k, s):
        return True

    async def incr(self, k):
        v = int(self.kv.get(k, "0")) + 1
        self.kv[k] = str(v)
        return v

    async def lpush(self, k, v):
        self.lists.setdefault(k, []).insert(0, v)

    async def ltrim(self, k, a, b):
        self.lists[k] = self.lists.get(k, [])[a:b + 1]

    async def lrange(self, k, a, b):
        return self.lists.get(k, [])[a:b + 1]

    async def hset(self, k, f, v):
        self.hashes.setdefault(k, {})[f] = v

    async def hget(self, k, f):
        return self.hashes.get(k, {}).get(f)

    async def hdel(self, k, f):
        self.hashes.get(k, {}).pop(f, None)

    def pipeline(self):
        return FakePipe(self)

    async def close(self):
        pass


# ─────────────────────────── Fixtures ───────────────────────────
def feed_market(symbol, price=100.0, sell_bias=0.5, n_trades=60, notional=1000.0):
    now = time.time()
    for i in range(6):
        bids = [[str(price - 0.01 * (j + 1)), "10"] for j in range(20)]
        asks = [[str(price + 0.01 * (j + 1)), "10"] for j in range(20)]
        ws_manager.imbalance.feed(symbol, bids, asks, now - 6 + i)
    for i in range(n_trades):
        is_sell = (i % 100) < sell_bias * 100
        ws_manager.flow.feed(symbol, price, notional / price, is_sell, now - n_trades * 0.4 + i * 0.4)


def put_fresh_upstream(r, age=10):
    now = time.time()
    r.kv["hta:state:wiseman_climate"] = json.dumps({"market_mode": "CHOP", "health": "HEALTHY", "confidence": 0.55,
                                                    "timestamp_epoch": now - age, "timestamp": "x"})
    r.kv["horus:global_ignition_state"] = json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - age)),
                                                      "regime": "DORMANT", "global_ignition": 0.39})
    r.kv["horus:maestro:state"] = json.dumps({"market_clock_iso": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - age)),
                                              "state": "HEALTHY_CONSOLIDATION", "trust_score": 45.2, "btc_price": 81600,
                                              "narrative": {"headline": "عنوان"},
                                              "contradictions": [{"contradiction_id": "MOMENTUM_vs_RESISTANCE_EXHAUSTION"}]})


@pytest.fixture(autouse=True)
def fresh_state():
    r = FakeRedis()
    redis_manager.redis = r
    auth._request_counts.clear()
    getattr(auth, "_demo_daily", {}).clear()
    if hasattr(main, "_preview_cache"):
        main._preview_cache.update(ts=0.0, data=None)
    ws_manager.symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    ws_manager.valid_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "PEPEUSDT"}
    ws_manager.ws = None
    ws_manager.flow._trades.clear()
    ws_manager.imbalance._snapshots.clear() if hasattr(ws_manager.imbalance, "_snapshots") else None
    for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        feed_market(s)
    yield r


client = TestClient(main.app)


def get(path, key=None, headers=None):
    h = dict(headers or {})
    if key:
        h["X-API-Key"] = KEYS[key]
    return client.get(path, headers=h)


# ─────────────────────────── Auth & tiers ───────────────────────────
def test_missing_and_invalid_keys():
    assert get("/v1/flow/crypto/BTCUSDT").status_code == 401
    assert client.get("/v1/flow/crypto/BTCUSDT", headers={"X-API-Key": "nope"}).status_code == 403


def test_sh_backdoor_removed():
    fake = "sh" + "x" * 40
    assert client.get("/v1/flow/crypto/BTCUSDT", headers={"X-API-Key": fake}).status_code == 403
    assert client.get("/v1/flow/equity/macro-blocks", headers={"X-API-Key": fake}).status_code == 403


def test_old_public_literals_rejected():
    for lit in ("horus-demo-key-2026", "horus-trader-key-2026"):
        assert client.get("/v1/intelligence/cortex", headers={"X-API-Key": lit}).status_code == 403


@pytest.mark.parametrize("key", ["demo", "free", "mcp"])
def test_free_level_scope(key, fresh_state):
    put_fresh_upstream(fresh_state)
    assert get("/v1/flow/crypto/BTCUSDT", key).status_code == 200
    assert get("/v1/flow/crypto/SOLUSDT", key).status_code == 200  # every pair is open on free plans
    assert get("/v1/intelligence/cortex", key).status_code == 403
    assert get("/v1/intelligence/climate", key).status_code == 403
    assert get("/v1/flow/equity/macro-blocks", key).status_code == 200


def test_builder_scope(fresh_state):
    put_fresh_upstream(fresh_state)
    assert get("/v1/flow/crypto/SOLUSDT", "builder").status_code == 200
    assert get("/v1/intelligence/climate", "builder").status_code == 200
    assert get("/v1/intelligence/ignitions", "builder").status_code == 200
    assert get("/v1/intelligence/cortex", "builder").status_code == 403
    assert get("/v1/flow/crypto/BTCUSDT/history?minutes=120", "builder").status_code == 403


def test_pro_scope(fresh_state):
    put_fresh_upstream(fresh_state)
    r = get("/v1/intelligence/cortex", "pro")
    assert r.status_code == 200
    body = r.json()
    assert body["narrative"]["headline_en"].startswith("Horus Cortex: Healthy Consolidation")
    assert body["active_contradictions"][0]["description_en"] == "Momentum Vs Resistance Exhaustion"
    assert body["freshness_ms"] < 60000


def test_rapidapi_plan_mapping(fresh_state):
    put_fresh_upstream(fresh_state)
    h = {"X-RapidAPI-Proxy-Secret": "test-proxy-secret", "X-RapidAPI-User": "u1"}
    basic = client.get("/v1/flow/crypto/SOLUSDT", headers={**h, "X-RapidAPI-Subscription": "BASIC"})
    assert basic.status_code == 200
    assert client.get("/v1/intelligence/climate", headers={**h, "X-RapidAPI-Subscription": "BASIC"}).status_code == 403
    pro = client.get("/v1/flow/crypto/SOLUSDT", headers={**h, "X-RapidAPI-Subscription": "PRO"})
    assert pro.status_code == 200
    assert client.get("/v1/intelligence/cortex", headers={**h, "X-RapidAPI-Subscription": "PRO"}).status_code == 403
    assert client.get("/v1/intelligence/cortex", headers={**h, "X-RapidAPI-Subscription": "ULTRA"}).status_code == 200
    assert client.get("/v1/intelligence/cortex", headers={**h, "X-RapidAPI-Subscription": "MEGA"}).status_code == 200


def test_demo_rate_limit_per_ip():
    codes = [get("/v1/flow/crypto/BTCUSDT", "demo").status_code for _ in range(21)]
    assert codes[:20].count(200) == 20 and codes[20] == 429


def _req(peer, headers):
    from starlette.requests import Request
    return Request({"type": "http", "client": (peer, 0), "method": "GET", "path": "/",
                    "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


def test_client_ip_behind_cloudflare_and_spoofing():
    # via Cloudflare -> nginx: uvicorn shows the Cloudflare edge as the client
    assert auth._client_ip(_req("172.71.148.65", {"CF-Connecting-IP": "203.0.113.7"})) == "203.0.113.7"
    assert auth._client_ip(_req("2606:4700:10::1", {"CF-Connecting-IP": "2001:db8::5"})) == "2001:db8::5"
    # direct caller trying to spoof the header is identified by its own address
    assert auth._client_ip(_req("185.73.23.168", {"CF-Connecting-IP": "1.2.3.4"})) == "185.73.23.168"
    # local nginx without Cloudflare
    assert auth._client_ip(_req("127.0.0.1", {"X-Real-IP": "198.51.100.9"})) == "198.51.100.9"
    assert auth._client_ip(_req("127.0.0.1", {})) == "127.0.0.1"


def test_free_limit_lower_than_builder():
    from app.config import RATE_LIMITS
    assert RATE_LIMITS["free"] < RATE_LIMITS["builder"] < RATE_LIMITS["pro"]


# ─────────────────────────── Symbols ───────────────────────────
def test_unknown_symbol_rejected_and_not_tracked():
    r = get("/v1/flow/crypto/FAKECOINUSDT", "admin")
    assert r.status_code == 404
    assert "FAKECOINUSDT" not in ws_manager.symbols


def test_new_valid_symbol_added():
    r = get("/v1/flow/crypto/PEPEUSDT", "admin")
    assert r.status_code == 202
    assert "PEPEUSDT" in ws_manager.symbols


def test_new_symbols_refused_until_symbol_list_loads():
    ws_manager.valid_symbols = set()
    r = get("/v1/flow/crypto/PEPEUSDT", "admin")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "symbol_list_loading"
    assert "PEPEUSDT" not in ws_manager.symbols
    assert get("/v1/flow/crypto/BTCUSDT", "admin").status_code == 200  # tracked symbols keep working


def test_capacity_limit(monkeypatch):
    monkeypatch.setattr(binance_ws_mod, "MAX_TRACKED_CRYPTO_SYMBOLS", len(ws_manager.symbols))
    assert get("/v1/flow/crypto/PEPEUSDT", "admin").status_code == 503


def test_live_subscribe_is_scheduled(monkeypatch):
    sent = []

    async def fake_sub(symbols):
        sent.append(set(symbols))

    async def run():
        monkeypatch.setattr(ws_manager, "_subscribe", fake_sub)
        ws_manager.ws, ws_manager._running = object(), True
        status = ws_manager.add_symbol("PEPEUSDT")
        await asyncio.sleep(0)
        return status

    try:
        assert asyncio.run(run()) == "added"
        assert sent == [{"PEPEUSDT"}]
    finally:
        ws_manager.ws, ws_manager._running = None, False


# ─────────────────────────── Flow details ───────────────────────────
def test_cache_keeps_original_timestamp(fresh_state):
    ts = time.time() - 1.5
    r1 = get("/v1/flow/crypto/BTCUSDT", "admin").json()
    doc = dict(r1)
    doc["timestamp"] = ts
    fresh_state.kv["flow:cache:BTCUSDT"] = json.dumps(doc)
    r2 = get("/v1/flow/crypto/BTCUSDT", "admin").json()
    assert abs(r2["timestamp"] - ts) < 1e-6
    assert 1400 <= r2["freshness_ms"] <= 3000


def test_large_trade_threshold_relative():
    f = ws_manager.flow
    f.set_quote_volumes({"BTCUSDT": 800e6, "TINYUSDT": 1e6, "HUGEUSDT": 20e9})
    assert f.large_trade_threshold("BTCUSDT") == 40000
    assert f.large_trade_threshold("TINYUSDT") == 10000
    assert f.large_trade_threshold("HUGEUSDT") == 250000
    assert f.large_trade_threshold("UNKNOWNUSDT") == 50000


def test_flow_metrics_expose_threshold_and_price():
    ws_manager.flow.set_quote_volumes({"BTCUSDT": 800e6})
    m = get("/v1/flow/crypto/BTCUSDT", "admin").json()["metrics"]
    assert m["large_trade_threshold_usd"] == 40000
    assert m["large_sell_window_s"] == 300
    assert m["price"] == 100.0


def test_history_has_numbers_and_tier_windows(fresh_state):
    from app.routes.flow import build_flow_response

    async def snap():
        doc = await build_flow_response("BTCUSDT", update_oscillation=False)
        m = doc["metrics"]
        await redis_manager.push_history("BTCUSDT", {"signal": doc["signal"], "price": m["price"], "delta_30s": m["delta_30s"]})

    asyncio.run(snap())
    r = get("/v1/flow/crypto/BTCUSDT/history?minutes=60", "builder")
    assert r.status_code == 200 and r.json()["history"][0]["price"] == 100.0
    assert get("/v1/flow/crypto/BTCUSDT/history?minutes=1440", "pro").status_code == 200


# ─────────────────────────── Freshness guards ───────────────────────────
def _put(r, tpl, sym, doc):
    r.kv[tpl.format(sym)] = json.dumps(doc)


def test_derivatives_missing_is_503():
    r = get("/v1/intelligence/cross-exchange-flow?symbol=BTCUSDT", "pro")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "data_unavailable"


def test_derivatives_stale_is_503(fresh_state):
    _put(fresh_state, dp.KEY_XFLOW, "BTCUSDT", {"timestamp": time.time() - 1000, "market_type": "BALANCED"})
    r = get("/v1/intelligence/cross-exchange-flow?symbol=BTCUSDT", "pro")
    assert r.status_code == 503 and r.json()["detail"]["error"] == "data_stale"


def test_old_legacy_keys_are_ignored(fresh_state):
    fresh_state.kv["horus:xflow:BTCUSDT"] = json.dumps({"timestamp": time.time(), "market_type": "HYPER_SPECULATION"})
    assert get("/v1/intelligence/cross-exchange-flow?symbol=BTCUSDT", "pro").status_code == 503


def test_composite_partial_without_direction_waits(fresh_state):
    _put(fresh_state, dp.KEY_COMPOSITE, "ETHUSDT", {"timestamp": time.time(), "composite_score": 65.8,
                                                     "verdict": "PARTIAL_CONVICTION", "direction": "NEUTRAL",
                                                     "details": {"climate": "CHOP/HEALTHY"}, "one_liner": "x"})
    r = get("/v1/intelligence/composite?symbol=ETHUSDT", "pro")
    assert r.status_code == 200 and r.json()["action"] == "WAIT"


def test_climate_and_cortex_stale_are_503(fresh_state):
    put_fresh_upstream(fresh_state, age=5000)
    assert get("/v1/intelligence/climate", "pro").json()["detail"]["error"] == "data_stale"
    assert get("/v1/intelligence/cortex", "pro").json()["detail"]["error"] == "data_stale"
    assert get("/v1/intelligence/ignitions", "pro").json()["detail"]["error"] == "data_stale"


def test_incubator_offline_is_503():
    for path in ("/v1/intelligence/incubator", "/v1/intelligence/verdict/BTCUSDT"):
        r = get(path, "pro")
        assert r.status_code == 503 and r.json()["detail"]["error"] == "engine_offline"


def test_market_intelligence_excludes_stale(fresh_state):
    put_fresh_upstream(fresh_state)
    _put(fresh_state, dp.KEY_XFLOW, "BTCUSDT", {"timestamp": time.time(), "market_type": "BALANCED"})
    _put(fresh_state, dp.KEY_HEATMAP, "BTCUSDT", {"timestamp": time.time() - 999, "gravity_direction": "DOWN"})
    body = get("/v1/intelligence/market-intelligence", "pro").json()
    assert "xflow" in body["symbols"]["BTCUSDT"] and "heatmap" not in body["symbols"]["BTCUSDT"]
    assert "BTCUSDT.heatmap" in body["stale_excluded"]


# ─────────────────────────── Publisher end to end ───────────────────────────
class StubSession:
    pass


def test_publisher_writes_ttl_keys_and_routes_serve_them(fresh_state, monkeypatch):
    put_fresh_upstream(fresh_state)
    raw = json.load(open(TESTS / "fixtures" / "binance_raw.json"))

    async def fake_fetch(session, sym):
        return raw[sym]

    monkeypatch.setattr(dp, "fetch_raw", fake_fetch)
    status = asyncio.run(dp.publish_once(fresh_state, StubSession()))
    assert status == {s: "ok" for s in dp.SYMBOLS}
    for tpl in (dp.KEY_XFLOW, dp.KEY_HEATMAP, dp.KEY_COMPOSITE):
        for sym in list(dp.SYMBOLS) + ["summary"]:
            k = tpl.format(sym)
            assert k in fresh_state.kv and 0 < fresh_state.ttl[k] - time.time() <= dp.KEY_TTL
    for path in ("cross-exchange-flow", "liquidation-heatmap", "composite"):
        r = get(f"/v1/intelligence/{path}?symbol=SOLUSDT", "pro")
        assert r.status_code == 200, (path, r.text)
        assert "method" in r.json()
    mi = get("/v1/intelligence/market-intelligence", "pro").json()
    assert set(mi["symbols"]) == set(dp.SYMBOLS) and mi["stale_excluded"] == []
    xf = get("/v1/intelligence/cross-exchange-flow?symbol=BTCUSDT", "pro").json()
    assert xf["cross_venue"]["venues_reporting"] == 3 and xf["cross_venue"]["total_oi_usd"] > 0
    # the legacy keys used by the trading platform were not written
    assert not any(k.startswith(("horus:xflow:", "horus:liq_heatmap:", "horus:composite:")) for k in fresh_state.kv)


def test_crowd_judged_against_its_median():
    raw = json.load(open(TESTS / "fixtures" / "binance_raw.json"))["BTCUSDT"]
    x = dp.compute_xflow("BTCUSDT", raw, time.time())
    h = dp.compute_heatmap("BTCUSDT", raw, {"long_liquidated_usd": 0, "short_liquidated_usd": 0, "count": 0}, x, time.time())
    assert h["long_short_ratio_global"] > 1.5          # Binance retail ratio is structurally long
    assert h["crowd_bias"] in ("BALANCED", "LONG_HEAVY", "SHORT_HEAVY")  # not a permanent OVERLEVERAGED label
    lz = h["estimated_liquidation_zones"]["long_zones"]
    assert lz == sorted(lz, reverse=True) and lz[0] < h["current_price"]


# ─────────────────────────── Equities ───────────────────────────
def test_equity_is_labelled_sample_and_capped(fresh_state):
    now = time.time()
    for sym in ("NVDA", "SPY"):
        for i in range(6):
            alpaca_ws_manager.imbalance.feed_quote(sym, 100.0, 5 if i < 3 else 1, 100.02, 5, now - 6 + i)
        for i in range(60):
            alpaca_ws_manager.flow.feed(sym, 100.0, 3000 if i % 10 else 2500, True, now - 30 + i * 0.4)
    r = get("/v1/flow/equity/NVDA", "builder")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["signal"] not in ("EMERGENCY_DUMP", "LIQUIDATION_CASCADE", "DEPTH_COLLAPSE", "WHALE_DUMP")
    assert b["confidence"] <= 0.6 and b["risk"] != "EXTREME"
    assert "IEX_SAMPLE" in b["metrics"]["flags"] and b["data_source"]["feed"] == "IEX via Alpaca"
    assert b["timestamp_utc"] and b["explanation"].endswith("[IEX sample, ~3% of US volume]")
    mb = get("/v1/flow/equity/macro-blocks", "free").json()
    assert mb["spy_macro_climate"]["market_mode"] in ("SELL_SKEW_STRONG", "SELL_SKEW", "BUY_SKEW", "BALANCED")
    assert "data_source" in mb


# ─────────────────────────── Public endpoints ───────────────────────────
def test_status_and_preview_need_no_key(fresh_state):
    put_fresh_upstream(fresh_state)
    ws_manager._last_msg_time = time.time()
    s = client.get("/v1/status")
    assert s.status_code == 200
    names = {c["name"]: c["status"] for c in s.json()["components"]}
    assert names["binance_spot_stream"] == "ok" and names["incubator"] == "down"
    p = client.get("/v1/public/preview").json()
    assert p["flow"]["symbol"] == "BTCUSDT" and p["cortex"]["regime_state"] == "HEALTHY_CONSOLIDATION"


# ═══════════════════════════ Agent layer ═══════════════════════════
import sqlite3  # noqa: E402
from app import track_record, events as ev, us_market  # noqa: E402


def make_ledger(path, now):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE predictions (id INTEGER PRIMARY KEY, ts REAL, symbol TEXT, signal TEXT, direction_bias TEXT,
        confidence REAL, price_at_signal REAL, whale_intent TEXT, price_1m REAL, price_5m REAL, price_15m REAL, price_30m REAL,
        move_pct_1m REAL, move_pct_5m REAL, move_pct_15m REAL, move_pct_30m REAL, correct_1m INTEGER, correct_5m INTEGER,
        correct_15m INTEGER, correct_30m INTEGER, resolved INTEGER)""")
    rows = []
    for i in range(300):  # STRONG_BUY on BTC: 60% hits at every horizon
        m = 0.05 if i % 10 < 6 else -0.05
        rows.append((now - 3600 - i * 60, "BTCUSDT", "STRONG_BUY_PRESSURE", "BULLISH", 0.9, 100.0, m, m, m, m))
    for i in range(300):  # SELL_PRESSURE on ETH: 50% hits
        m = -0.02 if i % 2 else 0.02
        rows.append((now - 3600 - i * 60, "ETHUSDT", "SELL_PRESSURE", "BEARISH", 0.8, 100.0, m, m, m, m))
    con.executemany("""INSERT INTO predictions (ts, symbol, signal, direction_bias, confidence, price_at_signal,
        move_pct_1m, move_pct_5m, move_pct_15m, move_pct_30m) VALUES (?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    con.close()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = str(tmp_path / "edge.db")
    make_ledger(path, time.time())
    monkeypatch.setattr(track_record, "EDGE_DB", path)
    track_record._cache.update(stats=track_record.compute_stats(path), computed_at=time.time())
    yield path
    track_record._cache.update(stats=None, computed_at=0.0)


def test_track_record_numbers(ledger):
    w = track_record.current_stats()["windows"]["30d"]
    assert w["by_signal"]["STRONG_BUY_PRESSURE"]["5m"]["hit_rate"] == 0.6
    assert w["by_signal"]["SELL_PRESSURE"]["5m"]["hit_rate"] == 0.5
    assert w["by_signal"]["STRONG_BUY_PRESSURE"]["5m"]["avg_directional_move_bps"] == 1.0


def test_reliability_text_is_honest(ledger):
    r = track_record.reliability_for("STRONG_BUY_PRESSURE", "BTCUSDT", 0.9, "BULLISH")
    assert r["basis"].startswith("STRONG_BUY_PRESSURE on BTCUSDT") and r["hit_rate"]["5m"] == 0.6
    assert "measurable directional edge" in r["interpretation"] and "+1.0 bps" in r["interpretation"]
    coin = track_record.reliability_for("SELL_PRESSURE", "XRPUSDT", 0.8, "BEARISH")
    assert "all tracked symbols" in coin["basis"] and "coin flip" in coin["interpretation"]
    assert track_record.reliability_for("NEUTRAL", "BTCUSDT", 0.5, "NEUTRAL")["directional"] is False


def test_track_record_public_and_ledger_tiers(ledger):
    pub = client.get("/v1/track-record")
    assert pub.status_code == 200 and pub.json()["coin_flip"] == 0.5 and "method" in pub.json()
    assert get("/v1/track-record/signals?symbol=BTCUSDT", "free").status_code == 403
    r = get("/v1/track-record/signals?symbol=BTCUSDT", "builder")
    assert r.status_code == 200 and r.json()["count"] > 0 and set(r.json()["signals"][0]["move_pct"]) == {"1m", "5m", "15m", "30m"}
    assert get("/v1/track-record/signals?symbol=BTCUSDT&start=2026-01-01&end=2026-03-01", "builder").status_code == 400
    assert get("/v1/track-record/signals?symbol=DOGEUSDT", "builder").status_code == 404


def test_flow_carries_reliability_and_compact_view(ledger):
    full = get("/v1/flow/crypto/BTCUSDT", "admin").json()
    rel = full["reliability"]
    assert rel["track_record_url"] == "/v1/track-record" if rel["directional"] else "note" in rel
    compact = get("/v1/flow/crypto/BTCUSDT?view=compact", "admin").json()
    assert set(compact) >= {"signal", "direction_bias", "price", "delta_30s_usd", "reliability", "freshness_ms"}
    assert "action" not in compact
    assert "metrics" not in compact and len(json.dumps(compact)) < 900


def test_detector_first_tick_silent_then_emits(fresh_state):
    det = ev.Detector()
    put_fresh_upstream(fresh_state)
    asyncio.run(det.tick())
    assert fresh_state.lists.get(ev.EVENTS_KEY) in (None, [])
    m = json.loads(fresh_state.kv["horus:maestro:state"])
    m["state"] = "RISK_OFF"
    fresh_state.kv["horus:maestro:state"] = json.dumps(m)
    out = asyncio.run(det.tick())
    assert [e["type"] for e in out] == ["cortex_regime_change"]
    assert out[0]["data"] == {"from": "HEALTHY_CONSOLIDATION", "to": "RISK_OFF", "trust_score": 45.2}
    r = get("/v1/events?since_id=0", "builder").json()
    assert r["count"] == 1 and r["last_id"] == out[0]["id"]
    assert get("/v1/events", "free").status_code == 403
    assert get("/v1/events/stream", "free").status_code == 403
    assert get("/v1/events?types=bogus", "builder").status_code == 400


def test_webhook_url_guard(monkeypatch):
    def fake_resolve(host, port, proto=0):
        table = {"good.example": "93.184.215.14", "internal.example": "10.1.2.3", "localhost": "127.0.0.1"}
        return [(2, 1, 6, "", (table.get(host, host), port))]
    monkeypatch.setattr(ev.socket, "getaddrinfo", fake_resolve)
    assert ev.validate_webhook_url("https://good.example/hook")
    for bad in ("http://good.example/hook", "https://internal.example/x", "https://localhost/x",
                "https://127.0.0.1/x", "https://user:pw@good.example/x", "https://good.example:6379/x"):
        with pytest.raises(ValueError):
            ev.validate_webhook_url(bad)


def test_webhook_lifecycle_and_signature(monkeypatch):
    monkeypatch.setattr(ev, "validate_webhook_url", lambda url: url)
    assert client.post("/v1/webhooks", json={"url": "https://good.example/h"}, headers={"X-API-Key": KEYS["builder"]}).status_code == 403
    r = client.post("/v1/webhooks", json={"url": "https://good.example/h", "types": ["liquidation_cascade"]},
                    headers={"X-API-Key": KEYS["pro"]})
    assert r.status_code == 200, r.text
    hook = r.json()
    assert hook["secret"].startswith("whsec_") and hook["types"] == ["liquidation_cascade"]
    listed = get("/v1/webhooks", "pro").json()["webhooks"]
    assert listed[0]["id"] == hook["id"] and "secret" not in listed[0]
    assert get("/v1/webhooks", "admin").json()["webhooks"] == []  # other keys cannot see it
    bad = client.post("/v1/webhooks", json={"url": "https://good.example/h", "types": ["nope"]}, headers={"X-API-Key": KEYS["pro"]})
    assert bad.status_code == 400
    assert client.delete(f"/v1/webhooks/{hook['id']}", headers={"X-API-Key": KEYS["admin"]}).status_code == 404
    assert client.delete(f"/v1/webhooks/{hook['id']}", headers={"X-API-Key": KEYS["pro"]}).status_code == 200
    import hashlib, hmac
    sig = ev.sign("whsec_x", "1700000000", b'{"a":1}')
    assert sig == "sha256=" + hmac.new(b"whsec_x", b'1700000000.{"a":1}', hashlib.sha256).hexdigest()


def test_equity_session_and_halts_public():
    us_market._halts.update(items=us_market.parse_halts(open(TESTS / "fixtures" / "nasdaq_halts.xml").read()), fetched_at=time.time())
    s = client.get("/v1/equity/session")
    assert s.status_code == 200 and s.json()["phase"] in ("pre_market", "regular", "after_hours", "closed_overnight", "closed_weekend", "closed_holiday")
    assert "halts" in s.json() and "agent_hint" in s.json()
    h = client.get("/v1/equity/halts?limit=5").json()
    assert h["today_count"] > 0 and len(h["today"]) <= 5 and h["today"][0]["reason"]


def test_us_calendar_edges():
    from zoneinfo import ZoneInfo
    from datetime import datetime as dt
    E = ZoneInfo("America/New_York")
    assert us_market.session(dt(2026, 11, 26, 11, 0, tzinfo=E))["phase"] == "closed_holiday"
    bf = us_market.session(dt(2026, 11, 27, 12, 59, tzinfo=E))
    assert bf["phase"] == "regular" and bf["minutes_to_close"] == 1
    assert us_market.session(dt(2026, 11, 27, 13, 30, tzinfo=E))["phase"] == "after_hours"
    assert us_market.session(dt(2026, 10, 24, 12, 0, tzinfo=E))["next_open_et"].startswith("2026-10-26T09:30")


def test_cross_asset(monkeypatch):
    assert get("/v1/cross-asset", "free").status_code == 403
    monkeypatch.setattr(us_market, "session", lambda now=None: {"phase": "closed_weekend", "next_open_et": "2026-10-26T09:30-04:00",
                                                                  "next_close_et": "x", "minutes_to_close": None})
    closed = get("/v1/cross-asset", "builder").json()
    assert closed["alignment"] == "CRYPTO_ONLY" and closed["us_equities"]["SPY"]["flow_skew"] == "MARKET_CLOSED"
    monkeypatch.setattr(us_market, "session", lambda now=None: {"phase": "regular", "next_open_et": "x", "next_close_et": "y", "minutes_to_close": 30})
    now = time.time()
    alpaca_ws_manager.flow._trades.clear()  # isolate from earlier equity tests
    for sym in ("SPY", "QQQ"):
        for i in range(40):
            alpaca_ws_manager.flow.feed(sym, 500.0, 10, False, now - 20 + i * 0.4)  # all buys
    ws_manager.flow._trades.pop("BTCUSDT", None)
    feed_market("BTCUSDT", sell_bias=0.0)  # all buys on BTC
    open_ = get("/v1/cross-asset", "builder").json()
    assert open_["us_equities"]["SPY"]["flow_skew"] == "BUYING"
    assert open_["alignment"] == "RISK_ON_ALIGNED", open_


def _strong_doc(sym):
    return {"signal": "STRONG_BUY_PRESSURE", "direction_bias": "BULLISH", "confidence": 0.9,
            "metrics": {"price": 1.0, "delta_30s": 1.0}, "reliability": {}}


def test_flow_events_need_persistence(monkeypatch, fresh_state):
    import app.routes.flow as flow_mod

    async def fake_build(sym, update_oscillation=True):
        return _strong_doc(sym)

    monkeypatch.setattr(flow_mod, "build_flow_response", fake_build)
    det = ev.Detector()
    det.started = time.time() - 1000          # warmed up
    counts = [len([e for e in asyncio.run(det.tick()) if e["type"] == "strong_flow_signal"]) for _ in range(4)]
    assert counts == [0, 0, 3, 0]             # fires once per symbol on the 3rd consecutive tick, then dedups


def test_flow_events_suppressed_during_warmup(monkeypatch, fresh_state):
    import app.routes.flow as flow_mod

    async def fake_build(sym, update_oscillation=True):
        return _strong_doc(sym)

    monkeypatch.setattr(flow_mod, "build_flow_response", fake_build)
    det = ev.Detector()                       # just started
    assert sum(len(asyncio.run(det.tick())) for _ in range(4)) == 0


def test_cross_asset_thin_sample(monkeypatch):
    monkeypatch.setattr(us_market, "session", lambda now=None: {"phase": "regular", "next_open_et": "x", "next_close_et": "y", "minutes_to_close": 30})
    alpaca_ws_manager.flow._trades.clear()
    now = time.time()
    for i in range(4):
        alpaca_ws_manager.flow.feed("SPY", 500.0, 10, True, now - 5 + i)
    r = get("/v1/cross-asset", "builder").json()
    assert r["us_equities"]["SPY"]["flow_skew"] == "THIN_SAMPLE" and r["us_equities"]["SPY"]["trades_5m"] == 4


# ═══════════════════════════ RapidAPI usage counters ═══════════════════════════
from app import rapidapi_stats  # noqa: E402


def test_rapidapi_usage_is_counted(fresh_state):
    h = {"X-RapidAPI-Proxy-Secret": "test-proxy-secret", "X-RapidAPI-User": "alice", "X-RapidAPI-Subscription": "BASIC"}
    assert client.get("/v1/flow/crypto/BTCUSDT", headers=h).status_code == 200
    assert client.get("/v1/intelligence/climate", headers=h).status_code == 403
    client.get("/v1/flow/crypto/BTCUSDT", headers={**h, "X-RapidAPI-User": "bob", "X-RapidAPI-Subscription": "PRO"})
    client.get("/v1/flow/crypto/BTCUSDT", headers={"X-API-Key": KEYS["admin"]})  # not RapidAPI: not counted
    s = asyncio.run(rapidapi_stats.summary(fresh_state, 1))[0]
    assert s["requests"] == 3
    assert s["requests_by_plan"] == {"BASIC": 2, "PRO": 1}
    assert s["unique_subscribers_by_plan"] == {"BASIC": 1, "PRO": 1}
    assert s["denied"] == {"BASIC /v1/intelligence/climate 403": 1}
    assert s["top_endpoints"] == {"/v1/flow/crypto/{symbol}": 2, "/v1/intelligence/climate": 1}
    assert "testserver" in s["hosts"]
    text = rapidapi_stats.telegram_text(s)
    assert "إجمالي الطلبات: 3" in text and "BASIC" in text and "رُفضت" in text


def test_rapidapi_usage_endpoint_is_admin_only(fresh_state):
    assert get("/v1/admin/rapidapi-usage", "pro").status_code == 403
    r = get("/v1/admin/rapidapi-usage?days=2", "admin")
    assert r.status_code == 200 and len(r.json()["days"]) == 2


def test_route_template_fallback():
    import app.main as m
    assert m._route_template("/v1/flow/crypto/BTCUSDT") == "/v1/flow/crypto/{symbol}"
    assert m._route_template("/v1/flow/crypto/BTCUSDT/history") == "/v1/flow/crypto/{symbol}/history"
    assert m._route_template("/v1/intelligence/cortex") == "/v1/intelligence/cortex"


def test_rapidapi_public_endpoints_are_counted(fresh_state):
    h = {"X-RapidAPI-Proxy-Secret": "test-proxy-secret", "X-RapidAPI-User": "carol", "X-RapidAPI-Subscription": "PRO"}
    assert client.get("/v1/status", headers=h).status_code == 200
    assert client.get("/v1/status").status_code == 200                      # not RapidAPI: not counted
    assert client.get("/v1/status", headers={**h, "X-RapidAPI-Proxy-Secret": "wrong"}).status_code == 200  # forged: not counted
    s = asyncio.run(rapidapi_stats.summary(fresh_state, 1))[0]
    assert s["requests_by_plan"] == {"PRO": 1} and s["top_endpoints"] == {"/v1/status": 1}


# ═══════════════════════════ Market scanner ═══════════════════════════
from app import market_scanner as ms  # noqa: E402


def _kl(opens, closes, qvol, taker_buy):
    return [[0, str(o), "0", "0", str(c), "0", 0, str(q), 0, "0", str(t), "0"] for o, c, q, t in zip(opens, closes, qvol, taker_buy)]


def test_scanner_metrics_from_candles():
    # 12 candles: flat first 45m, then 15m of heavy buying and a 2% rise
    opens = [100] * 9 + [100, 100.5, 101.2]
    closes = [100] * 9 + [100.5, 101.2, 102]
    qvol = [1000] * 9 + [4000, 4000, 4000]
    tb = [500] * 9 + [3000, 3000, 3000]
    m = ms.metrics_from_klines(_kl(opens, closes, qvol, tb))
    assert m["change_15m_pct"] == 2.0 and m["change_1h_pct"] == 2.0
    assert m["taker_buy_ratio_15m"] == 0.75 and m["volume_surge"] == 4.0
    assert m["net_taker_flow_15m_usd"] == 6000          # 9000 bought - 3000 sold
    assert ms.metrics_from_klines(_kl([1] * 5, [1] * 5, [1] * 5, [1] * 5)) is None


def _scanner_rows():
    now = time.time()
    base = dict(volume_24h_usd=50e6, change_24h_pct=1.0, funding_rate=0.0001, ignition_score=0.5, updated_at=now,
                price=1.0, change_1h_pct=0.5, taker_buy_ratio_1h=0.5, volume_15m_usd=1e5)
    rows = {
        "AAAUSDT": dict(base, symbol="AAAUSDT", taker_buy_ratio_15m=0.70, change_15m_pct=1.2, net_taker_flow_15m_usd=5e5, volume_surge=2.5, ignition_score=0.85),
        "BBBUSDT": dict(base, symbol="BBBUSDT", taker_buy_ratio_15m=0.62, change_15m_pct=0.4, net_taker_flow_15m_usd=9e5, volume_surge=1.1),
        "CCCUSDT": dict(base, symbol="CCCUSDT", taker_buy_ratio_15m=0.30, change_15m_pct=-2.0, net_taker_flow_15m_usd=-7e5, volume_surge=3.1, funding_rate=-0.0009),
        "DDDUSDT": dict(base, symbol="DDDUSDT", taker_buy_ratio_15m=0.80, change_15m_pct=3.0, net_taker_flow_15m_usd=8e5, volume_surge=4.0, volume_24h_usd=2e6),
        "EEEUSDT": dict(base, symbol="EEEUSDT", taker_buy_ratio_15m=0.55, change_15m_pct=0.1, net_taker_flow_15m_usd=1e5, volume_surge=1.0),
    }
    return rows


def test_scanner_presets():
    rows = _scanner_rows()
    q = lambda p, **kw: [r["symbol"] for r in ms.run_query(rows, p, 10, **kw)]
    assert q("buyers_in_control") == ["BBBUSDT", "AAAUSDT"]            # DDD excluded by $5M volume floor
    assert q("buyers_in_control", min_volume_24h=1e6) == ["BBBUSDT", "DDDUSDT", "AAAUSDT"]
    assert q("sellers_in_control") == ["CCCUSDT"]
    assert q("volume_surge") == ["CCCUSDT", "AAAUSDT"]
    assert q("breakout_candidates") == ["AAAUSDT"]
    assert q("crowded_funding") == ["CCCUSDT"]
    custom = ms.run_query(rows, None, 10, filters={"min_volume_surge": 2.0}, sort_by="change_15m_pct", descending=False)
    assert [r["symbol"] for r in custom] == ["CCCUSDT", "AAAUSDT"]


def test_scan_endpoint_tiers_and_warmup(monkeypatch):
    monkeypatch.setitem(ms._state, "rows", {})
    monkeypatch.setitem(ms._state, "universe", [])
    assert get("/v1/scan", "builder").status_code == 503
    rows = {f"S{i:02d}USDT": dict(_scanner_rows()["AAAUSDT"], symbol=f"S{i:02d}USDT", net_taker_flow_15m_usd=1e5 * i) for i in range(10)}
    monkeypatch.setitem(ms._state, "rows", rows)
    monkeypatch.setitem(ms._state, "universe", list(rows))
    monkeypatch.setitem(ms._state, "cycle_at", time.time())
    free = get("/v1/scan?preset=buyers_in_control&limit=10", "free").json()
    assert free["count"] == 3 and "upgrade" in free and free["results"][0]["symbol"] == "S09USDT"
    paid = get("/v1/scan?preset=buyers_in_control&limit=10", "builder").json()
    assert paid["count"] == 10 and "upgrade" not in paid and paid["coverage"]["universe"] == 10
    assert set(paid["results"][0]) >= {"symbol", "taker_buy_ratio_15m", "net_taker_flow_15m_usd", "volume_surge", "data_age_s"}
    custom = get("/v1/scan?preset=custom&min_volume_surge=2&sort_by=change_15m_pct&order=asc&limit=2", "builder").json()
    assert custom["count"] == 2 and custom["criteria"]["sort_by"] == "change_15m_pct"
    assert get("/v1/scan?preset=nonsense", "builder").status_code == 422


# ─────────────────────────── ops alerts ───────────────────────────
from app import status_monitor as sm  # noqa: E402


def test_ops_alerts_once_and_survive_restart(fresh_state, monkeypatch):
    sent = []

    async def fake_send(text):
        sent.append(text)
    monkeypatch.setattr(sm, "_send_telegram", fake_send)
    monkeypatch.setattr(sm, "_started_at", time.time() - sm.STARTUP_GRACE_SECONDS - 1)
    sm._down_streak.clear()
    down = {"us_halts_feed": {"status": "down", "age_seconds": None},
            "incubator": {"status": "down", "age_seconds": None}}
    for _ in range(5):
        asyncio.run(sm._alerts(down))
    assert sent == ["Horus Flow API: US trading halts (Nasdaq Trader) is DOWN."]  # once; incubator silent
    sm._down_streak.clear()  # an API restart forgets memory but not Redis
    for _ in range(3):
        asyncio.run(sm._alerts(down))
    assert len(sent) == 1
    asyncio.run(sm._alerts({"us_halts_feed": {"status": "ok", "age_seconds": 5}}))
    assert sent[-1] == "Horus Flow API: US trading halts (Nasdaq Trader) recovered." and len(sent) == 2


def test_ops_alerts_quiet_while_warming_up(fresh_state, monkeypatch):
    sent = []

    async def fake_send(text):
        sent.append(text)
    monkeypatch.setattr(sm, "_send_telegram", fake_send)
    monkeypatch.setattr(sm, "_started_at", time.time())
    sm._down_streak.clear()
    for _ in range(4):
        asyncio.run(sm._alerts({"market_scanner": {"status": "down", "age_seconds": None}}))
    assert sent == []
