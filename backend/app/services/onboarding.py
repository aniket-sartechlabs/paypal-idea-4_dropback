"""Merchant onboarding: workspace owner, the merchant's own PayPal app, and order import.

DropBack attaches to a merchant's existing PayPal checkout instead of replacing it:

1. The merchant connects their PayPal REST app (client ID + secret). DropBack verifies it
   with an OAuth token request, stores the secret encrypted, and from then on every
   Orders v2 / Payments v2 call runs as that merchant.
2. Paid orders arrive through the PAYMENT.CAPTURE.COMPLETED webhook (registered for the
   merchant when DropBack has a public HTTPS URL), or when a buyer opens the protection
   portal with a PayPal order ID. Either way DropBack reads the order from PayPal with the
   merchant's credentials, so only orders paid to that merchant can be imported.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models.entities import Capture, MerchantSettings, Order, OrderItem, Product, now_utc
from app.serializers import add_action, as_decimal
from app.services.paypal import PayPalError, paypal

WEBHOOK_EVENTS = ["PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.REFUNDED", "PAYMENT.REFUND.COMPLETED"]
PBKDF2_ROUNDS = 240_000
NAME_MATCH_MIN = 0.82


# -- owner password -------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# -- stored PayPal secret ---------------------------------------------------------------
def _fernet() -> Fernet:
    settings = get_settings()
    secret = settings.secret_key or ("dev-only-dropback-key" if not settings.is_production else "")
    if not secret:
        raise RuntimeError("SECRET_KEY is required to store merchant PayPal credentials.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"paypal-credentials:{secret}".encode()).digest()))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode() if value else ""
    except InvalidToken:
        return ""


def apply_saved_credentials(row: MerchantSettings) -> None:
    """Point the PayPal client at the merchant's connected app (startup and after connecting)."""
    if row.paypal_client_id and row.paypal_client_secret_enc:
        paypal.use_merchant_credentials(row.paypal_client_id, decrypt_secret(row.paypal_client_secret_enc), row.paypal_webhook_id)
    else:
        paypal.use_merchant_credentials("", "")


def webhook_url() -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/api/v1/webhooks/paypal"


async def connect_paypal(db: Session, row: MerchantSettings, client_id: str, client_secret: str) -> dict:
    client_id, client_secret = client_id.strip(), client_secret.strip()
    await paypal.verify_credentials(client_id, client_secret)
    row.paypal_client_id = client_id
    row.paypal_client_secret_enc = encrypt_secret(client_secret)
    row.paypal_connected_at = now_utc()
    row.paypal_webhook_id = ""
    apply_saved_credentials(row)
    webhook = {"url": webhook_url(), "registered": False, "reason": None}
    if webhook["url"].startswith("https://"):
        try:
            row.paypal_webhook_id = await paypal.register_webhook(webhook["url"], WEBHOOK_EVENTS)
            webhook["registered"] = bool(row.paypal_webhook_id)
            apply_saved_credentials(row)
        except PayPalError as exc:
            webhook["reason"] = str(exc)
    else:
        webhook["reason"] = "PayPal only delivers webhooks to a public HTTPS URL. Deploy DropBack (APP_BASE_URL) to receive orders automatically."
    add_action(db, "PAYPAL_CONNECTED", "merchant", "default", {"client_id_suffix": client_id[-6:], "webhook_registered": webhook["registered"]})
    return webhook


# -- order import --------------------------------------------------------------------
def _parse_time(value: str | None) -> datetime:
    if not value:
        return now_utc()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return now_utc()


def match_product(db: Session, sku: str, name: str) -> Product | None:
    if sku:
        product = db.scalar(select(Product).where(Product.sku == sku))
        if product:
            return product
    best, best_ratio = None, 0.0
    for product in db.scalars(select(Product).where(Product.active.is_(True))):
        ratio = SequenceMatcher(None, product.name.lower(), (name or "").lower()).ratio()
        if ratio > best_ratio:
            best, best_ratio = product, ratio
    return best if best_ratio >= NAME_MATCH_MIN else None


def find_order(db: Session, key: str) -> Order | None:
    return db.scalar(select(Order).options(joinedload(Order.items), joinedload(Order.capture))
                     .where((Order.id == key) | (Order.paypal_order_id == key)))


async def import_paypal_order(db: Session, paypal_order_id: str, source: str) -> Order | None:
    """Create a protected order from a completed PayPal order paid to this merchant.

    Returns None when PayPal does not know the order for this merchant's credentials or it
    has no completed capture. An already-known order is returned unchanged.
    """
    paypal_order_id = paypal_order_id.strip()
    existing = find_order(db, paypal_order_id)
    if existing:
        return existing
    if not paypal_order_id or not paypal.ready:
        return None
    try:
        data = await paypal.get_order(paypal_order_id)
    except PayPalError:
        return None  # unknown to this merchant's PayPal app, or not reachable
    units = data.get("purchase_units") or []
    captures = [c for unit in units for c in ((unit.get("payments") or {}).get("captures") or [])]
    capture_data = next((c for c in captures if c.get("status") in {"COMPLETED", "PARTIALLY_REFUNDED"}), None)
    if data.get("status") != "COMPLETED" or not capture_data:
        return None
    if db.scalar(select(Capture).where(Capture.paypal_capture_id == capture_data.get("id"))):
        return find_order(db, paypal_order_id)

    amount = capture_data.get("amount") or {}
    currency = amount.get("currency_code", "USD")
    payer = data.get("payer") or {}
    name = payer.get("name") or {}
    captured_at = _parse_time(capture_data.get("create_time"))
    order = Order(paypal_order_id=paypal_order_id, request_key=f"import-{paypal_order_id}"[:80], status="COMPLETED", source="import",
                  buyer_name=" ".join(filter(None, [name.get("given_name"), name.get("surname")]))[:160],
                  buyer_email=(payer.get("email_address") or "")[:254], total_amount=as_decimal(amount.get("value", "0")),
                  currency=currency, created_at=_parse_time(data.get("create_time")), captured_at=captured_at)
    for unit in units:
        for item in unit.get("items") or []:
            product = match_product(db, item.get("sku") or "", item.get("name") or "")
            order.items.append(OrderItem(product_id=product.id if product else None, sku=(item.get("sku") or (product.sku if product else "UNMATCHED"))[:80],
                                         name=(item.get("name") or "PayPal item")[:160], quantity=int(item.get("quantity") or 1),
                                         unit_price=as_decimal((item.get("unit_amount") or {}).get("value", "0"))))
    if not order.items:
        # A checkout without line items: protect the whole amount against the closest product description.
        description = (units[0].get("description") if units else "") or ""
        product = match_product(db, "", description)
        order.items.append(OrderItem(product_id=product.id if product else None, sku=product.sku if product else "UNMATCHED",
                                     name=(product.name if product else description or "PayPal purchase")[:160], quantity=1,
                                     unit_price=as_decimal(amount.get("value", "0"))))
    db.add(order)
    db.flush()
    db.add(Capture(order_id=order.id, paypal_capture_id=capture_data.get("id"), status="COMPLETED",
                   amount=as_decimal(amount.get("value", "0")), currency=currency,
                   capture_key=f"import-{capture_data.get('id')}"[:80], captured_at=captured_at))
    matched = sum(1 for item in order.items if item.product_id)
    add_action(db, "ORDER_IMPORTED", "order", order.id, {"paypal_order_id": paypal_order_id, "source": source,
                                                         "items": len(order.items), "matched_items": matched})
    db.commit()
    return find_order(db, paypal_order_id)


def setup_status(row: MerchantSettings, product_count: int) -> dict:
    return {
        "store": bool(row.merchant_name and row.merchant_name != "DropBack Demo Store"),
        "paypal": bool(row.paypal_client_id and row.paypal_client_secret_enc) or paypal.credential_source == "env",
        "paypal_source": paypal.credential_source,
        "policy": row.onboarding_completed_at is not None or row.updated_at is not None,
        "catalog": product_count > 0,
        "completed": row.onboarding_completed_at is not None,
        "completed_at": row.onboarding_completed_at.isoformat() if row.onboarding_completed_at else None,
    }


def money_value(value) -> float:
    return float(as_decimal(value or Decimal("0")))
