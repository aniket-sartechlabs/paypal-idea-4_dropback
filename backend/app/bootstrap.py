"""Startup checks, development schema creation, and the demo catalog."""

from decimal import Decimal

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app import database
from app.config import get_settings
from app.models.entities import Product
from app.serializers import add_action
from app.services.claims import get_settings_row

# Columns added after the first release. A development database created before them
# must be recreated (delete dropback.db) or upgraded with `alembic upgrade head`.
REQUIRED_COLUMNS = {"price_drops": {"offer_merchant", "offer_url"}}

DEMO_CATALOG = [
    dict(name="Sony WH-1000XM5 Wireless Noise Canceling Headphones", sku="SONY-WH1000XM5-BLK",
         description="Industry-leading noise cancellation, crystal clear hands-free calling, and 30-hour battery life with quick charging.",
         price="398.00", weight="0.55", image_url="https://www.sony.com/is/image/gwtprod/6145c1d32e6ac8e63a46c912dc33c5bb?fmt=png-alpha&wid=900"),
    dict(name="Apple AirPods Pro", sku="APPLE-AIRPODS-PRO2",
         description="Active Noise Cancellation, Adaptive Audio, Transparency mode, and USB-C MagSafe charging case.",
         price="249.00", weight="0.12", image_url="https://suprememobiles.in/cdn/shop/files/1_9ecff0cb-ba43-4945-b7ec-fc04bd2ab716.png?v=1726040725"),
    dict(name="Amazon Kindle Paperwhite", sku="AMZN-KINDLE-PW16",
         description="6.8-inch glare-free display, adjustable warm light, up to 10 weeks of battery life, and 20% faster page turns.",
         price="149.99", weight="0.45", image_url="https://multimedia.bbycastatic.ca/multimedia/products/1500x1500/189/18909/18909672.jpeg"),
]


def check_production_settings() -> None:
    settings = get_settings()
    if not settings.is_production:
        return
    problems = []
    if not settings.secret_key or len(settings.secret_key) < 32:
        problems.append("SECRET_KEY of at least 32 characters")
    if not settings.paypal_ready:
        problems.append("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET")
    if not settings.channel3_api_key:
        problems.append("CHANNEL3_API_KEY")
    if not settings.channel3_webhook_secret:
        problems.append("CHANNEL3_WEBHOOK_SECRET")
    if not settings.paypal_webhook_id:
        problems.append("PAYPAL_WEBHOOK_ID")
    if not settings.app_base_url.startswith("https://"):
        problems.append("an HTTPS APP_BASE_URL")
    if not settings.merchant_email or not settings.merchant_password:
        problems.append("MERCHANT_EMAIL and MERCHANT_PASSWORD")
    if problems:
        raise RuntimeError("Production requires " + "; ".join(problems) + ".")


def check_schema() -> None:
    inspector = inspect(database.engine)
    if not inspector.has_table("products"):
        raise RuntimeError("Database schema is missing. Run `alembic upgrade head` in backend/.")
    for table, required in REQUIRED_COLUMNS.items():
        present = {column["name"] for column in inspector.get_columns(table)}
        missing = required - present
        if missing:
            raise RuntimeError(f"Database table {table} is missing {sorted(missing)}. Run `alembic upgrade head` in backend/, "
                               "or delete the local development database (dropback.db) to recreate it.")


def seed_demo_catalog(db: Session) -> None:
    db.add_all([Product(name=row["name"], sku=row["sku"], description=row["description"], category="Electronics",
                        current_price=Decimal(row["price"]), currency="USD", protection_days=14,
                        weight_lbs=Decimal(row["weight"]), image_url=row["image_url"]) for row in DEMO_CATALOG])
    db.flush()
    add_action(db, "LIVE_CATALOG_SEEDED", details={"products": len(DEMO_CATALOG)})


def startup() -> None:
    settings = get_settings()
    check_production_settings()
    if not settings.is_production:
        database.Base.metadata.create_all(bind=database.engine)
    check_schema()
    with database.SessionLocal() as db:
        get_settings_row(db)
        if not settings.is_production and db.scalar(select(func.count(Product.id))) == 0:
            seed_demo_catalog(db)
        db.commit()
