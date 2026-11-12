"""Merchant onboarding: setup checklist, connect PayPal, finish setup, import a PayPal order."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import Db
from app.models.entities import Order, Product, now_utc
from app.schemas import OrderImportInput, PayPalConnectInput
from app.security import Merchant
from app.serializers import add_action, order_dict
from app.services import onboarding
from app.services.channel3 import parse_retailers
from app.services.claims import get_settings_row
from app.services.paypal import PayPalError, paypal

router = APIRouter(prefix="/api/v1")
settings = get_settings()


def _mask(value: str) -> str:
    return f"{value[:6]}…{value[-4:]}" if len(value) > 12 else "…"


@router.get("/setup")
def setup_overview(db: Db, _: Merchant):
    row = get_settings_row(db)
    products = db.scalar(select(func.count(Product.id)).where(Product.active.is_(True))) or 0
    linked = db.scalar(select(func.count(Product.id)).where(Product.active.is_(True), Product.channel3_product_id.is_not(None))) or 0
    protected_orders = db.scalar(select(func.count(Order.id)).where(Order.captured_at.is_not(None))) or 0
    imported_orders = db.scalar(select(func.count(Order.id)).where(Order.source == "import")) or 0
    connected = bool(row.paypal_client_id and row.paypal_client_secret_enc)
    base = settings.app_base_url.rstrip("/")
    return {
        "store": {"merchant_name": row.merchant_name, "store_url": row.store_url or "", "gross_margin_percentage": float(row.gross_margin_percentage or 0),
                  "owner_email": row.owner_email or None},
        "paypal": {
            "connected": connected, "source": paypal.credential_source, "environment": settings.paypal_env,
            "client_id": _mask(row.paypal_client_id if connected else paypal.client_id) if paypal.ready else None,
            "connected_at": row.paypal_connected_at.isoformat() if row.paypal_connected_at else None,
            "webhook_url": onboarding.webhook_url(), "webhook_registered": bool(row.paypal_webhook_id),
            "webhook_events": onboarding.WEBHOOK_EVENTS,
        },
        "policy": {"price_protection_window_days": row.price_protection_window_days, "max_refund_per_order": float(row.max_refund_per_order),
                   "daily_refund_budget": float(row.daily_refund_budget), "allowed_retailers": parse_retailers(row.allowed_retailers)},
        "catalog": {"products": products, "linked": linked},
        "orders": {"protected": protected_orders, "imported": imported_orders},
        "install": {"portal_url": f"{base}/portal", "store_url": f"{base}/store",
                    "email_snippet": (f"Price drop after you buy? {row.merchant_name} refunds the difference for "
                                      f"{row.price_protection_window_days} days. Check your order: {base}/portal")},
        "completed": row.onboarding_completed_at is not None,
        "completed_at": row.onboarding_completed_at.isoformat() if row.onboarding_completed_at else None,
    }


@router.post("/setup/paypal")
async def connect_paypal(body: PayPalConnectInput, db: Db, merchant: Merchant):
    row = get_settings_row(db)
    try:
        webhook = await onboarding.connect_paypal(db, row, body.client_id, body.client_secret)
    except PayPalError as exc:
        raise HTTPException(exc.status_code if exc.status_code < 500 else 502, str(exc)) from exc
    db.commit()
    return {"connected": True, "webhook": webhook, "setup": setup_overview(db, merchant)}


@router.delete("/setup/paypal")
def disconnect_paypal(db: Db, merchant: Merchant):
    row = get_settings_row(db)
    row.paypal_client_id = ""
    row.paypal_client_secret_enc = ""
    row.paypal_webhook_id = ""
    row.paypal_connected_at = None
    onboarding.apply_saved_credentials(row)
    add_action(db, "PAYPAL_DISCONNECTED", "merchant", "default", {})
    db.commit()
    return setup_overview(db, merchant)


@router.post("/setup/complete")
def complete_setup(db: Db, merchant: Merchant):
    row = get_settings_row(db)
    if not paypal.ready:
        raise HTTPException(409, "Connect a PayPal account before going live.")
    if not db.scalar(select(func.count(Product.id)).where(Product.active.is_(True))):
        raise HTTPException(409, "Add at least one product to protect before going live.")
    row.onboarding_completed_at = row.onboarding_completed_at or now_utc()
    add_action(db, "ONBOARDING_COMPLETED", "merchant", "default", {"store": row.merchant_name})
    db.commit()
    return setup_overview(db, merchant)


@router.post("/orders/import")
async def import_order(body: OrderImportInput, db: Db, _: Merchant):
    if not paypal.ready:
        raise HTTPException(409, "Connect a PayPal account first.")
    order = await onboarding.import_paypal_order(db, body.paypal_order_id.upper(), source="merchant")
    if not order:
        raise HTTPException(404, "PayPal has no completed order with that ID for the connected account.")
    return order_dict(order)
