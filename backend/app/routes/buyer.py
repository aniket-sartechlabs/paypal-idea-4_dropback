"""Buyer portal: open an order, check the live price, and request the difference.

Every endpoint here needs a buyer session that includes the order (or a merchant session).
"""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.deps import Db
from app.models.entities import Decision, Order, OrderItem, PriceDrop, Product, Refund, now_utc
from app.schemas import CheckPriceInput, ClaimSubmitInput
from app.security import rate_limited, record_hit, require_order_access
from app.serializers import add_action, as_decimal, decision_dict, order_dict
from app.services import claims
from app.services.channel3 import Channel3Error, channel3, parse_retailers, retailer_allowed

router = APIRouter(prefix="/api/v1")

EVIDENCE_TTL = timedelta(minutes=15)
PRICE_CHECKS_PER_ORDER = 10
PRICE_CHECK_WINDOW = 10 * 60


def _load_order(db, key: str) -> Order | None:
    return db.scalar(select(Order).options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.capture))
                     .where((Order.id == key) | (Order.paypal_order_id == key)))


def _captured_order(db, request: Request, key: str) -> Order:
    order = _load_order(db, key.strip())
    if not order:
        raise HTTPException(404, "Order not found.")
    require_order_access(request, order)
    if not order.capture or not order.capture.paypal_capture_id:
        raise HTTPException(409, "Price protection starts once the PayPal payment is captured.")
    return order


def _order_product(db, order: Order, product_id: str | None) -> tuple[OrderItem, Product]:
    item = next((it for it in order.items if product_id and it.product_id == product_id), None) or (order.items[0] if order.items else None)
    if not item:
        raise HTTPException(400, "Order has no items.")
    product = db.get(Product, item.product_id) if item.product_id else db.scalar(select(Product).where(Product.sku == item.sku))
    if not product:
        raise HTTPException(404, "The product on this order is no longer in the catalog.")
    return item, product


def _claim_query():
    return select(Decision).options(
        joinedload(Decision.order).joinedload(Order.items), joinedload(Decision.order).joinedload(Order.capture),
        joinedload(Decision.capture), joinedload(Decision.price_drop).joinedload(PriceDrop.product))


def _claim_with_refund(db, decision: Decision) -> dict:
    refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
    data = decision_dict(decision, refund)
    if refund is None:
        data.update(refund_status=None, paypal_refund_id=None)
    return data


@router.get("/orders/lookup/{lookup_key}")
def lookup_order(lookup_key: str, request: Request, db: Db):
    order = _load_order(db, lookup_key.strip())
    if not order:
        raise HTTPException(404, "Order not found. Check the order ID in your PayPal receipt.")
    require_order_access(request, order)
    data = order_dict(order)
    decision = db.scalar(_claim_query().where(Decision.order_id == order.id, Decision.customer_claim.is_(True)).order_by(Decision.created_at.desc()))
    data["claim"] = _claim_with_refund(db, decision) if decision else None
    if order.items:
        _, product = _order_product(db, order, order.items[0].product_id)
        window = claims.window_days_for(product, claims.get_settings_row(db))
        data["protection_window_days"] = window
        data["protection_active"] = order.captured_at is not None and claims.days_since_capture(order) <= window
    return data


@router.post("/claims/check-price")
async def check_price_for_claim(body: CheckPriceInput, request: Request, db: Db):
    order = _captured_order(db, request, body.order_id)
    bucket = f"price-check:{order.id}"
    if rate_limited(bucket, PRICE_CHECKS_PER_ORDER, PRICE_CHECK_WINDOW):
        raise HTTPException(429, "Too many price checks for this order. Try again in a few minutes.")
    record_hit(bucket)
    item, product = _order_product(db, order, body.product_id)
    paid_price = as_decimal(item.unit_price)
    try:
        comparison = await channel3.search_and_compare(product.name, product.sku, float(paid_price), order.currency,
                                                       parse_retailers(claims.get_settings_row(db).allowed_retailers))
    except Channel3Error as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not comparison.get("matched"):
        return {"matched": False, "message": comparison.get("message", "Channel3 could not find an exact match."),
                "product_name": product.name, "paid_price": float(paid_price), "evidence_source": "channel3_live"}

    best = comparison["best_offer"]
    best_price = as_decimal(best["price"])
    window = claims.window_days_for(product, claims.get_settings_row(db))
    market = await channel3.market_context(product.channel3_product_id or comparison.get("product_id"), best.get("merchant"))
    # Each buyer check is its own evidence row; it never changes the merchant's catalog data.
    drop = claims.record_price_drop(db, product, paid_price, best_price, "customer_claim_live", best.get("merchant"), best.get("url"), dedupe=False)
    db.commit()
    difference = max(as_decimal(0), paid_price - best_price)
    return {
        "matched": True, "product_id": product.id, "product_name": product.name, "sku": product.sku,
        "paid_price": float(paid_price), "currency": order.currency,
        "best_offer": best, "all_offers": comparison.get("all_offers", []),
        "competitor_name": best.get("merchant", "Authorized retailer"), "competitor_price": float(best_price),
        "drop_amount": float(difference),
        "drop_percentage": round(float(difference / paid_price * 100), 1) if paid_price else 0.0,
        "price_drop_detected": drop is not None, "price_drop_id": drop.id if drop else None,
        "protection_window_days": window,
        "protection_active": claims.days_since_capture(order) <= window,
        "evidence_source": "channel3_live",
        "market": {**market, "offers_checked": comparison.get("offer_count"),
                   "summary": claims.market_summary(market, best_price, best.get("merchant", ""))},
    }


@router.post("/claims/submit")
async def submit_customer_claim(body: ClaimSubmitInput, request: Request, db: Db):
    order = _captured_order(db, request, body.order_id)
    item, product = _order_product(db, order, body.product_id)

    existing = db.scalar(_claim_query().where(Decision.order_id == order.id, Decision.customer_claim.is_(True),
                                              Decision.status.in_({"PENDING_REVIEW", "APPROVED", "REFUND_PENDING", "REFUNDED"})))
    if existing:
        return _claim_with_refund(db, existing)

    settings_row = claims.get_settings_row(db)
    window = claims.window_days_for(product, settings_row)
    if claims.days_since_capture(order) > window:
        raise HTTPException(409, f"This purchase is outside its {window}-day price-protection window.")

    if body.price_drop_id:
        drop = db.scalar(select(PriceDrop).options(joinedload(PriceDrop.product)).where(PriceDrop.id == body.price_drop_id))
        if not drop or drop.product_id != product.id or drop.source != "customer_claim_live":
            raise HTTPException(409, "The checked price evidence is no longer available. Run the price check again.")
        if drop.detected_at < now_utc() - EVIDENCE_TTL:
            raise HTTPException(409, "The price check expired. Run the live price check again before submitting.")
        if as_decimal(drop.old_price) != as_decimal(item.unit_price):
            raise HTTPException(409, "The price evidence does not match this order. Run the price check again.")
        allowed = parse_retailers(settings_row.allowed_retailers)
        if allowed and not retailer_allowed(drop.offer_merchant or "", allowed):
            raise HTTPException(409, "This store only matches prices from: " + ", ".join(allowed) + ".")
    else:
        try:
            comparison = await channel3.search_and_compare(product.name, product.sku, float(item.unit_price), order.currency,
                                                           parse_retailers(settings_row.allowed_retailers))
        except Channel3Error as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        if not (comparison.get("matched") and comparison.get("lower_than_current")):
            raise HTTPException(409, "Channel3 did not find a lower in-stock offer for this exact product.")
        best = comparison["best_offer"]
        drop = claims.record_price_drop(db, product, as_decimal(item.unit_price), as_decimal(best["price"]), "customer_claim_live",
                                        best.get("merchant"), best.get("url"), dedupe=False)
    if drop is None or as_decimal(drop.new_price) >= as_decimal(item.unit_price):
        raise HTTPException(409, "The checked offer is no longer below the purchase price.")

    competitor = drop.offer_merchant or "Authorized retailer"
    assessment = claims.assess_order(db, order, product, as_decimal(drop.new_price), settings_row)
    if assessment is None:
        raise HTTPException(409, "This order has no captured item for that product.")
    market = await channel3.market_context(product.channel3_product_id, competitor)
    await claims.score(assessment, product, order, competitor, body.customer_notes, market)
    decision = claims.build_decision(
        assessment, order, drop, competitor, customer_claim=True, customer_notes=body.customer_notes,
        evidence={"price": float(drop.new_price), "merchant": competitor, "url": drop.offer_url, "observed_at": drop.detected_at.isoformat()},
        market=market,
    )
    drop.processed = True
    db.add(decision)
    add_action(db, "CUSTOMER_CLAIM_SUBMITTED", "order", order.id, {"drop_amount": float(assessment.price_difference), "competitor": competitor})
    db.commit()
    return _claim_with_refund(db, db.scalar(_claim_query().where(Decision.id == decision.id)))


@router.get("/claims/{decision_id}")
def get_claim_status(decision_id: str, request: Request, db: Db):
    decision = db.scalar(_claim_query().where(Decision.id == decision_id))
    if not decision:
        raise HTTPException(404, "Claim not found.")
    require_order_access(request, decision.order)
    data = _claim_with_refund(db, decision)
    refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
    data["refund"] = {"id": refund.id, "paypal_refund_id": refund.paypal_refund_id, "amount": float(refund.amount), "status": refund.status,
                      "completed_at": refund.completed_at.isoformat() if refund.completed_at else None} if refund else None
    return data
