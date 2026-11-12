"""Merchant sign-in and buyer sign-in."""

import hmac
import re

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.deps import Db
from app.models.entities import Order
from app.schemas import BuyerLoginInput, LoginInput, SignupInput
from app.serializers import add_action
from app.services import onboarding
from app.services.claims import get_settings_row
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


def _owner_matches(row, email: str, password: str) -> bool:
    if not row.owner_email or not row.owner_password_hash:
        return False
    return hmac.compare_digest(email, row.owner_email.strip().lower()) & onboarding.verify_password(password, row.owner_password_hash)


def _env_matches(email: str, password: str) -> bool:
    if not (settings.merchant_email and settings.merchant_password) and not settings.is_production:
        expected_email, expected_password = merchant_credentials()
    elif settings.merchant_email and settings.merchant_password:
        expected_email, expected_password = settings.merchant_email, settings.merchant_password
    else:
        return False
    return hmac.compare_digest(email, expected_email.strip().lower()) & hmac.compare_digest(password, expected_password)


def _signup_code_required() -> bool:
    # A public deployment must not let the first visitor claim the workspace.
    return settings.is_production or bool(settings.signup_code)


@router.get("/auth/signup")
def signup_status(db: Db):
    row = get_settings_row(db)
    open_ = not row.owner_password_hash and (bool(settings.signup_code) or not settings.is_production)
    return {"open": open_, "store_name": row.merchant_name, "code_required": _signup_code_required()}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupInput, response: Response, request: Request, db: Db):
    """Create the workspace owner. One owner per DropBack workspace; later sign-ups are refused."""
    bucket = f"merchant-signup:{client_ip(request)}"
    if rate_limited(bucket, LOGIN_LIMIT, LOGIN_WINDOW):
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    record_hit(bucket)
    row = get_settings_row(db)
    if row.owner_password_hash:
        raise HTTPException(409, "This DropBack workspace already has an owner. Sign in instead.")
    if _signup_code_required():
        if not settings.signup_code:
            raise HTTPException(403, "Sign-up is closed on this deployment.")
        if not hmac.compare_digest((body.invite_code or "").strip(), settings.signup_code):
            raise HTTPException(403, "That invite code is not valid.")
    email = body.email.strip().lower()
    row.owner_email = email
    row.owner_password_hash = onboarding.hash_password(body.password)
    row.merchant_name = body.store_name.strip()
    add_action(db, "MERCHANT_SIGNED_UP", "merchant", "default", {"store": row.merchant_name})
    db.commit()
    issue_merchant_session(response, email)
    return {"authenticated": True, "email": email}


@router.post("/auth/login")
def login(body: LoginInput, response: Response, request: Request, db: Db):
    bucket = f"merchant-login:{client_ip(request)}"
    if rate_limited(bucket, LOGIN_LIMIT, LOGIN_WINDOW):
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    email = body.email.strip().lower()
    valid = _owner_matches(get_settings_row(db), email, body.password) or _env_matches(email, body.password)
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
async def buyer_login(body: BuyerLoginInput, request: Request, response: Response, db: Db):
    """Sign in to the buyer portal with an order ID and the email on the buyer's PayPal account."""
    bucket = f"buyer-login:{client_ip(request)}"
    if rate_limited(bucket, LOGIN_LIMIT, LOGIN_WINDOW):
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    key = body.order_id.strip()
    order = db.scalar(select(Order).options(joinedload(Order.items)).where(
        (Order.id == key) | (Order.paypal_order_id == key)))
    if order is None and re.fullmatch(r"[A-Z0-9]{12,24}", key.upper()):
        # Paid through the merchant's own PayPal checkout: import it from PayPal with the merchant's credentials.
        order = await onboarding.import_paypal_order(db, key.upper(), source="buyer_portal")
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
