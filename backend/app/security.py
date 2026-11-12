"""Sessions and access checks.

Two kinds of signed, httponly cookies:

* Merchant session: issued by email/password sign-in; required for the merchant console.
* Buyer session: lists the order IDs this browser may open. An order is added when the
  browser creates it at checkout, or when the buyer signs in with the order ID and the
  email address on their PayPal account. Buyer endpoints only show orders in that list.
"""

import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import get_settings
from app.models.entities import Order

settings = get_settings()

MERCHANT_COOKIE = "dropback_session"
BUYER_COOKIE = "dropback_buyer"
MERCHANT_MAX_AGE = 12 * 60 * 60
BUYER_MAX_AGE = 30 * 24 * 60 * 60
BUYER_MAX_ORDERS = 25

_secret = settings.secret_key or ("dev-only-dropback-key" if not settings.is_production else "")
merchant_serializer = URLSafeTimedSerializer(_secret, salt="dropback-session-v1")
buyer_serializer = URLSafeTimedSerializer(_secret, salt="dropback-buyer-v1")


# -- rate limiting -------------------------------------------------------------
_hits: dict[str, list[float]] = {}


def rate_limited(bucket: str, limit: int, window_seconds: int) -> bool:
    """Return True when `bucket` already has `limit` hits inside the window."""
    now = time.time()
    recent = [stamp for stamp in _hits.get(bucket, []) if now - stamp < window_seconds]
    _hits[bucket] = recent
    return len(recent) >= limit


def record_hit(bucket: str) -> None:
    _hits.setdefault(bucket, []).append(time.time())


def clear_hits(bucket: str) -> None:
    _hits.pop(bucket, None)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_local_request(request: Request) -> None:
    if client_ip(request) not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(403, "This endpoint is available only on this machine.")


def cookie_secure() -> bool:
    return settings.session_cookie_secure or settings.is_production


# -- merchant session --------------------------------------------------------------
def merchant_email(request: Request) -> str | None:
    token = request.cookies.get(MERCHANT_COOKIE)
    if not token:
        return None
    try:
        payload = merchant_serializer.loads(token, max_age=MERCHANT_MAX_AGE)
    except BadSignature:
        return None
    if not isinstance(payload, dict) or payload.get("role") != "merchant":
        return None
    return str(payload.get("email", "merchant"))


def signed_in_merchant(request: Request) -> str:
    email = merchant_email(request)
    if not email:
        raise HTTPException(401, "Sign in to access the merchant dashboard.")
    return email


def issue_merchant_session(response: Response, email: str) -> None:
    token = merchant_serializer.dumps({"role": "merchant", "email": email, "issued": int(time.time())})
    response.set_cookie(MERCHANT_COOKIE, token, httponly=True, secure=cookie_secure(), samesite="lax", max_age=MERCHANT_MAX_AGE, path="/")


def clear_merchant_session(response: Response) -> None:
    response.delete_cookie(MERCHANT_COOKIE, path="/", httponly=True, samesite="lax", secure=cookie_secure())


Merchant = Annotated[str, Depends(signed_in_merchant)]


# -- buyer session -------------------------------------------------------------------
def buyer_order_ids(request: Request) -> list[str]:
    token = request.cookies.get(BUYER_COOKIE)
    if not token:
        return []
    try:
        payload = buyer_serializer.loads(token, max_age=BUYER_MAX_AGE)
    except BadSignature:
        return []
    orders = payload.get("orders") if isinstance(payload, dict) else None
    return [str(item) for item in orders] if isinstance(orders, list) else []


def grant_buyer_order(request: Request, response: Response, order_id: str) -> None:
    orders = [item for item in buyer_order_ids(request) if item != order_id] + [order_id]
    token = buyer_serializer.dumps({"role": "buyer", "orders": orders[-BUYER_MAX_ORDERS:]})
    response.set_cookie(BUYER_COOKIE, token, httponly=True, secure=cookie_secure(), samesite="lax", max_age=BUYER_MAX_AGE, path="/")


def clear_buyer_session(response: Response) -> None:
    response.delete_cookie(BUYER_COOKIE, path="/", httponly=True, samesite="lax", secure=cookie_secure())


def can_access_order(request: Request, order: Order) -> bool:
    return order.id in buyer_order_ids(request) or merchant_email(request) is not None


def require_order_access(request: Request, order: Order) -> None:
    if not can_access_order(request, order):
        raise HTTPException(403, "Sign in with your order ID and the email address on your PayPal account to view this order.")
