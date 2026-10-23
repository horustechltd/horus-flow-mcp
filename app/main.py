# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — main.py
"""
import asyncio
import logging
import json
import os
import time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import HOST, PORT
from app.routes.flow import router as flow_router
from app.routes.equity import router_equity
from app.routes.intelligence import router_intelligence
from app.routes.auth import router_auth
from app.routes.oauth import router_oauth
from app.routes.billing import router_billing
from app.routes.admin import router_admin
from app.feeds import start_ws, start_alpaca_ws
from app.feeds.binance_ws import ws_manager
from app.feeds.alpaca_ws import alpaca_ws_manager
from app.feeds.binance_futures_ws import futures_manager
from app.redis_client import redis_manager
from app.database import log_usage
from app.wiseman_publisher import wiseman_publisher_loop
from app.ignition_publisher import ignition_publisher_loop
from app.config import TEST_INSTANCE, RAPIDAPI_PROXY_SECRET
from app.derivatives_publisher import derivatives_publisher_loop, KEY_COMPOSITE
from app.history_recorder import history_recorder_loop
from app.status_monitor import status_monitor_loop, public_status
from app.routes.agents import router_agents
from app import events as agent_events, track_record, us_market, rapidapi_stats, market_scanner
from app.auth import require_tier
from fastapi import Depends, Query

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("API")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up resources...")
    await redis_manager.connect()
    ws_task = asyncio.create_task(start_ws())
    futures_task = asyncio.create_task(futures_manager.start())
    background = [
        asyncio.create_task(ws_manager.refresh_market_info_loop()),
        asyncio.create_task(derivatives_publisher_loop(redis_manager)),
        asyncio.create_task(track_record.track_record_loop()),
        asyncio.create_task(us_market.halts_loop()),
        asyncio.create_task(market_scanner.scanner_loop(redis_manager, record_ledger=not TEST_INSTANCE)),
    ]
    if not TEST_INSTANCE:  # these write shared history / uptime samples
        background.append(asyncio.create_task(history_recorder_loop()))
        background.append(asyncio.create_task(status_monitor_loop()))
    alp_task = None
    if TEST_INSTANCE:
        # A test instance must not write keys shared with the trading platform
        # (WiseMan climate, ignition) nor take the single Alpaca WS connection.
        logger.warning("HORUS_TEST_INSTANCE=1: WiseMan/ignition publishers and Alpaca WS disabled")
    else:
        alp_task = asyncio.create_task(start_alpaca_ws())
        background.append(asyncio.create_task(wiseman_publisher_loop(redis_manager)))
        background.append(asyncio.create_task(ignition_publisher_loop(redis_manager)))
        # events are shared state: only the production instance detects and delivers them
        background.append(asyncio.create_task(agent_events.detector_loop()))
        background.append(asyncio.create_task(agent_events.webhook_loop()))
    yield
    # Shutdown
    logger.info("Shutting down resources...")
    for t in background:
        t.cancel()
    await redis_manager.disconnect()
    ws_manager.stop()
    alpaca_ws_manager.stop()
    futures_manager.stop()
    await ws_task
    if alp_task:
        await alp_task
    await futures_task

app = FastAPI(
    title="Horus Flow Signal API",
    description="Institutional-grade orderflow intelligence platform by Horus Tech Ltd.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    process_time_ms = int(process_time * 1000)
    
    # Add Process Time in ms
    response.headers["X-Process-Time"] = f"{process_time_ms:.2f} ms"
    
    # Log API usage if it was authenticated via verify_api_key
    if hasattr(request.state, "api_key"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
        
        # Dispatch to background task or log directly (synchronous for now, but fast)
        log_usage(
            api_key=request.state.api_key,
            endpoint=request.url.path,
            response_time_ms=process_time_ms,
            client_ip=ip
        )

    # RapidAPI usage counters (plan, unique subscribers, endpoint, status)
    rapid = getattr(request.state, "rapidapi", None)
    if not rapid and RAPIDAPI_PROXY_SECRET and request.headers.get("x-rapidapi-proxy-secret") == RAPIDAPI_PROXY_SECRET:
        # public endpoints (status, track record, US session) skip key checks; count them too
        rapid = {"plan": (request.headers.get("x-rapidapi-subscription") or "NONE").upper(),
                 "user": request.headers.get("x-rapidapi-user", "rapidapi-subscriber")}
    if rapid:
        try:
            route = getattr(request.scope.get("route"), "path", None) or _route_template(request.url.path)
            await rapidapi_stats.record(redis_manager.redis, rapid["plan"], rapid["user"], route,
                                        response.status_code, request.headers.get("host", ""))
        except Exception as e:
            logger.error(f"rapidapi stats error: {e}")

    return response


def _route_template(path: str) -> str:
    """Collapse symbol-like path segments so counters group by endpoint, not by coin."""
    import re
    return re.sub(r"/[A-Z0-9]{2,15}(?=/|$)", "/{symbol}", path)

app.include_router(flow_router, prefix="/v1/flow/crypto", tags=["Crypto Flow"])
app.include_router(router_equity, prefix="/v1/flow/equity", tags=["Equity Flow"])
app.include_router(router_intelligence, prefix="/v1/intelligence", tags=["🧠 Premium Intelligence"])
app.include_router(router_auth, prefix="/api/auth", tags=["🔐 Authentication"])
app.include_router(router_oauth, prefix="/api/oauth", tags=["🌐 Social Login"])
app.include_router(router_billing, prefix="/api/billing", tags=["💳 Billing"])
app.include_router(router_admin, prefix="/api/admin", tags=["🛡️ Admin"])
app.include_router(router_agents, prefix="/v1", tags=["Agents"])

# MCP Registry Domain Verification
from fastapi.responses import PlainTextResponse, RedirectResponse

@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/site/")

@app.get("/.well-known/mcp-registry-auth", response_class=PlainTextResponse, tags=["System"])
async def mcp_registry_auth():
    return "v=MCPv1; k=ed25519; p=nWYLm+WB0QKWTVhGQtHDJoNL4eraIJjq56Wjrfj6Vs0="

@app.get("/v1/admin/rapidapi-usage", tags=["System"], include_in_schema=False)
async def rapidapi_usage(days: int = Query(7, ge=1, le=100), auth: dict = Depends(require_tier("ADMIN"))):
    """RapidAPI usage per day: requests and unique subscribers per plan, endpoints, denials, hosts."""
    return {"days": await rapidapi_stats.summary(redis_manager.redis, days)}


@app.get("/README.md", response_class=PlainTextResponse, tags=["System"])
async def serve_readme():
    readme_path = Path(__file__).resolve().parent.parent / "README.md"
    if readme_path.exists():
        return readme_path.read_text(encoding="utf-8")
    return PlainTextResponse("Not found", status_code=404)

# Mount Brand Website (Landing, Pricing, Docs)
app.mount("/site", StaticFiles(directory="static/site", html=True), name="brand-site")

# Mount Original Dashboard Interface
app.mount("/dash", StaticFiles(directory="static", html=True), name="static")

@app.get("/v1/status", tags=["System"])
async def service_status():
    """Public status: freshness and uptime of every data source behind the API. No key required."""
    return await public_status()


_preview_cache = {"ts": 0.0, "data": None}


@app.get("/v1/public/preview", tags=["System"])
async def public_preview():
    """
    Small public sample for the website (no key, cached 30s):
    BTC flow signal, Cortex regime and BTC composite score.
    """
    now = time.time()
    if _preview_cache["data"] and now - _preview_cache["ts"] < 30:
        return _preview_cache["data"]
    out = {"generated_at": now, "flow": None, "cortex": None, "composite": None}
    try:
        from app.routes.flow import build_flow_response
        f = await build_flow_response("BTCUSDT", update_oscillation=False)
        out["flow"] = {"symbol": "BTCUSDT", "signal": f["signal"], "direction_bias": f["direction_bias"],
                       "confidence": f["confidence"], "delta_30s": f["metrics"].get("delta_30s"),
                       "buy_sell_ratio": f["metrics"].get("buy_sell_ratio")}
    except Exception:
        pass
    if redis_manager.redis:
        try:
            raw = await redis_manager.redis.get("horus:maestro:state")
            if raw:
                c = json.loads(raw)
                out["cortex"] = {"regime_state": c.get("state"), "trust_score": c.get("trust_score"),
                                 "btc_price": c.get("btc_price")}
            raw = await redis_manager.redis.get(KEY_COMPOSITE.format("BTCUSDT"))
            if raw:
                comp = json.loads(raw)
                if now - float(comp.get("timestamp", 0)) < 180:
                    out["composite"] = {"composite_score": comp.get("composite_score"), "verdict": comp.get("verdict")}
        except Exception:
            pass
    _preview_cache.update(ts=now, data=out)
    return out


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "online", 
        "binance_ws": ws_manager._running,
        "alpaca_ws": alpaca_ws_manager._running
    }

@app.get("/v1/flow/theses", tags=["System"])
async def get_theses():
    try:
        if os.path.exists("manus_theses.json"):
            with open("manus_theses.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error reading theses: {e}")
    return {"stats": {"wins": 0, "losses": 0, "draws": 0}, "active_theses": [], "resolved_theses": []}

# ---------- Billing Placeholder ----------
from fastapi import Request as _Req
from fastapi.responses import JSONResponse

@app.post("/api/checkout/create-session", tags=["Billing"])
async def create_checkout_session(req: _Req):
    """Placeholder for Stripe Checkout. Will be wired when Stripe keys are configured."""
    body = await req.json()
    plan = body.get("plan", "unknown")
    return JSONResponse({"message": f"Checkout for '{plan}' plan coming soon.", "checkout_url": None})


@app.middleware("http")
async def no_cache_middleware(request, call_next):
    response = await call_next(request)
    # Prevent Cloudflare and browsers from caching API responses AND dashboard files
    if request.url.path.startswith("/v1/") or request.url.path.startswith("/api/admin") or request.url.path.startswith("/dash/") or request.url.path.startswith("/site/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=PORT, workers=1)
