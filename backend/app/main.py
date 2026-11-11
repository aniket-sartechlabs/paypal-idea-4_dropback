import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import secrets
import subprocess
import sys
import time
from pathlib import Path
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
from app.services.agent import deterministic_score, explain_decision, generate_customer_message
from app.services.apimatic_mcp import apimatic_mcp
from app.services.channel3 import Channel3Error, channel3
from app.services.paypal import PayPalError, paypal


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dropback")
settings = get_settings()
COOKIE_NAME = "dropback_session"
serializer = URLSafeTimedSerializer(settings.secret_key or ("dev-only-dropback-key" if not settings.is_production else ""), salt="dropback-session-v1")
login_failures: dict[str, list[float]] = {}
sandbox_demo_process: subprocess.Popen | None = None

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
    channel3_product_id: str | None = Field(default=None, max_length=120)

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


class CheckPriceInput(BaseModel):
    order_id: str | None = None
    product_id: str | None = None


class ClaimSubmitInput(BaseModel):
    order_id: str
    product_id: str | None = None
    price_drop_id: str | None = None
    customer_notes: str = Field(default="", max_length=1500)
    reason: str = Field(default="price_drop_match", max_length=100)


class ClaimResolveInput(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    refund_amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    custom_message: str | None = Field(default=None, max_length=2000)


class APIMaticInvokeInput(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


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
        "image_url": product.image_url if (product.image_url or "").startswith("https://") else None,
        "category": product.category, "current_price": money(product.current_price), "currency": product.currency,
        "protection_days": product.protection_days, "merchant_domain": product.merchant_domain,
        "channel3_connected": bool(product.channel3_product_id), "channel3_product_id": product.channel3_product_id,
        "last_market_price": money(product.last_market_price) if product.last_market_price is not None else None,
        "competitor_name": product.competitor_name, "competitor_url": product.competitor_url,
        "weight_lbs": float(product.weight_lbs) if product.weight_lbs is not None else None,
        "active": product.active,
    }


def order_dict(order: Order) -> dict:
    return {
        "id": order.id, "paypal_order_id": order.paypal_order_id, "status": order.status, "source": order.source,
        "buyer_name": order.buyer_name, "buyer_email": order.buyer_email, "total_amount": money(order.total_amount),
        "currency": order.currency, "created_at": order.created_at.isoformat() if order.created_at else None,
        "captured_at": order.captured_at.isoformat() if order.captured_at else None,
        "items": [{"product_id": item.product_id, "sku": item.sku, "name": item.name, "quantity": item.quantity, "unit_price": money(item.unit_price), "image_url": item.product.image_url if item.product and (item.product.image_url or "").startswith("https://") else None} for item in order.items],
        "refundable": bool(order.capture and order.capture.paypal_capture_id and order.source == "paypal"),
    }


def parse_decision_report(decision: Decision) -> tuple[str, dict]:
    raw = decision.reasoning or ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("reasoning", ""), data
    except Exception:
        pass
    prob = float(decision.return_probability or 0)
    risk_level = "HIGH" if prob >= 0.55 else "MEDIUM" if prob >= 0.3 else "LOW"
    provider = "openai" if "[scoring: openai]" in raw else "gemini" if "[scoring: gemini]" in raw else "rules"
    clean_text = raw.replace("[scoring: openai]", "").replace("[scoring: gemini]", "").replace("[scoring: rules]", "").strip()
    return clean_text, {
        "return_probability": prob,
        "confidence": "HIGH" if provider in {"openai", "gemini"} else "MEDIUM",
        "risk_level": risk_level,
        "key_drivers": [
            f"Evaluated return risk: {round(prob * 100)}% based on market price delta.",
            f"Within merchant's protection window: {'Yes' if decision.within_window else 'No'}.",
            f"Projected net merchant savings: ${money(decision.estimated_savings):.2f} if proactive refund preempts full return.",
        ],
        "reasoning": clean_text,
        "retention_impact": "Proactive price protection converts buyer remorse into brand loyalty.",
        "recommended_action": "APPROVE_PARTIAL_REFUND" if decision.decision == "REFUND" else "POLICY_SKIP",
        "provider": provider,
        "model": "gpt-4.1-mini" if provider == "openai" else "Actuarial Engine",
        "financial_breakdown": {
            "proposed_refund": money(decision.refund_amount),
            "estimated_return_cost": money(decision.estimated_return_cost),
            "net_savings": money(decision.estimated_savings),
        },
    }


def decision_dict(decision: Decision) -> dict:
    refund = decision.order.capture.refunded_amount if decision.order.capture else 0
    reason_text, report = parse_decision_report(decision)
    buyer_name = decision.order.buyer_name or "Buyer"
    product_name = decision.price_drop.product.name if decision.price_drop and decision.price_drop.product else "Item"
    comp_name = decision.competitor_name or (decision.price_drop.product.competitor_name if decision.price_drop and decision.price_drop.product else "authorized retailers")
    drafted_msg = decision.ai_drafted_message or (report.get("drafted_customer_message") if isinstance(report, dict) else "")
    if not drafted_msg:
        drafted_msg = generate_customer_message(buyer_name, product_name, float(decision.refund_amount), comp_name)

    return {
        "id": decision.id, "price_drop_id": decision.price_drop_id, "order_id": decision.order_id,
        "paypal_order_id": decision.order.paypal_order_id, "buyer_name": decision.order.buyer_name,
        "buyer_email": decision.order.buyer_email, "product_name": product_name,
        "sku": decision.price_drop.product.sku if decision.price_drop and decision.price_drop.product else "",
        "purchase_price": max((money(item.unit_price) for item in decision.order.items if item.sku == (decision.price_drop.product.sku if decision.price_drop and decision.price_drop.product else "")), default=0),
        "refund_amount": money(decision.refund_amount), "currency": decision.order.currency,
        "return_probability": float(decision.return_probability), "estimated_return_cost": money(decision.estimated_return_cost),
        "estimated_savings": money(decision.estimated_savings), "reasoning": reason_text,
        "analysis_report": report,
        "evidence_source": report.get("evidence_source", "channel3_live"),
        "customer_claim": bool(decision.customer_claim),
        "customer_notes": decision.customer_notes or "",
        "ai_drafted_message": drafted_msg,
        "merchant_message": decision.merchant_message or "",
        "competitor_name": comp_name,
        "competitor_price": money(decision.competitor_price) if decision.competitor_price else (money(decision.price_drop.new_price) if decision.price_drop else None),
        "decision": decision.decision, "status": decision.status, "within_window": decision.within_window,
        "budget_available": decision.budget_available, "source": decision.order.source,
        "settlement_mode": "paypal_sandbox" if decision.order.source == "paypal" and decision.capture and decision.capture.paypal_capture_id else "demo_ledger",
        "can_execute": bool(decision.capture and decision.capture.paypal_capture_id and decision.order.source == "paypal" and decision.status in {"APPROVED", "PENDING_REVIEW", "REFUND_PENDING", "REFUND_FAILED"}),
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
        "reviewed_at": decision.reviewed_at.isoformat() if decision.reviewed_at else None,
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
        obsolete_coffee_product = db.scalar(select(Product).where(Product.sku == "ESPRESSO-BARISTA-01"))
        if obsolete_coffee_product:
            obsolete_coffee_product.active = False
        # Channel3 does not return product photography for every exact match.
        # Use real manufacturer/retailer product images for the curated electronics catalog.
        image_sources = {
            "SONY-WH1000XM5-BLK": "https://www.sony.com/is/image/gwtprod/6145c1d32e6ac8e63a46c912dc33c5bb?fmt=png-alpha&wid=900",
            "APPLE-AIRPODS-PRO2": "https://suprememobiles.in/cdn/shop/files/1_9ecff0cb-ba43-4945-b7ec-fc04bd2ab716.png?v=1726040725",
            "AMZN-KINDLE-PW16": "https://multimedia.bbycastatic.ca/multimedia/products/1500x1500/189/18909/18909672.jpeg",
        }
        for sku, image_url in image_sources.items():
            catalog_product = db.scalar(select(Product).where(Product.sku == sku))
            if catalog_product and not catalog_product.image_url:
                catalog_product.image_url = image_url
        db.commit()


def seed_demo_data(db: Session) -> None:
    products = [
        Product(
            name="Barista Express Espresso Machine",
            sku="ESPRESSO-BARISTA-01",
            description="Dose-control grinding and micro-foam milk texturing for third-wave specialty espresso at home.",
            category="Appliances",
            current_price=Decimal("499.00"),
            currency="USD",
            protection_days=14,
            channel3_product_id=None,
            last_market_price=None,
            weight_lbs=Decimal("23.00"),
            active=False,
        ),
        Product(
            name="Sony WH-1000XM5 Wireless Noise Canceling Headphones",
            sku="SONY-WH1000XM5-BLK",
            description="Industry-leading noise cancellation, crystal clear hands-free calling, and 30-hour battery life with quick charging.",
            category="Electronics",
            current_price=Decimal("398.00"),
            currency="USD",
            protection_days=14,
            channel3_product_id=None,
            last_market_price=None,
            weight_lbs=Decimal("0.55"),
            image_url="https://www.sony.com/is/image/gwtprod/6145c1d32e6ac8e63a46c912dc33c5bb?fmt=png-alpha&wid=900",
        ),
        Product(
            name="Apple AirPods Pro",
            sku="APPLE-AIRPODS-PRO2",
            description="Active Noise Cancellation, Adaptive Audio, Transparency mode, and USB-C MagSafe charging case.",
            category="Electronics",
            current_price=Decimal("249.00"),
            currency="USD",
            protection_days=14,
            channel3_product_id=None,
            last_market_price=None,
            weight_lbs=Decimal("0.12"),
            image_url="https://suprememobiles.in/cdn/shop/files/1_9ecff0cb-ba43-4945-b7ec-fc04bd2ab716.png?v=1726040725",
        ),
        Product(
            name="Amazon Kindle Paperwhite",
            sku="AMZN-KINDLE-PW16",
            description="6.8-inch glare-free display, adjustable warm light, up to 10 weeks of battery life, and 20% faster page turns.",
            category="Electronics",
            current_price=Decimal("149.99"),
            currency="USD",
            protection_days=14,
            channel3_product_id=None,
            last_market_price=None,
            weight_lbs=Decimal("0.45"),
            image_url="https://multimedia.bbycastatic.ca/multimedia/products/1500x1500/189/18909/18909672.jpeg",
        ),
    ]
    db.add_all(products)
    db.flush()

    add_action(db, "LIVE_CATALOG_SEEDED", details={"products": len(products), "sample_orders": 0})


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


@app.post("/api/v1/demo/run")
def start_sandbox_demo(request: Request):
    """Launch the real buyer-to-refund walkthrough from its dedicated local URL."""
    global sandbox_demo_process
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(403, "The demo launcher is available only on this machine.")
    if settings.is_production or settings.paypal_env.lower() != "sandbox":
        raise HTTPException(503, "The automated purchase walkthrough is restricted to PayPal Sandbox development.")
    if not settings.paypal_ready or not settings.paypal_sandbox_buyer_email or not settings.paypal_sandbox_buyer_password or not settings.channel3_api_key:
        raise HTTPException(503, "Complete the PayPal Sandbox buyer, PayPal API, and Channel3 setup before launching the demo.")
    if sandbox_demo_process and sandbox_demo_process.poll() is None:
        return {"started": False, "running": True, "message": "The full Sandbox walkthrough is already running."}
    root = Path(__file__).resolve().parents[2]
    log_path = root / "logs" / "sandbox-demo-runner.log"
    log_path.parent.mkdir(exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    sandbox_demo_process = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "sandbox_demo.py"), "--slow-mo", "20"],
        cwd=root, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True,
    )
    return {"started": True, "running": True, "message": "The full Sandbox walkthrough is starting in a new browser window.", "log": "logs/sandbox-demo-runner.log"}


@app.get("/api/v1/demo/run")
def sandbox_demo_status(request: Request):
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(403, "The demo status is available only on this machine.")
    process = sandbox_demo_process
    running = bool(process and process.poll() is None)
    report_path = Path(__file__).resolve().parents[2] / "demo-video" / "out" / "latest_run.json"
    report = None
    if report_path.exists() and not running:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            report = {key: payload.get(key) for key in ("environment", "timeline", "captured_amount", "live_price_check", "claim_id", "recommended_refund", "refund_status", "run_error", "created_at")}
        except (OSError, json.JSONDecodeError):
            pass
    return {"running": running, "exit_code": process.poll() if process else None, "report": report, "log": "logs/sandbox-demo-runner.log"}


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


@app.get("/api/v1/store/products")
def list_store_products(db: Db):
    """Only sell items with a verified Channel3 product link in the public storefront."""
    return [product_dict(item) for item in db.scalars(
        select(Product).where(Product.active.is_(True), Product.channel3_product_id.is_not(None)).order_by(Product.created_at)
    ).all()]


@app.post("/api/v1/products", status_code=201)
async def create_product(body: ProductInput, db: Db, _: Merchant):
    product = Product(**body.model_dump())
    if body.channel3_product_id:
        try:
            live = await channel3.current_offer(body.channel3_product_id, body.currency)
        except Channel3Error as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        if not channel3.matches_product(body.name, body.sku, live.get("title", "")):
            raise HTTPException(409, "The selected Channel3 listing no longer matches this product. Search again and choose the exact listing.")
        product.last_market_price = Decimal(str(live["best_offer"]["price"]))
        product.competitor_name = live["best_offer"]["merchant"]
        product.competitor_url = live["best_offer"].get("url")
        # Keep the merchant's curated product image when Channel3 has no image.
        image_url = live.get("image_url")
        if isinstance(image_url, str) and image_url.startswith("https://"):
            product.image_url = image_url
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "That SKU already exists.") from exc
    if product.channel3_product_id and not product.channel3_subscription_id:
        try:
            product.channel3_subscription_id = await channel3.subscribe(product.channel3_product_id, product.merchant_domain)
        except Channel3Error as exc:
            log.warning("Channel3 subscription setup failed for imported product %s: %s", product.id, exc)
    add_action(db, "PRODUCT_CREATED", "product", product.id, {"sku": product.sku, "channel3_linked": bool(product.channel3_product_id)})
    db.commit()
    return product_dict(product)


@app.get("/api/v1/products/{product_id}")
def get_product(product_id: str, db: Db):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    return product_dict(product)


def record_price_drop(db: Session, product: Product, new_price: Decimal, source: str) -> PriceDrop | None:
    if source in {"merchant", "customer_claim", "customer_claim_live", "demo_fixture"}:
        old_price = as_decimal(product.current_price)
    else:
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
    if str(observation.get("image_url") or "").startswith("https://"):
        product.image_url = observation["image_url"]
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
        try:
            exp_res = await explain_decision(
                product.category,
                float(drop.drop_percentage),
                days_since,
                prior_probability,
                float(gross_savings_if_returned),
                product_name=product.name,
                purchase_price=float(purchase_value),
                refund_amount=float(refund_amount),
                return_cost=float(return_cost),
            )
        except TypeError:
            exp_res = await explain_decision(
                product.category,
                float(drop.drop_percentage),
                days_since,
                prior_probability,
                float(gross_savings_if_returned),
            )

        if len(exp_res) == 4:
            probability, model_reason, provider, report = exp_res
        else:
            probability, model_reason, provider = exp_res
            report = None

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

        if report and isinstance(report, dict):
            report["reasoning"] = reason
            report["recommended_action"] = "APPROVE_PARTIAL_REFUND" if recommend else "POLICY_SKIP"
            report_payload = json.dumps(report)
        else:
            report_payload = f"{reason} [scoring: {provider}]"

        decision = Decision(price_drop_id=drop.id, capture_id=order.capture.id, order_id=order.id,
                            decision="REFUND" if recommend else "SKIP", refund_amount=refund_amount if recommend else Decimal("0.00"),
                            reasoning=report_payload, return_probability=probability,
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
    elif existing.status in {"FAILED", "CANCELLED"}:
        row.status = "REFUND_FAILED"
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


@app.get("/api/v1/channel3/search")
async def search_channel3_products(query: str = "", limit: int = 6):
    if not query.strip():
        return []
    try:
        return await channel3.search_products(query.strip(), limit=limit)
    except Channel3Error as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@app.get("/api/v1/orders/lookup/{lookup_key}")
def lookup_order(lookup_key: str, db: Db):
    key = lookup_key.strip()
    order = db.scalar(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).where((Order.id == key) | (Order.paypal_order_id == key)))
    if not order:
        raise HTTPException(404, f"Order '{lookup_key}' was not found. Please verify your Order ID.")
    data = order_dict(order)
    decision = db.scalar(select(Decision).options(joinedload(Decision.price_drop).joinedload(PriceDrop.product), joinedload(Decision.order), joinedload(Decision.capture)).where(Decision.order_id == order.id))
    if decision:
        claim = decision_dict(decision)
        refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
        claim["refund_status"] = refund.status if refund else None
        claim["paypal_refund_id"] = refund.paypal_refund_id if refund else None
        data["claim"] = claim
    else:
        data["claim"] = None
    return data


@app.post("/api/v1/claims/check-price")
async def check_price_for_claim(body: CheckPriceInput, db: Db):
    product = None
    paid_price = None
    currency = "USD"
    order = None

    if body.order_id:
        order = db.scalar(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).where((Order.id == body.order_id) | (Order.paypal_order_id == body.order_id)))
        if not order:
            raise HTTPException(404, "Order not found.")
        if order.source != "paypal" or not order.capture or not order.capture.paypal_capture_id:
            raise HTTPException(409, "Live price protection requires a completed PayPal Sandbox capture.")
        if order.items:
            product_id = body.product_id or order.items[0].product_id
            product = db.get(Product, product_id) if product_id else None
            matching_item = next((it for it in order.items if it.product_id == product_id or it.sku == (product.sku if product else "")), order.items[0])
            paid_price = float(matching_item.unit_price)
            currency = order.currency

    elif body.product_id:
        product = db.get(Product, body.product_id)
        if product:
            paid_price = float(product.current_price)
            currency = product.currency

    if not product:
        raise HTTPException(404, "Product could not be identified for price check.")

    evidence_source = "channel3_live"
    try:
        comparison = await channel3.search_and_compare(product.name, product.sku, paid_price or float(product.current_price), currency)
    except Channel3Error as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    if not comparison.get("matched"):
        return {
            "matched": False,
            "message": comparison.get("message", "Channel3 could not find an exact match."),
            "product_name": product.name,
            "paid_price": paid_price,
            "evidence_source": evidence_source,
        }

    best = comparison["best_offer"]
    best_price = float(best["price"])
    drop = round((paid_price or float(product.current_price)) - best_price, 2)
    has_drop = drop > 0

    product.last_market_price = Decimal(str(best_price))
    product.competitor_name = best.get("merchant")
    product.competitor_url = best.get("url")
    price_drop = None
    if has_drop:
        # Each customer check is new evidence. Reusing the shared 12-hour
        # dedupe row made a fresh Channel3 response appear expired at claim time.
        live_price = as_decimal(best_price)
        reference_price = as_decimal(paid_price or product.current_price)
        difference = reference_price - live_price
        percent = (difference / reference_price * Decimal("100")) if reference_price else Decimal("0")
        price_drop = PriceDrop(
            product_id=product.id, old_price=reference_price, new_price=live_price,
            drop_amount=difference, drop_percentage=percent.quantize(Decimal("0.001")),
            source="customer_claim_live",
        )
        db.add(price_drop)
        db.flush()
    db.commit()

    return {
        "matched": True,
        "product_id": product.id,
        "product_name": product.name,
        "sku": product.sku,
        "paid_price": paid_price,
        "currency": currency,
        "best_offer": best,
        "all_offers": comparison.get("all_offers", []),
        "competitor_name": best.get("merchant", "Authorized Retailer"),
        "competitor_price": best_price,
        "drop_amount": max(0.0, drop),
        "drop_percentage": round((drop / (paid_price or 1.0)) * 100, 1) if has_drop else 0.0,
        "price_drop_detected": has_drop,
        "price_drop_id": price_drop.id if price_drop else None,
        "protection_active": True if not order or (order.captured_at and (now_utc() - order.captured_at).days <= product.protection_days) else False,
        "evidence_source": evidence_source,
    }


@app.post("/api/v1/claims/submit")
async def submit_customer_claim(body: ClaimSubmitInput, db: Db):
    order = db.scalar(select(Order).options(joinedload(Order.items), joinedload(Order.capture)).where((Order.id == body.order_id) | (Order.paypal_order_id == body.order_id)))
    if not order:
        raise HTTPException(404, "Order not found.")
    if order.source != "paypal" or not order.capture or not order.capture.paypal_capture_id:
        raise HTTPException(400, "This order does not have a completed capture.")

    target_item = None
    if body.product_id:
        target_item = next((it for it in order.items if it.product_id == body.product_id), None)
    if not target_item and order.items:
        target_item = order.items[0]
    if not target_item:
        raise HTTPException(400, "Order has no items.")

    product = db.get(Product, target_item.product_id) if target_item.product_id else db.scalar(select(Product).where(Product.sku == target_item.sku))
    if not product:
        raise HTTPException(404, "Product associated with this order item was not found.")

    existing_decision = db.scalar(select(Decision).options(joinedload(Decision.price_drop).joinedload(PriceDrop.product), joinedload(Decision.order), joinedload(Decision.capture)).where(Decision.order_id == order.id))
    if existing_decision and existing_decision.status in {"PENDING_REVIEW", "APPROVED", "REFUNDED", "REFUND_PENDING"}:
        return decision_dict(existing_decision)

    purchase_price = float(target_item.unit_price)
    currency = order.currency
    days_since = (now_utc() - (order.captured_at or order.created_at)).days
    within_window = days_since <= product.protection_days
    if not within_window:
        raise HTTPException(409, "This purchase is outside its 14-day DropBack price-protection window.")

    price_drop = db.get(PriceDrop, body.price_drop_id) if body.price_drop_id else None
    if body.price_drop_id:
        if not price_drop or price_drop.product_id != product.id or price_drop.source not in {"customer_claim_live", "channel3"}:
            raise HTTPException(409, "The checked price evidence is no longer available. Run the price check again.")
        if price_drop.detected_at < now_utc() - timedelta(minutes=15):
            raise HTTPException(409, "The price check expired. Run the live price check again before submitting.")
        comp_price = float(price_drop.new_price)
        comp_merchant = product.competitor_name or "Authorized Retailer"
        drop_val = round(purchase_price - comp_price, 2)
        evidence_source = "channel3_live"
        if drop_val <= 0:
            raise HTTPException(409, "The checked offer is no longer below the purchase price.")
    else:
        evidence_source = "channel3_live"
        try:
            comparison = await channel3.search_and_compare(product.name, product.sku, purchase_price, currency)
        except Channel3Error as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

        if comparison.get("matched") and comparison.get("lower_than_current"):
            comp_price = float(comparison["best_offer"]["price"])
            comp_merchant = comparison["best_offer"]["merchant"]
            drop_val = round(purchase_price - comp_price, 2)
        else:
            raise HTTPException(409, "Channel3 did not find a lower in-stock offer for this exact product.")

    drop_pct = round((drop_val / purchase_price) * 100, 2)

    drop = price_drop or record_price_drop(
        db,
        product,
        Decimal(str(comp_price)),
        "customer_claim_live",
    )
    if not drop:
        drop = db.scalar(select(PriceDrop).where(PriceDrop.product_id == product.id).order_by(PriceDrop.detected_at.desc()))
    if not drop:
        drop = PriceDrop(
            product_id=product.id,
            old_price=as_decimal(purchase_price),
            new_price=Decimal(str(comp_price)),
            drop_amount=Decimal(str(drop_val)),
            drop_percentage=Decimal(str(drop_pct)),
            source="customer_claim",
        )
        db.add(drop)
        db.flush()
    drop.processed = True
    db.flush()

    settings_row = get_settings_row(db)
    weight = float(product.weight_lbs or 2.0)
    
    reverse_shipping = round(float(settings_row.return_shipping_cost) + (weight * 0.75), 2)
    restocking_cost = round(purchase_price * (float(settings_row.restocking_fee_percentage) / 100.0), 2)
    open_box_loss = round(purchase_price * (float(settings_row.open_box_discount_percentage) / 100.0), 2)
    total_return_cost = round(reverse_shipping + restocking_cost + open_box_loss, 2)

    proposed_refund = min(Decimal(str(drop_val)), Decimal(str(purchase_price)), settings_row.max_refund_per_order)
    gross_savings = round(total_return_cost - float(proposed_refund), 2)

    exp_res = await explain_decision(
        category=product.category,
        drop_percentage=drop_pct,
        days_since_purchase=days_since,
        probability=0.84,
        savings=gross_savings,
        product_name=product.name,
        purchase_price=purchase_price,
        refund_amount=float(proposed_refund),
        return_cost=total_return_cost,
        buyer_name=order.buyer_name or "Buyer",
        competitor_name=comp_merchant,
        customer_notes=body.customer_notes,
    )
    probability, model_reason, provider, report = exp_res
    if isinstance(report, dict):
        report["evidence_source"] = evidence_source
        breakdown = report.get("financial_breakdown") if isinstance(report.get("financial_breakdown"), dict) else {}
        breakdown.update({
            "purchase_price": purchase_price,
            "days_since_purchase": days_since,
            "proposed_refund": money(proposed_refund),
            "estimated_return_cost": total_return_cost,
            "reverse_shipping": reverse_shipping,
            "restocking_cost": restocking_cost,
            "open_box_loss": open_box_loss,
            "net_savings": max(0.0, gross_savings),
        })
        report["financial_breakdown"] = breakdown
    drafted_msg = report.get("drafted_customer_message") if isinstance(report, dict) else generate_customer_message(order.buyer_name, product.name, float(proposed_refund), comp_merchant)
    if not isinstance(report, dict):
        report = {}
    report["evidence_source"] = evidence_source
    report["channel3_offer"] = {
        "price": comp_price,
        "merchant": comp_merchant,
        "url": product.competitor_url,
        "observed_at": now_utc().isoformat(),
    }

    decision = Decision(
        price_drop_id=drop.id,
        capture_id=order.capture.id,
        order_id=order.id,
        decision="REFUND",
        refund_amount=proposed_refund,
        reasoning=json.dumps(report) if report else model_reason,
        return_probability=probability,
        estimated_return_cost=Decimal(str(total_return_cost)),
        estimated_savings=Decimal(str(max(0.0, gross_savings))),
        within_window=within_window,
        budget_available=True,
        customer_claim=True,
        customer_notes=body.customer_notes,
        ai_drafted_message=drafted_msg,
        competitor_name=comp_merchant,
        competitor_price=Decimal(str(comp_price)),
        status="PENDING_REVIEW",
    )
    db.add(decision)
    add_action(db, "CUSTOMER_CLAIM_SUBMITTED", "order", order.id, {
        "drop_amount": drop_val, "competitor": comp_merchant, "claim_notes": body.customer_notes
    })
    db.commit()
    db.refresh(decision)
    decision.order = order
    decision.capture = order.capture
    decision.price_drop = drop
    return decision_dict(decision)


@app.get("/api/v1/claims/{decision_id}")
def get_claim_status(decision_id: str, db: Db):
    decision = db.scalar(select(Decision).options(joinedload(Decision.order).joinedload(Order.items), joinedload(Decision.order).joinedload(Order.capture), joinedload(Decision.capture), joinedload(Decision.price_drop).joinedload(PriceDrop.product)).where(Decision.id == decision_id))
    if not decision:
        raise HTTPException(404, "Claim not found.")
    data = decision_dict(decision)
    refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
    data["refund"] = {
        "id": refund.id,
        "paypal_refund_id": refund.paypal_refund_id,
        "amount": money(refund.amount),
        "status": refund.status,
        "completed_at": refund.completed_at.isoformat() if refund.completed_at else None,
    } if refund else None
    return data


@app.post("/api/v1/claims/{decision_id}/resolve")
async def resolve_claim(decision_id: str, body: ClaimResolveInput, db: Db, _: Merchant):
    decision = db.scalar(select(Decision).options(joinedload(Decision.order).joinedload(Order.capture), joinedload(Decision.order).joinedload(Order.items), joinedload(Decision.capture), joinedload(Decision.price_drop).joinedload(PriceDrop.product)).where(Decision.id == decision_id))
    if not decision:
        raise HTTPException(404, "Claim not found.")
    
    if body.action == "reject":
        if decision.status not in {"PENDING_REVIEW", "APPROVED", "REFUND_FAILED"}:
            raise HTTPException(409, "This claim can no longer be rejected.")
        decision.status = "REJECTED"
        decision.reviewed_at = now_utc()
        decision.merchant_message = body.custom_message or "Your claim was reviewed and could not be approved under current return policies."
        add_action(db, "CLAIM_REJECTED", "decision", decision.id, {"note": decision.merchant_message})
        db.commit()
        return decision_dict(decision)

    if decision.status in {"REFUNDED", "REFUND_PENDING"}:
        refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
        result = decision_dict(decision)
        result["refund_status"] = refund.status if refund else None
        result["paypal_refund_id"] = refund.paypal_refund_id if refund else None
        return result
    if decision.status not in {"PENDING_REVIEW", "APPROVED", "REFUND_FAILED"}:
        raise HTTPException(409, "This claim is no longer awaiting a settlement decision.")
    if body.refund_amount:
        if as_decimal(body.refund_amount) > as_decimal(decision.refund_amount):
            raise HTTPException(422, "The refund cannot exceed the verified price difference in this claim.")
        decision.refund_amount = as_decimal(body.refund_amount)
    if body.custom_message:
        decision.merchant_message = body.custom_message
    else:
        decision.merchant_message = decision.ai_drafted_message
    
    executed_refund = None
    if decision.order.source == "sample":
        decision.status = "APPROVED"
        decision.reviewed_at = now_utc()
        db.commit()
        demo_refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
        if not demo_refund:
            demo_refund = Refund(
                decision_id=decision.id,
                capture_id=decision.capture_id,
                amount=as_decimal(decision.refund_amount),
                currency=decision.order.currency,
                status="DEMO_CREDITED",
                note_to_payer="Local demo ledger only; no PayPal funds were moved.",
                idempotency_key=f"demo-refund-{decision.id}",
                completed_at=now_utc(),
            )
            db.add(demo_refund)
        add_action(db, "DEMO_SETTLEMENT_RECORDED", "decision", decision.id, {"amount": money(decision.refund_amount), "external_payment": False})
        db.commit()
    elif decision.capture and decision.capture.paypal_capture_id and decision.order.source == "paypal":
        # Keep a live claim in review until the PayPal refund succeeds or is explicitly
        # reported as pending. Never display an approval when the external refund failed.
        decision.status = "REFUND_PENDING"
        decision.reviewed_at = now_utc()
        db.commit()
        try:
            executed_refund = await execute_refund(decision.id, db, _)
        except HTTPException as exc:
            refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
            if refund and refund.status == "FAILED":
                decision.status = "REFUND_FAILED"
                db.commit()
            log.warning("Could not execute live refund for claim %s: %s", decision.id, exc.detail)
            raise
    else:
        raise HTTPException(409, "This claim is not attached to a refundable PayPal capture.")

    add_action(db, "CLAIM_SETTLEMENT_RESOLVED", "decision", decision.id, {
        "refund_amount": money(decision.refund_amount),
        "live_refund_status": executed_refund.get("status") if executed_refund else "DEMO_CREDITED",
    })
    db.commit()
    db.refresh(decision)
    result = decision_dict(decision)
    refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
    result["refund_status"] = refund.status if refund else None
    result["paypal_refund_id"] = refund.paypal_refund_id if refund else None
    return result


@app.get("/api/v1/apimatic/status")
def apimatic_status():
    return apimatic_mcp.get_plugin_manifest()


@app.get("/api/v1/apimatic/sandbox-orders")
def apimatic_sandbox_orders(db: Db, _: Merchant):
    rows = db.scalars(
        select(Order)
        .options(joinedload(Order.capture), joinedload(Order.items))
        .where(Order.source == "paypal", Order.paypal_order_id.is_not(None))
        .order_by(Order.created_at.desc())
        .limit(10)
    ).unique().all()
    return [
        {
            "order_id": row.paypal_order_id,
            "capture_id": row.capture.paypal_capture_id if row.capture else None,
            "buyer_name": row.buyer_name,
            "item_name": row.items[0].name if row.items else "PayPal order",
            "amount": money(row.total_amount),
            "currency": row.currency,
            "status": row.status,
        }
        for row in rows
    ]


@app.post("/api/v1/apimatic/mcp/invoke")
async def apimatic_invoke(body: APIMaticInvokeInput, db: Db, _: Merchant):
    if body.tool != "paypal_issue_capture_refund":
        return await apimatic_mcp.invoke_mcp_tool(body.tool, body.arguments)
    if settings.paypal_env.lower() != "sandbox" or "api-m.sandbox.paypal.com" not in settings.paypal_base_url.lower():
        raise HTTPException(409, "The APIMatic refund runner is restricted to PayPal Sandbox.")

    capture_id = str(body.arguments.get("capture_id", "")).strip()
    try:
        submitted_amount = Decimal(str(body.arguments.get("amount")))
        requested = as_decimal(submitted_amount)
    except Exception as exc:
        raise HTTPException(422, "Enter a valid refund amount.") from exc
    if submitted_amount != requested or requested <= 0:
        raise HTTPException(422, "Refund amount must be a positive value with no more than two decimal places.")
    capture = db.scalar(select(Capture).options(joinedload(Capture.order)).where(Capture.paypal_capture_id == capture_id))
    if not capture or capture.order.source != "paypal" or not capture.paypal_capture_id:
        raise HTTPException(404, "Choose a captured PayPal Sandbox payment from this merchant account.")
    requested_currency = str(body.arguments.get("currency", "USD")).upper()
    if requested_currency != capture.currency.upper():
        raise HTTPException(409, "Refund currency must match the captured PayPal payment.")
    active_claim = db.scalar(select(Decision.id).where(
        Decision.capture_id == capture.id,
        Decision.decision == "REFUND",
        Decision.status.in_({"PENDING_REVIEW", "APPROVED", "REFUND_PENDING"}),
    ))
    if active_claim:
        raise HTTPException(409, "This capture has a DropBack claim. Resolve the approved claim from the merchant review flow.")

    request_digest = hashlib.sha256(f"{capture_id}:{requested_currency}:{requested:.2f}".encode()).hexdigest()[:32]
    request_key = f"db-{request_digest}"
    prior_action = db.scalar(select(AgentAction).where(
        AgentAction.action_type == "APIMATIC_REFUND_REQUESTED", AgentAction.entity_id == request_key,
    ))
    prior_details = json.loads(prior_action.details or "{}") if prior_action else {}
    if prior_details.get("refund_status") == "COMPLETED" and prior_details.get("tool_result"):
        return prior_details["tool_result"]

    pending_dropback = as_decimal(db.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(
        Refund.capture_id == capture.id, Refund.status == "PENDING",
    )))
    apimatic_actions = db.scalars(select(AgentAction).where(
        AgentAction.action_type == "APIMATIC_REFUND_REQUESTED",
        AgentAction.entity_id != request_key,
    )).all()
    pending_apimatic = Decimal("0.00")
    today_apimatic = Decimal("0.00")
    today = now_utc().date()
    for action in apimatic_actions:
        details = json.loads(action.details or "{}")
        if details.get("capture_id") == capture_id and details.get("refund_status") in {"PENDING", "REQUESTED"}:
            pending_apimatic += as_decimal(details.get("amount"))
            if action.created_at and action.created_at.date() == today:
                today_apimatic += as_decimal(details.get("amount"))

    settings_row = get_settings_row(db)
    remaining = max(Decimal("0.00"), as_decimal(capture.amount) - as_decimal(capture.refunded_amount) - pending_dropback - pending_apimatic)
    already_spent_today = as_decimal(db.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(
        Refund.status.in_({"PENDING", "COMPLETED"}), func.date(Refund.created_at) == today,
    )))
    if requested > remaining or requested > as_decimal(settings_row.max_refund_per_order):
        raise HTTPException(409, "Refund amount exceeds the remaining captured balance or merchant per-order cap.")
    if already_spent_today + today_apimatic + requested > as_decimal(settings_row.daily_refund_budget):
        raise HTTPException(409, "Refund amount exceeds the remaining merchant daily refund budget.")

    details = {
        "capture_id": capture_id,
        "amount": money(requested),
        "currency": capture.currency,
        "refund_status": "REQUESTED",
    }
    if prior_action:
        prior_action.details = json.dumps(details)
    else:
        prior_action = AgentAction(action_type="APIMATIC_REFUND_REQUESTED", entity_type="capture", entity_id=request_key, details=json.dumps(details))
        db.add(prior_action)
    db.commit()

    result = await apimatic_mcp.invoke_mcp_tool(body.tool, {
        **body.arguments,
        "capture_id": capture_id,
        "amount": f"{requested:.2f}",
        "currency": requested_currency,
    })
    refund_status = result.get("refund_status")
    details["refund_status"] = refund_status or ("PENDING" if result.get("status") == "EXCEPTION" else "FAILED")
    details["tool_result"] = result
    if result.get("status") == "SUCCESS" and refund_status == "COMPLETED":
        capture.refunded_amount = as_decimal(capture.refunded_amount) + requested
        capture.status = "REFUNDED" if as_decimal(capture.refunded_amount) >= as_decimal(capture.amount) else "COMPLETED"
        add_action(db, "APIMATIC_REFUND_ISSUED", "capture", capture_id, {
            "amount": money(requested), "currency": capture.currency, "paypal_refund_id": result.get("refund_id"),
        })
    prior_action.details = json.dumps(details)
    db.commit()
    return result


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
