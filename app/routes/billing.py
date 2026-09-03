# -*- coding: utf-8 -*-
"""
Horus Flow — Billing & Stripe Integration
"""
import os
import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
import stripe

from app.database import upgrade_user_tier, get_user_by_id
from app.routes.auth import get_current_user

logger = logging.getLogger("Billing")

router_billing = APIRouter()

# ============ Configuration ============

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Price IDs
PRICES = {
    "trader": os.getenv("STRIPE_PRICE_TRADER", "price_trader_placeholder"),
    "pro": os.getenv("STRIPE_PRICE_PRO", "price_pro_placeholder"),
    "institutional": os.getenv("STRIPE_PRICE_INSTITUTIONAL", "price_institutional_placeholder"),
}

# Reverse mapping to easily identify tier from price
PRICE_TO_TIER = {v: k for k, v in PRICES.items()}

SITE_URL = os.getenv("SITE_URL", "https://flow.horustek.pro")


@router_billing.post("/create-checkout-session")
async def create_checkout_session(request: Request, current_user: dict = Depends(get_current_user)):
    """Create a Stripe Checkout Session for a specific tier."""
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Billing system is not configured.")

    try:
        body = await request.json()
        tier = body.get("tier", "").lower()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if tier not in PRICES:
        raise HTTPException(status_code=400, detail="Invalid tier selected")

    price_id = PRICES[tier]

    try:
        # Create Stripe Checkout Session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{SITE_URL}/account.html?upgrade=success",
            cancel_url=f"{SITE_URL}/account.html?upgrade=cancelled",
            client_reference_id=str(current_user["id"]),
            customer_email=current_user["email"],
            metadata={
                "user_id": current_user["id"],
                "tier": tier
            }
        )
        return {"checkout_url": session.url}
    except Exception as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router_billing.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks for subscription updates."""
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("Stripe Webhook Secret not configured!")
        raise HTTPException(status_code=503, detail="Webhook not configured.")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("client_reference_id")
        
        # In case client_reference_id was lost, check metadata
        if not user_id and "metadata" in session:
            user_id = session["metadata"].get("user_id")

        if user_id:
            user_id = int(user_id)
            # Find which tier they bought
            tier = session.get("metadata", {}).get("tier", "")
            if not tier:
                # If tier wasn't in metadata, try finding it via line items
                # Usually we'd use stripe.checkout.Session.list_line_items but metadata is easier
                pass
            
            sub_id = session.get("subscription", "")
            if tier:
                upgrade_user_tier(user_id, tier, sub_id)
                logger.info(f"✅ Webhook: User {user_id} upgraded to {tier} via Checkout")
            else:
                logger.warning(f"⚠️ Webhook: Tier not found in session metadata for User {user_id}")

    elif event["type"] == "customer.subscription.updated":
        sub = event["data"]["object"]
        # If subscription is canceled or unpaid, downgrade
        if sub["status"] not in ["active", "trialing"]:
            # Needs user mapping from customer ID or we rely on invoice
            pass
    
    elif event["type"] == "customer.subscription.deleted":
        sub = event["data"]["object"]
        # Handle subscription deletion/cancellation
        # We need a way to find user by sub_id and downgrade them to 'free'
        from app.database import _get_conn
        conn = _get_conn()
        user = conn.execute("SELECT id FROM users WHERE stripe_sub_id = ?", (sub["id"],)).fetchone()
        conn.close()
        
        if user:
            upgrade_user_tier(user["id"], "free", "")
            logger.info(f"❌ Webhook: User {user['id']} subscription cancelled. Downgraded to free.")

    return JSONResponse(content={"status": "success"})
