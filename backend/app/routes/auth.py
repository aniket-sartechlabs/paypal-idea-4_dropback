"""Merchant sign-in and buyer sign-in."""

import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.deps import Db
from app.models.entities import Order
from app.schemas import BuyerLoginInput, LoginInput
from app.security import (buyer_order_ids, clear_buyer_session, clear_hits, clear_merchant_session, client_ip, grant_buyer_order,
                          issue_merchant_session, merchant_email, rate_limited, record_hit)

router = APIRouter(prefix="/api/v1")
settings = get_settings()

LOGIN_LIMIT = 8
LOGIN_WINDOW = 15 * 60


def merchant_credentials() -> tuple[str, str]:
    if settings.merchant_email and settings.merchant_password:
        return settings.merchant_email, settings.merchant_password
    if settings.is_production:
        raise HTTPException(503, "Set MERCHANT_EMAIL and MERCHANT_PASSWORD before enabling merchant sign-in.")
    return "demo@dropback.local", "dropback-demo"


@router.get("/auth/me")
def auth_me(request: Request):
    email = merchant_email(request)
    return {"authenticated": True, "email": email} if email else {"authenticated": False}


@router.post("/auth/login")
def login(body: LoginInput, response: Response, request: Request):
    bucket = f"merchant-login:{client_ip(request)}"
    if rate_limited(bucket, LOGIN_LIMIT, LOGIN_WINDOW):
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    expected_email, expected_password = merchant_credentials()
    email = body.email.strip().lower()
    valid = hmac.compare_digest(email, expected_email.strip().lower()) & hmac.compare_digest(body.password, expected_password)
    if not valid:
        record_hit(bucket)
        raise HTTPException(401, "Email or password is incorrect.")
    clear_hits(bucket)
    issue_merchant_session(response, email)
    return {"authenticated": True, "email": email}


@router.post("/auth/logout")
def logout(response: Response):
    clear_merchant_session(response)
    return {"authenticated": False}


# -- buyers -------------------------------------------------------------------------
def _buyer_order_summary(order: Order) -> dict:
    first = order.items[0] if order.items else None
    return {
        "id": order.id, "paypal_order_id": order.paypal_order_id, "status": order.status,
        "item_name": first.name if first else "PayPal order", "total_amount": float(order.total_amount), "currency": order.currency,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


@router.post("/buyer/login")
def buyer_login(body: BuyerLoginInput, request: Request, response: Response, db: Db):
    """Sign in to the buyer portal with an order ID and the email on the buyer's PayPal account."""
    bucket = f"buyer-login:{client_ip(request)}"
    if rate_limited(bucket, LOGIN_LIMIT, LOGIN_WINDOW):
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    key = body.order_id.strip()
    order = db.scalar(select(Order).options(joinedload(Order.items)).where(
        (Order.id == key) | (Order.paypal_order_id == key)))
    email_ok = bool(order and order.buyer_email) and hmac.compare_digest(
        (order.buyer_email or "").strip().lower(), body.email.strip().lower())
    if not order or not email_ok or order.captured_at is None:
        record_hit(bucket)
        raise HTTPException(401, "We couldn't find a completed order with that order ID and PayPal email.")
    clear_hits(bucket)
    grant_buyer_order(request, response, order.id)
    return {"authenticated": True, "order": _buyer_order_summary(order)}


@router.get("/buyer/orders")
def buyer_orders(request: Request, db: Db):
    ids = buyer_order_ids(request)
    if not ids:
        return {"authenticated": False, "orders": []}
    orders = db.scalars(select(Order).options(joinedload(Order.items)).where(
        Order.id.in_(ids), Order.status != "CANCELLED", func.coalesce(Order.paypal_order_id, "") != "")
        .order_by(Order.created_at.desc())).unique().all()
    return {"authenticated": True, "orders": [_buyer_order_summary(order) for order in orders]}


@router.post("/buyer/logout")
def buyer_logout(response: Response):
    clear_buyer_session(response)
    return {"authenticated": False}
