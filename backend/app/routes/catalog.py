"""Merchant catalog, Channel3 matching, and price-drop evaluation."""

import logging
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.deps import Db
from app.models.entities import Decision, Order, PriceDrop, Product
from app.schemas import LookupInput, PriceUpdate, ProductInput
from app.security import Merchant
from app.serializers import add_action, as_decimal, decision_dict, price_drop_dict, product_dict, store_product_dict
from app.services import claims
from app.services.channel3 import Channel3Error, channel3

log = logging.getLogger("dropback.catalog")
router = APIRouter(prefix="/api/v1")


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


async def ensure_subscription(product: Product) -> None:
    """Watch a linked product two ways: offer-change webhooks (product subscription) and price history (price tracking)."""
    if product.channel3_product_id and not product.channel3_subscription_id:
        try:
            product.channel3_subscription_id = await channel3.subscribe(product.channel3_product_id, product.merchant_domain)
        except Channel3Error as exc:
            log.warning("Channel3 subscription setup failed for product %s: %s", product.id, exc)
        try:
            await channel3.start_tracking(product.channel3_product_id)
        except Channel3Error as exc:
            log.warning("Channel3 price tracking could not start for product %s: %s", product.id, exc)


@router.get("/store/info")
def store_info(db: Db):
    """Public store facts for the buyer portal: the merchant's name and protection window."""
    row = claims.get_settings_row(db)
    return {"merchant_name": row.merchant_name, "protection_window_days": row.price_protection_window_days}


@router.get("/store/products")
def list_store_products(db: Db):
    """Only sell items with a verified Channel3 product link in the public storefront."""
    rows = db.scalars(select(Product).where(Product.active.is_(True), Product.channel3_product_id.is_not(None)).order_by(Product.created_at)).all()
    return [store_product_dict(item) for item in rows]


@router.get("/products")
def list_products(db: Db, _: Merchant):
    return [product_dict(item) for item in db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.created_at)).all()]


@router.get("/products/{product_id}")
def get_product(product_id: str, db: Db, _: Merchant):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    return product_dict(product)


@router.post("/products", status_code=201)
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
        image_url = live.get("image_url")
        if isinstance(image_url, str) and image_url.startswith("https://"):
            product.image_url = image_url
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "That SKU already exists.") from exc
    await ensure_subscription(product)
    add_action(db, "PRODUCT_CREATED", "product", product.id, {"sku": product.sku, "channel3_linked": bool(product.channel3_product_id)})
    db.commit()
    return product_dict(product)


@router.patch("/products/{product_id}/price")
def update_price(product_id: str, body: PriceUpdate, db: Db, _: Merchant):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    old_price = as_decimal(product.current_price)
    new_price = as_decimal(body.new_price)
    drop = claims.record_price_drop(db, product, old_price, new_price, "merchant") if new_price < old_price else None
    product.current_price = new_price
    db.commit()
    return {"product": product_dict(product), "price_drop": price_drop_dict(drop) if drop else None}


@router.post("/products/{product_id}/channel3-check")
async def check_channel3(product_id: str, db: Db, _: Merchant):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    try:
        observation = await channel3.search_and_compare(product.name, product.sku, float(product.current_price), product.currency)
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
    await ensure_subscription(product)
    best = observation["best_offer"]
    best_price = as_decimal(best["price"])
    reference = as_decimal(product.last_market_price if product.last_market_price is not None else product.current_price)
    drop = claims.record_price_drop(db, product, reference, best_price, "channel3", best.get("merchant"), best.get("url")) if best_price < reference else None
    product.last_market_price = best_price
    product.competitor_name = best.get("merchant")
    product.competitor_url = best.get("url")
    add_action(db, "CHANNEL3_PRICE_CHECK", "product", product.id, {"offer": best, "match_confidence": observation["match_confidence"], "subscription_created": bool(product.channel3_subscription_id)})
    db.commit()
    observation["price_drop"] = price_drop_dict(drop) if drop else None
    observation["subscription_active"] = bool(product.channel3_subscription_id)
    observation["subscription_note"] = "Channel3 can send ongoing price-change events after a webhook URL is registered in its dashboard." if product.channel3_subscription_id else None
    return observation


@router.get("/channel3/search")
async def search_channel3_products(_: Merchant, query: str = "", limit: int = 6):
    if not query.strip():
        return []
    try:
        return await channel3.search_products(query.strip()[:200], limit=max(1, min(limit, 12)))
    except Channel3Error as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/channel3/lookup")
async def lookup_channel3_product(body: LookupInput, _: Merchant):
    """Paste a product page URL (your store or any retailer); Channel3 resolves the exact product."""
    try:
        return await channel3.lookup(body.url.strip())
    except Channel3Error as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/products/{product_id}/market")
async def product_market(product_id: str, db: Db, _: Merchant):
    """Channel3 price history and the current best retailer for a linked product."""
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found.")
    if not product.channel3_product_id:
        raise HTTPException(409, "Link this product to Channel3 first.")
    return await channel3.market_context(product.channel3_product_id, product.competitor_name)


@router.get("/price-drops")
def list_price_drops(db: Db, _: Merchant):
    drops = db.scalars(select(PriceDrop).options(joinedload(PriceDrop.product)).order_by(PriceDrop.detected_at.desc()).limit(100)).all()
    return [price_drop_dict(drop) for drop in drops]


def _decision_query():
    return select(Decision).options(
        joinedload(Decision.order).joinedload(Order.items), joinedload(Decision.order).joinedload(Order.capture),
        joinedload(Decision.capture), joinedload(Decision.price_drop).joinedload(PriceDrop.product))


@router.post("/price-drops/{drop_id}/process")
async def process_price_drop(drop_id: str, db: Db, _: Merchant):
    """Evaluate every captured order containing the product against this price drop."""
    drop = db.scalar(select(PriceDrop).options(joinedload(PriceDrop.product)).where(PriceDrop.id == drop_id))
    if not drop:
        raise HTTPException(404, "Price drop not found.")
    if drop.processed:
        return [decision_dict(row) for row in db.scalars(_decision_query().where(Decision.price_drop_id == drop.id)).unique().all()]
    settings_row = claims.get_settings_row(db)
    product = drop.product
    competitor = drop.offer_merchant or product.competitor_name or "authorized retailers"
    budget_left = claims.daily_budget_left(db, settings_row)
    candidates = db.scalars(select(Order).options(joinedload(Order.items), joinedload(Order.capture))
                            .where(Order.status == "COMPLETED", Order.captured_at.is_not(None))).unique().all()
    created: list[str] = []
    market = await channel3.market_context(product.channel3_product_id, drop.offer_merchant) if product.channel3_product_id else None
    for order in candidates:
        if db.scalar(select(Decision.id).where(Decision.price_drop_id == drop.id, Decision.order_id == order.id)):
            continue
        assessment = claims.assess_order(db, order, product, as_decimal(drop.new_price), settings_row, budget_left)
        if not assessment:
            continue
        await claims.score(assessment, product, order, competitor, market=market)
        decision = claims.build_decision(assessment, order, drop, competitor, customer_claim=False,
                                         evidence={"price": float(drop.new_price), "merchant": competitor, "url": drop.offer_url, "source": drop.source},
                                         market=market)
        db.add(decision)
        db.flush()
        created.append(decision.id)
        if decision.decision == "REFUND":
            budget_left = max(Decimal("0"), budget_left - as_decimal(decision.refund_amount))
    drop.processed = True
    add_action(db, "PRICE_DROP_PROCESSED", "price_drop", drop.id, {"decisions_created": len(created)})
    db.commit()
    db.expire_all()
    return [decision_dict(row) for row in db.scalars(_decision_query().where(Decision.id.in_(created))).unique().all()] if created else []
