import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.database import Base, SessionLocal, engine, get_db
from app.models.entities import AgentAction, Capture, Decision, MerchantSettings, Order, OrderItem, PriceDrop, Product, Refund, WebhookReceipt, now_utc
from app.services.agent import deterministic_score, explain_decision
from app.services.channel3 import Channel3Error, channel3
from app.services.paypal import PayPalError, paypal


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dropback")
settings = get_settings()
COOKIE_NAME = "dropback_session"
serializer = URLSafeTimedSerializer(settings.secret_key or ("dev-only-dropback-key" if not settings.is_production else ""), salt="dropback-session-v1")
login_failures: dict[str, list[float]] = {}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


app = FastAPI(title="DropBack", version="1.0.0", docs_url="/api/docs" if not settings.is_production else None, redoc_url=None, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type", "Idempotency-Key"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method in {"POST", "PATCH", "DELETE"} and request.url.path.startswith("/api/v1/") and request.url.path not in {"/api/v1/auth/login", "/api/v1/webhooks/paypal"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in {item.rstrip("/") for item in settings.cors_origins}:
            return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class CartItemInput(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=20)


class OrderInput(BaseModel):
    items: list[CartItemInput] = Field(min_length=1, max_length=20)


class ProductInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    sku: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="General", max_length=80)
    current_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    protection_days: int = Field(default=14, ge=1, le=90)
    merchant_domain: str | None = Field(default=None, max_length=255)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        value = value.upper()
        if value != "USD":
            raise ValueError("This PayPal checkout currently supports USD only.")
        return value

    @field_validator("sku")
    @classmethod
    def normalized_sku(cls, value: str) -> str:
        return value.strip().upper()


class PriceUpdate(BaseModel):
    new_price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class SettingsUpdate(BaseModel):
    merchant_name: str | None = Field(default=None, min_length=2, max_length=120)
    price_protection_window_days: int | None = Field(default=None, ge=1, le=90)
    max_refund_per_order: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    daily_refund_budget: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    auto_refund_enabled: bool | None = None
    min_price_drop_percentage: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=3)
    min_price_drop_amount: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    return_shipping_cost: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    restocking_fee_percentage: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=3)
    open_box_discount_percentage: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=3)


def as_decimal(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money(value) -> float:
    return float(as_decimal(value))


def add_action(db: Session, action_type: str, entity_type: str = "", entity_id: str = "", details: dict | None = None) -> None:
    db.add(AgentAction(action_type=action_type, entity_type=entity_type, entity_id=entity_id, details=json.dumps(details or {}, default=str)))


def get_settings_row(db: Session) -> MerchantSettings:
    row = db.get(MerchantSettings, "default")
    if not row:
        row = MerchantSettings(id="default")
        db.add(row)
        db.flush()
    return row


def product_dict(product: Product) -> dict:
    return {
        "id": product.id, "name": product.name, "sku": product.sku, "description": product.description,
        "category": product.category, "current_price": money(product.current_price), "currency": product.currency,
        "protection_days": product.protection_days, "merchant_domain": product.merchant_domain,
        "channel3_connected": bool(product.channel3_product_id), "active": product.active,
    }


def order_dict(order: Order) -> dict:
    return {
        "id": order.id, "paypal_order_id": order.paypal_order_id, "status": order.status, "source": order.source,
        "buyer_name": order.buyer_name, "buyer_email": order.buyer_email, "total_amount": money(order.total_amount),
        "currency": order.currency, "created_at": order.created_at.isoformat() if order.created_at else None,
        "captured_at": order.captured_at.isoformat() if order.captured_at else None,
        "items": [{"product_id": item.product_id, "sku": item.sku, "name": item.name, "quantity": item.quantity, "unit_price": money(item.unit_price)} for item in order.items],
        "refundable": bool(order.capture and order.capture.paypal_capture_id and order.source == "paypal"),
    }


def decision_dict(decision: Decision) -> dict:
    refund = decision.order.capture.refunded_amount if decision.order.capture else 0
    return {
        "id": decision.id, "price_drop_id": decision.price_drop_id, "order_id": decision.order_id,
        "paypal_order_id": decision.order.paypal_order_id, "buyer_name": decision.order.buyer_name,
        "buyer_email": decision.order.buyer_email, "product_name": decision.price_drop.product.name,
        "sku": decision.price_drop.product.sku, "purchase_price": max((money(item.unit_price) for item in decision.order.items if item.sku == decision.price_drop.product.sku), default=0),
        "refund_amount": money(decision.refund_amount), "currency": decision.order.currency,
        "return_probability": float(decision.return_probability), "estimated_return_cost": money(decision.estimated_return_cost),
        "estimated_savings": money(decision.estimated_savings), "reasoning": decision.reasoning,
        "decision": decision.decision, "status": decision.status, "within_window": decision.within_window,
        "budget_available": decision.budget_available, "source": decision.order.source,
        "can_execute": bool(decision.capture.paypal_capture_id and decision.order.source == "paypal" and decision.status == "APPROVED"),
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


def price_drop_dict(drop: PriceDrop) -> dict:
    return {"id": drop.id, "product_id": drop.product_id, "product_name": drop.product.name, "sku": drop.product.sku,
            "old_price": money(drop.old_price), "new_price": money(drop.new_price), "drop_amount": money(drop.drop_amount),
            "drop_percentage": float(drop.drop_percentage), "source": drop.source, "detected_at": drop.detected_at.isoformat(), "processed": drop.processed}


def signed_in_user(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Sign in to access the merchant dashboard.")
    try:
        payload = serializer.loads(token, max_age=12 * 60 * 60)
    except BadSignature as exc:
        raise HTTPException(401, "Your session expired. Sign in again.") from exc
    if not isinstance(payload, dict) or payload.get("role") != "merchant":
        raise HTTPException(401, "Sign in to access the merchant dashboard.")
    return str(payload.get("email", "merchant"))


Merchant = Annotated[str, Depends(signed_in_user)]
Db = Annotated[Session, Depends(get_db)]


def ensure_demo_credentials() -> tuple[str, str]:
    if settings.merchant_email and settings.merchant_password:
        return settings.merchant_email, settings.merchant_password
    if settings.is_production:
        raise HTTPException(503, "Set MERCHANT_EMAIL and MERCHANT_PASSWORD before enabling merchant sign-in.")
    return "demo@dropback.local", "dropback-demo"


def startup() -> None:
    if settings.is_production and (not settings.secret_key or len(settings.secret_key) < 32):
        raise RuntimeError("Production requires a SECRET_KEY of at least 32 characters.")
    if settings.is_production and not settings.paypal_ready:
        raise RuntimeError("Production requires PayPal credentials.")
    if settings.is_production and not settings.channel3_api_key:
        raise RuntimeError("Production requires CHANNEL3_API_KEY because Channel3 powers price monitoring.")
    if settings.is_production and not settings.channel3_webhook_secret:
        raise RuntimeError("Production requires CHANNEL3_WEBHOOK_SECRET for authenticated price-change events.")
    if settings.is_production and not settings.paypal_webhook_id:
        raise RuntimeError("Production requires PAYPAL_WEBHOOK_ID for authenticated payment events.")
    if settings.is_production and not settings.app_base_url.startswith("https://"):
        raise RuntimeError("Production APP_BASE_URL must use HTTPS.")
    if settings.is_production and (not settings.merchant_email or not settings.merchant_password):
        raise RuntimeError("Production requires MERCHANT_EMAIL and MERCHANT_PASSWORD.")
    if settings.is_production:
        if not inspect(engine).has_table("products"):
            raise RuntimeError("Production database schema is missing. Apply Alembic migrations first.")
    else:
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        get_settings_row(db)
        if not settings.is_production and db.scalar(select(func.count(Product.id))) == 0:
            seed_demo_data(db)
        db.commit()


def seed_demo_data(db: Session) -> None:
    products = [
        Product(name="Barista Express Espresso Machine", sku="ESPRESSO-BARISTA-01", description="A stainless steel espresso machine built for better mornings.", category="Appliances", current_price=Decimal("499.00"), currency="USD", protection_days=14),
        Product(name="Studio ANC Headphones", sku="AUDIO-STUDIO-02", description="Comfortable over-ear headphones with adaptive noise cancellation.", category="Electronics", current_price=Decimal("249.00"), currency="USD", protection_days=14),
        Product(name="Everyday Carry Backpack", sku="BAG-EVERYDAY-03", description="Weather-resistant recycled fabric with a padded laptop sleeve.", category="Accessories", current_price=Decimal("119.00"), currency="USD", protection_days=14),
    ]
    db.add_all(products)
    db.flush()
    demo_orders = [
        (products[0], 1, Decimal("499.00"), 2, "Maya Chen"),
        (products[0], 1, Decimal("499.00"), 5, "Rohan Shah"),
        (products[0], 1, Decimal("479.00"), 8, "Alex Morgan"),
        (products[1], 1, Decimal("249.00"), 1, "Priya Nair"),
        (products[1], 1, Decimal("249.00"), 6, "Jordan Lee"),
        (products[2], 2, Decimal("119.00"), 4, "Sam Rivera"),
        (products[2], 1, Decimal("119.00"), 12, "Taylor Brooks"),
    ]
    for product, quantity, unit_price, days_ago, name in demo_orders:
        created = now_utc() - timedelta(days=days_ago, hours=2)
        order = Order(request_key=f"sample-{uuid4()}", status="COMPLETED", source="sample", buyer_name=name,
                      buyer_email="", total_amount=unit_price * quantity, currency="USD", created_at=created, captured_at=created)
        order.items.append(OrderItem(product_id=product.id, sku=product.sku, name=product.name, quantity=quantity, unit_price=unit_price))
        order.capture = Capture(status="COMPLETED", amount=unit_price * quantity, refunded_amount=Decimal("0.00"), currency="USD", capture_key=f"sample-capture-{uuid4()}", captured_at=created)
        db.add(order)
    add_action(db, "DEMO_DATA_SEEDED", details={"orders": len(demo_orders), "notice": "Sample orders cannot be refunded."})


async def clear_channel3_link(product: Product) -> None:
    if product.channel3_subscription_id:
        try:
            await channel3.unsubscribe(product.channel3_subscription_id)
        except Channel3Error as exc:
            # Stop routing this product to the stale Channel3 ID even if remote cleanup needs retrying.
            log.warning("Could not remove stale Channel3 subscription for product %s: %s", product.id, exc)
    product.channel3_product_id = None
    product.channel3_subscription_id = None
    product.last_market_price = None


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "environment": settings.environment, "paypal_configured": settings.paypal_ready,
            "paypal_environment": settings.paypal_env, "channel3_configured": bool(settings.channel3_api_key),
            "channel3_webhook_configured": bool(settings.channel3_webhook_secret),
            "llm_configured": bool(settings.openai_api_key or settings.gemini_api_key)}


@app.get("/api/v1/auth/me")
def auth_me(request: Request):
    try:
        email = signed_in_user(request)
        return {"authenticated": True, "email": email}
    except HTTPException:
        return {"authenticated": False}


@app.post("/api/v1/auth/login")
def login(body: LoginInput, response: Response, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    recent_failures = [stamp for stamp in login_failures.get(client_ip, []) if time.time() - stamp < 900]
    login_failures[client_ip] = recent_failures
    if len(recent_failures) >= 8:
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    expected_email, expected_password = ensure_demo_credentials()
    valid = hmac.compare_digest(body.email.strip().lower(), expected_email.strip().lower()) and hmac.compare_digest(body.password, expected_password)
    if not valid:
        login_failures[client_ip].append(time.time())
        raise HTTPException(401, "Email or password is incorrect.")
    login_failures.pop(client_ip, None)
    token = serializer.dumps({"role": "merchant", "email": expected_email.strip().lower(), "issued": int(time.time())})
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=settings.session_cookie_secure or settings.is_production, samesite="lax", max_age=12 * 60 * 60, path="/")
    return {"authenticated": True, "email": expected_email.strip().lower()}


@app.post("/api/v1/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=settings.session_cookie_secure or settings.is_production)
    return {"authenticated": False}


@app.get("/api/v1/paypal/config")
def paypal_config():
    if not settings.paypal_ready:
        return {"configured": False, "client_id": None, "environment": settings.paypal_env}
    return {"configured": True, "client_id": settings.paypal_client_id, "environment": settings.paypal_env}


@app.get("/api/v1/products")
def list_products(db: Db):
    return [product_dict(item) for item in db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.created_at)).all()]


@app.post("/api/v1/products", status_code=201)
def create_product(body: ProductInput, db: Db, _: Merchant):
    product = Product(**body.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "That SKU already exists.") from exc
    add_action(db, "PRODUCT_CREATED", "product", product.id, {"sku": product.sku})
    db.commit()
    return product_dict(product)


@app.get("/api/v1/products/{product_id}")
def get_product(product_id: str, db: Db):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    return product_dict(product)


def record_price_drop(db: Session, product: Product, new_price: Decimal, source: str) -> PriceDrop | None:
    old_price = as_decimal(product.last_market_price if product.last_market_price is not None else product.current_price)
    new_price = as_decimal(new_price)
    if new_price >= old_price:
        return None
    percent = (old_price - new_price) / old_price * Decimal("100") if old_price else Decimal("0")
    # Avoid duplicate decisions when the same offer is returned by repeated checks.
    recent = db.scalar(select(PriceDrop).where(PriceDrop.product_id == product.id, PriceDrop.new_price == new_price,
                                                   PriceDrop.detected_at >= now_utc() - timedelta(hours=12)))
    if recent:
        return recent
    drop = PriceDrop(product_id=product.id, old_price=old_price, new_price=new_price, drop_amount=old_price - new_price,
                     drop_percentage=percent.quantize(Decimal("0.001")), source=source)
    db.add(drop)
    db.flush()
    add_action(db, "PRICE_DROP_DETECTED", "price_drop", drop.id, {"product_id": product.id, "source": source, "old": str(old_price), "new": str(new_price)})
    return drop


@app.patch("/api/v1/products/{product_id}/price")
def update_price(product_id: str, body: PriceUpdate, db: Db, _: Merchant):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    old_price = as_decimal(product.current_price)
    new_price = as_decimal(body.new_price)
    drop = record_price_drop(db, product, new_price, "merchant") if new_price < old_price else None
    product.current_price = new_price
    if drop:
        product.last_market_price = new_price
    db.commit()
    return {"product": product_dict(product), "price_drop": price_drop_dict(drop) if drop else None}


@app.post("/api/v1/products/{product_id}/channel3-check")
async def check_channel3(product_id: str, db: Db, _: Merchant):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    try:
        observation = await channel3.search_and_compare(product.name, product.sku, money(product.current_price), product.currency)
    except Channel3Error as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not observation.get("matched"):
        if product.channel3_product_id or product.channel3_subscription_id:
            await clear_channel3_link(product)
            add_action(db, "CHANNEL3_LINK_CLEARED", "product", product.id, {"reason": "No confident current product match."})
            db.commit()
        return observation
    matched_product_id = observation.get("product_id")
    if not matched_product_id:
        raise HTTPException(502, "Channel3 matched the title without a stable product ID, so DropBack cannot safely monitor it.")
    if product.channel3_product_id and product.channel3_product_id != str(matched_product_id):
        await clear_channel3_link(product)
    product.channel3_product_id = str(matched_product_id)
    # Channel3 subscriptions provide ongoing, daily-refreshed price-change events. Live search remains the immediate check.
    if product.channel3_product_id and not product.channel3_subscription_id:
        try:
            product.channel3_subscription_id = await channel3.subscribe(product.channel3_product_id, product.merchant_domain)
        except Channel3Error as exc:
            log.warning("Channel3 subscription setup failed for product %s: %s", product.id, exc)
    best_price = as_decimal(observation["best_offer"]["price"])
    old_reference = as_decimal(product.last_market_price if product.last_market_price is not None else product.current_price)
    drop = record_price_drop(db, product, best_price, "channel3") if best_price < old_reference else None
    product.last_market_price = best_price
    add_action(db, "CHANNEL3_PRICE_CHECK", "product", product.id, {"offer": observation["best_offer"], "match_confidence": observation["match_confidence"], "subscription_created": bool(product.channel3_subscription_id)})
    db.commit()
    observation["price_drop"] = price_drop_dict(drop) if drop else None
    observation["subscription_active"] = bool(product.channel3_subscription_id)
    observation["subscription_note"] = "Channel3 can send ongoing price-change events after a webhook URL is registered in its dashboard." if product.channel3_subscription_id else None
    return observation


@app.get("/api/v1/price-drops")
def list_price_drops(db: Db, _: Merchant):
    drops = db.scalars(select(PriceDrop).options(joinedload(PriceDrop.product)).order_by(PriceDrop.detected_at.desc()).limit(100)).all()
    return [price_drop_dict(drop) for drop in drops]


@app.get("/api/v1/orders")
def list_orders(db: Db, _: Merchant):
    orders = db.scalars(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).order_by(Order.created_at.desc()).limit(250)).unique().all()
    return [order_dict(order) for order in orders]


@app.get("/api/v1/orders/{order_id}")
def get_order(order_id: str, db: Db, _: Merchant):
    order = db.scalar(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).where(Order.id == order_id))
    if not order:
        raise HTTPException(404, "Order not found.")
    return order_dict(order)


def money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


@app.post("/api/v1/orders", status_code=201)
async def create_order(body: OrderInput, db: Db, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    if not settings.paypal_ready:
        raise HTTPException(503, "PayPal sandbox credentials are required for checkout.")
    request_key = (idempotency_key or "").strip()
    if not request_key or len(request_key) < 8 or len(request_key) > 80:
        raise HTTPException(400, "Send an Idempotency-Key header of 8–80 characters.")
    existing = db.scalar(select(Order).options(joinedload(Order.items)).where(Order.request_key == request_key))
    if existing and existing.paypal_order_id:
        return {"order_id": existing.paypal_order_id, "internal_order_id": existing.id, "status": existing.status}
    products_by_id = {item.id: item for item in db.scalars(select(Product).where(Product.active.is_(True), Product.id.in_([item.product_id for item in body.items]))).all()}
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
    if existing:
        if existing.request_hash and existing.request_hash != request_hash:
            raise HTTPException(409, "This Idempotency-Key was already used for a different cart.")
        db.delete(existing)
        db.flush()
    internal_id = str(uuid4())
    order = Order(id=internal_id, request_key=request_key, request_hash=request_hash, status="CREATING", source="paypal", total_amount=total, currency="USD")
    for item in line_items:
        order.items.append(OrderItem(product_id=item["product_id"], sku=item["sku"], name=item["name"], quantity=item["quantity"], unit_price=Decimal(item["unit_price"])))
    db.add(order)
    db.commit()
    brand = get_settings_row(db).merchant_name
    try:
        response = await paypal.create_order(order.id, request_key, line_items, money_text(total), "USD", brand)
    except PayPalError as exc:
        order.status = "CREATE_FAILED"
        db.commit()
        raise HTTPException(exc.status_code, str(exc), headers={"X-Request-Id": request_key}) from exc
    order.paypal_order_id = response.get("id")
    order.status = response.get("status", "CREATED")
    db.commit()
    return {"order_id": order.paypal_order_id, "internal_order_id": order.id, "status": order.status}


@app.post("/api/v1/orders/{order_id}/cancel")
def cancel_order(order_id: str, db: Db):
    order = db.scalar(select(Order).where((Order.id == order_id) | (Order.paypal_order_id == order_id)))
    if not order:
        raise HTTPException(404, "Order not found.")
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


@app.post("/api/v1/orders/{order_id}/capture")
async def capture_order(order_id: str, db: Db):
    order = db.scalar(select(Order).options(joinedload(Order.capture)).where((Order.id == order_id) | (Order.paypal_order_id == order_id)))
    if not order:
        raise HTTPException(404, "Order not found.")
    if order.capture:
        return {"status": "COMPLETED", "capture_id": order.capture.paypal_capture_id, "internal_order_id": order.id}
    if order.status == "CANCELLED":
        raise HTTPException(409, "This checkout was cancelled and cannot be captured.")
    if not order.paypal_order_id or order.source != "paypal":
        raise HTTPException(400, "This sample order cannot be captured.")
    request_id = f"capture-{order.id}"
    try:
        response = await paypal.capture_order(order.paypal_order_id, request_id)
    except PayPalError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    capture_data = next((capture for unit in response.get("purchase_units", []) for capture in unit.get("payments", {}).get("captures", [])), None)
    if not capture_data or capture_data.get("status") != "COMPLETED":
        raise HTTPException(502, "PayPal did not confirm a completed capture.")
    amount = capture_data.get("amount", {})
    capture = Capture(paypal_capture_id=capture_data["id"], status=capture_data["status"], amount=as_decimal(amount.get("value")), currency=amount.get("currency_code", order.currency), capture_key=request_id)
    order.capture = capture
    order.status = "COMPLETED"
    order.captured_at = now_utc()
    payer = response.get("payer", {})
    name = payer.get("name", {})
    order.buyer_name = " ".join(part for part in [name.get("given_name"), name.get("surname")] if part)
    order.buyer_email = payer.get("email_address", "")[:254]
    add_action(db, "PAYPAL_CAPTURE_COMPLETED", "order", order.id, {"paypal_capture_id": capture.paypal_capture_id, "amount": money(capture.amount)})
    db.commit()
    return {"status": "COMPLETED", "capture_id": capture.paypal_capture_id, "internal_order_id": order.id, "amount": money(capture.amount), "currency": capture.currency}


@app.post("/api/v1/price-drops/{drop_id}/process")
async def process_price_drop(drop_id: str, db: Db, _: Merchant):
    drop = db.scalar(select(PriceDrop).options(joinedload(PriceDrop.product)).where(PriceDrop.id == drop_id))
    if not drop:
        raise HTTPException(404, "Price drop not found.")
    if drop.processed:
        existing = db.scalars(select(Decision).options(joinedload(Decision.order), joinedload(Decision.capture), joinedload(Decision.price_drop).joinedload(PriceDrop.product)).where(Decision.price_drop_id == drop.id)).unique().all()
        return [decision_dict(row) for row in existing]
    current_settings = get_settings_row(db)
    product = drop.product
    candidates = db.scalars(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).where(Order.status == "COMPLETED", Order.captured_at.is_not(None))).unique().all()
    today = now_utc().date()
    spent = sum(money(item.amount) for item in db.scalars(select(Refund).where(Refund.status.in_(["PENDING", "COMPLETED"]), func.date(Refund.created_at) == today)).all())
    pending_reserved = money(db.scalar(
        select(func.coalesce(func.sum(Decision.refund_amount), 0)).select_from(Decision)
        .outerjoin(Refund, Refund.decision_id == Decision.id)
        .where(Decision.status.in_(["PENDING_REVIEW", "APPROVED"]), Decision.decision == "REFUND", Refund.id.is_(None))
    ))
    budget_left = max(0.0, money(current_settings.daily_refund_budget) - spent - pending_reserved)
    created: list[Decision] = []
    eligible_days = min(product.protection_days, current_settings.price_protection_window_days)
    for order in candidates:
        matching = [item for item in order.items if item.sku == product.sku]
        if not matching or not order.capture:
            continue
        if db.scalar(select(Decision.id).where(Decision.price_drop_id == drop.id, Decision.order_id == order.id)):
            continue
        captured_at = order.captured_at or order.created_at
        days_since = max(0, (now_utc() - captured_at).days)
        within_window = days_since <= eligible_days
        price_difference = sum(max(Decimal("0"), as_decimal(item.unit_price) - as_decimal(drop.new_price)) * item.quantity for item in matching)
        remaining_capture = max(Decimal("0"), as_decimal(order.capture.amount) - as_decimal(order.capture.refunded_amount))
        refund_amount = min(price_difference, remaining_capture, as_decimal(current_settings.max_refund_per_order))
        budget_available = float(refund_amount) <= budget_left
        purchase_value = sum(as_decimal(item.unit_price) * item.quantity for item in matching)
        buyer_drop_percentage = float(refund_amount / purchase_value * Decimal("100")) if purchase_value else 0.0
        min_drop_ok = money(refund_amount) >= money(current_settings.min_price_drop_amount) and buyer_drop_percentage >= float(current_settings.min_price_drop_percentage)
        return_cost = as_decimal(current_settings.return_shipping_cost) * 2 + purchase_value * as_decimal(current_settings.restocking_fee_percentage) / 100 + purchase_value * as_decimal(current_settings.open_box_discount_percentage) / 100
        gross_savings_if_returned = return_cost - refund_amount
        prior_probability, _ = deterministic_score(product.category, float(drop.drop_percentage), days_since)
        probability, model_reason, provider = await explain_decision(product.category, float(drop.drop_percentage), days_since, prior_probability, float(gross_savings_if_returned))
        expected_savings = return_cost * as_decimal(probability) - refund_amount
        recommend = within_window and min_drop_ok and budget_available and refund_amount > 0 and expected_savings > 0 and probability >= 0.25
        if not within_window:
            reason = f"Outside the {eligible_days}-day protection window; no refund recommended."
        elif not min_drop_ok:
            reason = "This drop is below the merchant’s minimum amount or percentage."
        elif refund_amount <= 0:
            reason = "No refundable difference remains for this order."
        elif not budget_available:
            reason = "The daily refund budget is reserved or exhausted."
        elif expected_savings <= 0:
            reason = f"Probability-weighted return cost (${float(return_cost * as_decimal(probability)):.2f}) does not exceed the refund amount."
        elif probability < 0.25:
            reason = "Return likelihood is below the merchant’s decision threshold."
        else:
            reason = model_reason
        decision = Decision(price_drop_id=drop.id, capture_id=order.capture.id, order_id=order.id,
                            decision="REFUND" if recommend else "SKIP", refund_amount=refund_amount if recommend else Decimal("0.00"),
                            reasoning=f"{reason} [scoring: {provider}]", return_probability=probability,
                            estimated_return_cost=return_cost, estimated_savings=max(Decimal("0.00"), expected_savings) if recommend else Decimal("0.00"),
                            within_window=within_window, budget_available=budget_available, status="PENDING_REVIEW" if recommend else "SKIPPED")
        db.add(decision)
        created.append(decision)
        if recommend:
            budget_left = max(0, budget_left - float(refund_amount))
    drop.processed = True
    add_action(db, "PRICE_DROP_PROCESSED", "price_drop", drop.id, {"decisions_created": len(created), "recommendations": sum(item.decision == "REFUND" for item in created)})
    db.commit()
    for item in created:
        db.refresh(item)
        item.order = db.scalar(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).where(Order.id == item.order_id))
        item.capture = db.get(Capture, item.capture_id)
        item.price_drop = db.scalar(select(PriceDrop).options(joinedload(PriceDrop.product)).where(PriceDrop.id == item.price_drop_id))
    return [decision_dict(item) for item in created]


@app.get("/api/v1/agent/decisions")
def list_decisions(db: Db, _: Merchant):
    rows = db.scalars(select(Decision).options(joinedload(Decision.order).joinedload(Order.items), joinedload(Decision.order).joinedload(Order.capture), joinedload(Decision.capture), joinedload(Decision.price_drop).joinedload(PriceDrop.product)).order_by(Decision.created_at.desc()).limit(500)).unique().all()
    return [decision_dict(item) for item in rows]


@app.post("/api/v1/agent/decisions/{decision_id}/approve")
def approve_decision(decision_id: str, db: Db, _: Merchant):
    row = db.scalar(select(Decision).where(Decision.id == decision_id))
    if not row:
        raise HTTPException(404, "Decision not found.")
    if row.decision != "REFUND" or row.status not in {"PENDING_REVIEW", "APPROVED"}:
        raise HTTPException(409, "Only pending refund recommendations can be approved.")
    row.status = "APPROVED"
    row.reviewed_at = now_utc()
    add_action(db, "REFUND_APPROVED", "decision", row.id, {"approved_by": "merchant"})
    db.commit()
    return {"status": row.status, "decision_id": row.id, "sample_order": row.order.source == "sample", "can_execute": bool(row.capture.paypal_capture_id and row.order.source == "paypal")}


@app.post("/api/v1/agent/decisions/{decision_id}/reject")
def reject_decision(decision_id: str, db: Db, _: Merchant):
    row = db.get(Decision, decision_id)
    if not row:
        raise HTTPException(404, "Decision not found.")
    if row.status not in {"PENDING_REVIEW", "APPROVED"}:
        raise HTTPException(409, "This decision is no longer awaiting review.")
    row.status = "REJECTED"
    row.reviewed_at = now_utc()
    add_action(db, "REFUND_REJECTED", "decision", row.id, {"rejected_by": "merchant"})
    db.commit()
    return {"status": row.status}


@app.post("/api/v1/refunds/{decision_id}/execute")
async def execute_refund(decision_id: str, db: Db, _: Merchant):
    row = db.scalar(select(Decision).options(joinedload(Decision.order), joinedload(Decision.capture)).where(Decision.id == decision_id))
    if not row:
        raise HTTPException(404, "Decision not found.")
    if row.order.source != "paypal" or not row.capture.paypal_capture_id:
        raise HTTPException(409, "This is a sample order. Only PayPal sandbox captures can be refunded.")
    locked_capture = db.scalar(select(Capture).where(Capture.id == row.capture_id).with_for_update())
    if not locked_capture:
        raise HTTPException(409, "The PayPal capture is no longer available.")
    existing = db.scalar(select(Refund).where(Refund.decision_id == row.id))
    if existing and existing.status == "COMPLETED":
        return {"status": existing.status, "refund_id": existing.paypal_refund_id, "amount": money(existing.amount)}
    if row.decision != "REFUND" or row.status not in {"APPROVED", "REFUND_PENDING"}:
        raise HTTPException(409, "Approve the recommendation before issuing a refund.")
    if not existing:
        existing = Refund(decision_id=row.id, capture_id=row.capture_id, amount=as_decimal(row.refund_amount), currency=row.order.currency,
                          status="PENDING", note_to_payer="DropBack price protection: we found a lower price and are refunding the difference.", idempotency_key=f"refund-{row.id}")
        db.add(existing)
    elif existing.status == "FAILED":
        existing.status = "PENDING"
    db.flush()
    reserved_for_capture = money(db.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.capture_id == row.capture_id, Refund.status.in_(["PENDING", "COMPLETED"])
        )
    ))
    current_settings = get_settings_row(db)
    if reserved_for_capture > money(locked_capture.amount) or money(existing.amount) > money(current_settings.max_refund_per_order):
        existing.status = "FAILED"
        db.commit()
        raise HTTPException(409, "The refund exceeds the remaining capture balance or the current per-order cap.")
    other_daily = money(db.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.status.in_(["PENDING", "COMPLETED"]), func.date(Refund.created_at) == now_utc().date(), Refund.id != existing.id
        )
    ))
    if other_daily + money(existing.amount) > money(current_settings.daily_refund_budget):
        existing.status = "FAILED"
        db.commit()
        raise HTTPException(409, "The daily refund budget has been reached.")
    db.commit()
    try:
        response = await paypal.refund_capture(row.capture.paypal_capture_id, existing.idempotency_key, money_text(as_decimal(existing.amount)), existing.currency, existing.note_to_payer)
    except PayPalError as exc:
        # Keep PENDING on network failures so a retry reuses the same PayPal idempotency key.
        if exc.status_code != 502:
            existing.status = "FAILED"
            db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc
    existing.paypal_refund_id = response.get("id")
    existing.status = response.get("status", "PENDING")
    if existing.status == "COMPLETED":
        existing.completed_at = now_utc()
        row.capture.refunded_amount = as_decimal(row.capture.refunded_amount) + as_decimal(existing.amount)
        row.capture.status = "REFUNDED" if as_decimal(row.capture.refunded_amount) >= as_decimal(row.capture.amount) else "COMPLETED"
        row.status = "REFUNDED"
    elif existing.status == "PENDING":
        row.status = "REFUND_PENDING"
    add_action(db, "REFUND_ISSUED", "refund", existing.id, {"paypal_refund_id": existing.paypal_refund_id, "amount": money(existing.amount), "status": existing.status})
    db.commit()
    return {"status": existing.status, "refund_id": existing.paypal_refund_id, "amount": money(existing.amount), "currency": existing.currency}


@app.get("/api/v1/refunds")
def list_refunds(db: Db, _: Merchant):
    rows = db.scalars(select(Refund).order_by(Refund.created_at.desc()).limit(500)).all()
    return [{"id": row.id, "decision_id": row.decision_id, "paypal_refund_id": row.paypal_refund_id, "amount": money(row.amount),
             "currency": row.currency, "status": row.status, "note_to_payer": row.note_to_payer, "created_at": row.created_at.isoformat()} for row in rows]


@app.get("/api/v1/refunds/{refund_id}/status")
async def refund_status(refund_id: str, db: Db, _: Merchant):
    row = db.get(Refund, refund_id)
    if not row:
        raise HTTPException(404, "Refund not found.")
    if row.paypal_refund_id and row.status == "PENDING":
        try:
            remote = await paypal.get_refund(row.paypal_refund_id)
            row.status = remote.get("status", row.status)
            if row.status == "COMPLETED" and not row.completed_at:
                row.completed_at = now_utc()
                capture = db.get(Capture, row.capture_id)
                if capture:
                    capture.refunded_amount = as_decimal(capture.refunded_amount) + as_decimal(row.amount)
                    capture.status = "REFUNDED" if as_decimal(capture.refunded_amount) >= as_decimal(capture.amount) else "COMPLETED"
                decision = db.get(Decision, row.decision_id)
                if decision:
                    decision.status = "REFUNDED"
            db.commit()
        except PayPalError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
    return {"id": row.id, "paypal_refund_id": row.paypal_refund_id, "status": row.status, "amount": money(row.amount), "currency": row.currency}


@app.get("/api/v1/dashboard/stats")
def dashboard_stats(db: Db, _: Merchant):
    orders = db.scalars(select(Order).options(joinedload(Order.items), joinedload(Order.capture))).unique().all()
    decisions = db.scalars(select(Decision)).all()
    refunds = db.scalars(select(Refund).where(Refund.status == "COMPLETED")).all()
    pending = db.scalars(select(Decision).where(Decision.status == "PENDING_REVIEW", Decision.decision == "REFUND")).all()
    active_exposure = sum(1 for order in orders if order.capture and order.captured_at and (now_utc() - order.captured_at).days <= get_settings_row(db).price_protection_window_days)
    total_refunded = sum(money(row.amount) for row in refunds)
    savings = sum(money(row.estimated_savings) for row in decisions if row.status in {"APPROVED", "REFUNDED"})
    return {"orders_exposed": active_exposure, "refunds_issued": len(refunds), "total_refunded": round(total_refunded, 2),
            "recommendations_pending": len(pending), "estimated_returns_avoided": len(refunds), "estimated_savings": round(savings, 2),
            "orders_total": len(orders), "decisions_total": len(decisions), "sample_orders": sum(order.source == "sample" for order in orders),
            "paypal_configured": settings.paypal_ready, "channel3_configured": bool(settings.channel3_api_key)}


@app.get("/api/v1/dashboard/timeline")
def dashboard_timeline(db: Db, _: Merchant):
    rows = db.scalars(select(Refund).order_by(Refund.created_at.desc()).limit(30)).all()
    return [{"date": row.created_at.date().isoformat(), "amount": money(row.amount), "status": row.status} for row in rows]


@app.get("/api/v1/settings")
def read_settings(db: Db, _: Merchant):
    row = get_settings_row(db)
    return {"merchant_name": row.merchant_name, "price_protection_window_days": row.price_protection_window_days,
            "max_refund_per_order": money(row.max_refund_per_order), "daily_refund_budget": money(row.daily_refund_budget),
            "auto_refund_enabled": False, "min_price_drop_percentage": float(row.min_price_drop_percentage),
            "min_price_drop_amount": money(row.min_price_drop_amount), "return_shipping_cost": money(row.return_shipping_cost),
            "restocking_fee_percentage": float(row.restocking_fee_percentage), "open_box_discount_percentage": float(row.open_box_discount_percentage),
            "channel3_configured": bool(settings.channel3_api_key), "paypal_environment": settings.paypal_env}


@app.patch("/api/v1/settings")
def update_settings(body: SettingsUpdate, db: Db, _: Merchant):
    if body.auto_refund_enabled:
        raise HTTPException(422, "Automatic refunds are disabled in this build. Merchant approval is required before every payment action.")
    row = get_settings_row(db)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    db.commit()
    return read_settings(db, _)


@app.get("/api/v1/agent/actions")
def list_agent_actions(db: Db, _: Merchant):
    rows = db.scalars(select(AgentAction).order_by(AgentAction.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "action_type": row.action_type, "entity_type": row.entity_type, "entity_id": row.entity_id,
             "details": json.loads(row.details or "{}"), "created_at": row.created_at.isoformat()} for row in rows]


@app.post("/api/v1/webhooks/paypal")
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
    receipt = WebhookReceipt(event_id=event_id, event_type=event_type)
    db.add(receipt)
    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        capture_id = resource.get("id")
        capture = db.scalar(select(Capture).where(Capture.paypal_capture_id == capture_id))
        if capture:
            capture.status = "COMPLETED"
    elif event_type in {"PAYMENT.REFUND.COMPLETED", "PAYMENT.CAPTURE.REFUNDED"}:
        refund_id = resource.get("id")
        refund = db.scalar(select(Refund).where(Refund.paypal_refund_id == refund_id))
        if refund and refund.status != "COMPLETED":
            refund.status = "COMPLETED"
            refund.completed_at = now_utc()
            decision = db.get(Decision, refund.decision_id)
            if decision:
                decision.status = "REFUNDED"
            capture = db.get(Capture, refund.capture_id)
            if capture:
                capture.refunded_amount = as_decimal(capture.refunded_amount) + as_decimal(refund.amount)
                capture.status = "REFUNDED" if as_decimal(capture.refunded_amount) >= as_decimal(capture.amount) else "COMPLETED"
    add_action(db, "PAYPAL_WEBHOOK", "event", event_id, {"event_type": event_type})
    db.commit()
    return {"received": True, "event_type": event_type}


@app.post("/api/v1/webhooks/channel3")
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
    try:
        encoded_secret = secret.removeprefix("whsec_")
        key = base64.b64decode(encoded_secret + "=" * (-len(encoded_secret) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(503, "Channel3 webhook secret is invalid.") from exc
    signed_content = event_id.encode() + b"." + timestamp.encode() + b"." + raw
    expected = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()
    valid = any(hmac.compare_digest(candidate, f"v1,{expected}") for candidate in signatures.split())
    if not valid:
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
                # Search-time matching is stricter than the notification payload. Never create a refund
                # recommendation if the title linked to a subscription has since changed.
                await clear_channel3_link(product)
                add_action(db, "CHANNEL3_LINK_CLEARED", "product", product.id, {"reason": "Webhook product title no longer matches the merchant catalog."})
                db.commit()
                return {"received": True, "event_type": event_type, "matched_product": False}
            best = as_decimal(current["best_offer"]["price"])
            old_reference = as_decimal(product.last_market_price if product.last_market_price is not None else product.current_price)
            drop = record_price_drop(db, product, best, "channel3") if best < old_reference else None
            product.last_market_price = best
            add_action(db, "CHANNEL3_WEBHOOK", "product", product.id, {"event_type": event_type, "offer": current["best_offer"], "price_drop_id": drop.id if drop else None})
        except Channel3Error as exc:
            log.warning("Could not refresh Channel3 product %s after signed webhook: %s", product_id, exc)
    else:
        add_action(db, "CHANNEL3_WEBHOOK", "event", receipt_id, {"event_type": event_type, "matched_product": False})
    db.commit()
    return {"received": True, "event_type": event_type, "matched_product": bool(product)}


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
