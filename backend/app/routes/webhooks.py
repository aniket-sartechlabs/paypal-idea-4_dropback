"""Signed PayPal and Channel3 webhooks."""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.config import get_settings
from app.deps import Db
from app.models.entities import Capture, Product, Refund, WebhookReceipt
from app.serializers import add_action, as_decimal
from app.services import claims
from app.services.channel3 import Channel3Error, channel3
from app.services.paypal import PayPalError, paypal
from app.routes.catalog import clear_channel3_link

log = logging.getLogger("dropback.webhooks")
router = APIRouter(prefix="/api/v1/webhooks")
settings = get_settings()


@router.post("/paypal")
async def paypal_webhook(request: Request, db: Db):
    event = await request.json()
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        verified = await paypal.verify_webhook(headers, event)
    except PayPalError as exc:
        raise HTTPException(502, "PayPal webhook verification service failed.") from exc
    if not verified:
        raise HTTPException(400, "PayPal webhook signature could not be verified.")
    event_id = str(event.get("id", ""))
    if not event_id:
        raise HTTPException(400, "Webhook event is missing its id.")
    if db.get(WebhookReceipt, event_id):
        return {"received": True, "duplicate": True}
    event_type = str(event.get("event_type", ""))
    resource = event.get("resource", {})
    db.add(WebhookReceipt(event_id=event_id, event_type=event_type))
    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        capture = db.scalar(select(Capture).where(Capture.paypal_capture_id == resource.get("id")))
        if capture:
            capture.status = "COMPLETED"
    elif event_type in {"PAYMENT.REFUND.COMPLETED", "PAYMENT.CAPTURE.REFUNDED"}:
        refund = db.scalar(select(Refund).where(Refund.paypal_refund_id == resource.get("id")))
        if refund:
            claims.mark_refund_status(db, refund, "COMPLETED")
    add_action(db, "PAYPAL_WEBHOOK", "event", event_id[:36], {"event_type": event_type})
    db.commit()
    return {"received": True, "event_type": event_type}


def _verify_svix(secret: str, event_id: str, timestamp: str, signatures: str, raw: bytes) -> bool:
    try:
        encoded = secret.removeprefix("whsec_")
        key = base64.b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(503, "Channel3 webhook secret is invalid.") from exc
    expected = base64.b64encode(hmac.new(key, event_id.encode() + b"." + timestamp.encode() + b"." + raw, hashlib.sha256).digest()).decode()
    return any(hmac.compare_digest(candidate, f"v1,{expected}") for candidate in signatures.split())


@router.post("/channel3")
async def channel3_webhook(request: Request, db: Db):
    secret = settings.channel3_webhook_secret
    if not secret:
        raise HTTPException(503, "Channel3 webhook verification is not configured.")
    raw = await request.body()
    event_id = request.headers.get("svix-id", "")
    timestamp = request.headers.get("svix-timestamp", "")
    signatures = request.headers.get("svix-signature", "")
    if not event_id or not timestamp or not signatures:
        raise HTTPException(400, "Missing signed webhook headers.")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(400, "Invalid webhook timestamp.") from exc
    if abs(time.time() - timestamp_value) > 300:
        raise HTTPException(400, "Webhook timestamp is outside the allowed window.")
    if not _verify_svix(secret, event_id, timestamp, signatures, raw):
        raise HTTPException(400, "Channel3 webhook signature could not be verified.")
    receipt_id = f"channel3:{event_id}"
    if db.get(WebhookReceipt, receipt_id):
        return {"received": True, "duplicate": True}
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Webhook body is not valid JSON.") from exc
    event_type = str(event.get("type") or event.get("event_type") or "")[:120]
    data = event.get("data") if isinstance(event.get("data"), dict) else event
    product_id = str(data.get("product_id") or data.get("canonical_product_id") or (data.get("product") or {}).get("id") or "")
    product = db.scalar(select(Product).where(Product.channel3_product_id == product_id)) if product_id else None
    db.add(WebhookReceipt(event_id=receipt_id, event_type=event_type or "unknown"))
    if product:
        try:
            current = await channel3.current_offer(product_id, product.currency)
            if not current.get("title") or not channel3.matches_product(product.name, product.sku, current["title"]):
                # Never create a refund recommendation if the linked listing no longer matches.
                await clear_channel3_link(product)
                add_action(db, "CHANNEL3_LINK_CLEARED", "product", product.id, {"reason": "Webhook product title no longer matches the merchant catalog."})
                db.commit()
                return {"received": True, "event_type": event_type, "matched_product": False}
            best = current["best_offer"]
            best_price = as_decimal(best["price"])
            reference = as_decimal(product.last_market_price if product.last_market_price is not None else product.current_price)
            drop = claims.record_price_drop(db, product, reference, best_price, "channel3", best.get("merchant"), best.get("url")) if best_price < reference else None
            product.last_market_price = best_price
            add_action(db, "CHANNEL3_WEBHOOK", "product", product.id, {"event_type": event_type, "offer": best, "price_drop_id": drop.id if drop else None})
        except Channel3Error as exc:
            log.warning("Could not refresh Channel3 product %s after signed webhook: %s", product_id, exc)
    else:
        add_action(db, "CHANNEL3_WEBHOOK", "event", event_id[:36], {"event_type": event_type, "matched_product": False})
    db.commit()
    return {"received": True, "event_type": event_type, "matched_product": bool(product)}
