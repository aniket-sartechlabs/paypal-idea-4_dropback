"""Storefront checkout: PayPal Orders v2 create, capture, and cancel."""

import hashlib
import json
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.deps import Db
from app.models.entities import Capture, Order, OrderItem, Product, now_utc
from app.schemas import OrderInput
from app.security import Merchant, grant_buyer_order, require_order_access
from app.serializers import add_action, as_decimal, money, money_text, order_dict
from app.services.claims import get_settings_row
from app.services.paypal import PayPalError, paypal

router = APIRouter(prefix="/api/v1")
settings = get_settings()


def _find_order(db, key: str) -> Order | None:
    return db.scalar(select(Order).options(joinedload(Order.items), joinedload(Order.capture))
                     .where((Order.id == key) | (Order.paypal_order_id == key)))


@router.get("/paypal/config")
def paypal_config():
    if not paypal.ready:
        return {"configured": False, "client_id": None, "environment": settings.paypal_env}
    return {"configured": True, "client_id": paypal.client_id, "environment": settings.paypal_env}


@router.get("/orders")
def list_orders(db: Db, _: Merchant):
    orders = db.scalars(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).order_by(Order.created_at.desc()).limit(250)).unique().all()
    return [order_dict(order) for order in orders]


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Db, _: Merchant):
    order = _find_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    return order_dict(order)


@router.post("/orders", status_code=201)
async def create_order(body: OrderInput, request: Request, response: Response, db: Db,
                       idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    if not paypal.ready:
        raise HTTPException(503, "PayPal sandbox credentials are required for checkout.")
    request_key = (idempotency_key or "").strip()
    if not 8 <= len(request_key) <= 80:
        raise HTTPException(400, "Send an Idempotency-Key header of 8–80 characters.")
    products_by_id = {item.id: item for item in db.scalars(select(Product).where(
        Product.active.is_(True), Product.id.in_([item.product_id for item in body.items]))).all()}
    if len(products_by_id) != len({item.product_id for item in body.items}):
        raise HTTPException(400, "One or more cart items are no longer available.")
    line_items = []
    total = Decimal("0.00")
    for cart_item in body.items:
        product = products_by_id[cart_item.product_id]
        unit = as_decimal(product.current_price)
        total += unit * cart_item.quantity
        line_items.append({"product_id": product.id, "name": product.name, "sku": product.sku, "unit_price": money_text(unit), "quantity": cart_item.quantity})
    request_hash = hashlib.sha256(json.dumps(line_items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    existing = db.scalar(select(Order).where(Order.request_key == request_key))
    if existing:
        if existing.request_hash and existing.request_hash != request_hash:
            raise HTTPException(409, "This Idempotency-Key was already used for a different cart.")
        if existing.paypal_order_id:
            grant_buyer_order(request, response, existing.id)
            return {"order_id": existing.paypal_order_id, "internal_order_id": existing.id, "status": existing.status}
        db.delete(existing)  # a previous attempt never reached PayPal; start it again
        db.flush()

    order = Order(id=str(uuid4()), request_key=request_key, request_hash=request_hash, status="CREATING", source="paypal", total_amount=total, currency="USD")
    for item in line_items:
        order.items.append(OrderItem(product_id=item["product_id"], sku=item["sku"], name=item["name"], quantity=item["quantity"], unit_price=Decimal(item["unit_price"])))
    db.add(order)
    db.commit()
    try:
        created = await paypal.create_order(order.id, request_key, line_items, money_text(total), "USD", get_settings_row(db).merchant_name)
    except PayPalError as exc:
        order.status = "CREATE_FAILED"
        db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc
    order.paypal_order_id = created.get("id")
    order.status = created.get("status", "CREATED")
    db.commit()
    # The browser that starts checkout may finish it and open the order afterwards.
    grant_buyer_order(request, response, order.id)
    return {"order_id": order.paypal_order_id, "internal_order_id": order.id, "status": order.status}


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, request: Request, db: Db):
    order = _find_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    require_order_access(request, order)
    if order.capture:
        raise HTTPException(409, "A captured order cannot be cancelled.")
    if order.status == "CANCELLED":
        return {"status": order.status}
    if order.status != "CREATED":
        raise HTTPException(409, "This order can no longer be cancelled.")
    order.status = "CANCELLED"
    add_action(db, "PAYPAL_CHECKOUT_CANCELLED", "order", order.id, {"paypal_order_id": order.paypal_order_id})
    db.commit()
    return {"status": order.status}


@router.post("/orders/{order_id}/capture")
async def capture_order(order_id: str, request: Request, db: Db):
    order = _find_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    require_order_access(request, order)
    if order.capture:
        return {"status": "COMPLETED", "capture_id": order.capture.paypal_capture_id, "internal_order_id": order.id,
                "amount": money(order.capture.amount), "currency": order.capture.currency}
    if order.status == "CANCELLED":
        raise HTTPException(409, "This checkout was cancelled and cannot be captured.")
    if not order.paypal_order_id:
        raise HTTPException(400, "This order was never created in PayPal.")
    request_id = f"capture-{order.id}"
    try:
        result = await paypal.capture_order(order.paypal_order_id, request_id)
    except PayPalError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    capture_data = next((capture for unit in result.get("purchase_units", []) for capture in unit.get("payments", {}).get("captures", [])), None)
    if not capture_data or capture_data.get("status") != "COMPLETED":
        raise HTTPException(502, "PayPal did not confirm a completed capture.")
    amount = capture_data.get("amount", {})
    capture = Capture(paypal_capture_id=capture_data["id"], status=capture_data["status"], amount=as_decimal(amount.get("value")),
                      currency=amount.get("currency_code", order.currency), capture_key=request_id)
    order.capture = capture
    order.status = "COMPLETED"
    order.captured_at = now_utc()
    payer = result.get("payer", {})
    name = payer.get("name", {})
    order.buyer_name = " ".join(part for part in [name.get("given_name"), name.get("surname")] if part)
    order.buyer_email = (payer.get("email_address") or "")[:254]
    add_action(db, "PAYPAL_CAPTURE_COMPLETED", "order", order.id, {"paypal_capture_id": capture.paypal_capture_id, "amount": money(capture.amount)})
    db.commit()
    return {"status": "COMPLETED", "capture_id": capture.paypal_capture_id, "internal_order_id": order.id, "amount": money(capture.amount), "currency": capture.currency}
