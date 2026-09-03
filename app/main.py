# -*- coding: utf-8 -*-
"""
Horus Flow Signal API — main.py
"""
import asyncio
import logging
import json
import os
import time
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

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("API")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up resources...")
    await redis_manager.connect()
    ws_task = asyncio.create_task(start_ws())
    alp_task = asyncio.create_task(start_alpaca_ws())
    futures_task = asyncio.create_task(futures_manager.start())
    wiseman_task = asyncio.create_task(wiseman_publisher_loop(redis_manager))
    yield
    # Shutdown
    logger.info("Shutting down resources...")
    await redis_manager.disconnect()
    ws_manager.stop()
    alpaca_ws_manager.stop()
    futures_manager.stop()
    await ws_task
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
        
    return response

app.include_router(flow_router, prefix="/v1/flow/crypto", tags=["Crypto Flow"])
app.include_router(router_equity, prefix="/v1/flow/equity", tags=["Equity Flow"])
app.include_router(router_intelligence, prefix="/v1/intelligence", tags=["🧠 Premium Intelligence"])
app.include_router(router_auth, prefix="/api/auth", tags=["🔐 Authentication"])
app.include_router(router_oauth, prefix="/api/oauth", tags=["🌐 Social Login"])
app.include_router(router_billing, prefix="/api/billing", tags=["💳 Billing"])
app.include_router(router_admin, prefix="/api/admin", tags=["🛡️ Admin"])

# MCP Registry Domain Verification
from fastapi.responses import PlainTextResponse

@app.get("/.well-known/mcp-registry-auth", response_class=PlainTextResponse, tags=["System"])
async def mcp_registry_auth():
    return "v=MCPv1; k=ed25519; p=nWYLm+WB0QKWTVhGQtHDJoNL4eraIJjq56Wjrfj6Vs0="

# Mount Brand Website (Landing, Pricing, Docs)
app.mount("/site", StaticFiles(directory="static/site", html=True), name="brand-site")

# Mount Original Dashboard Interface
app.mount("/dash", StaticFiles(directory="static", html=True), name="static")

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
