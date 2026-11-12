"""Claim economics, refund execution, and manual refunds.

The same `assess_order` calculation backs both entry points:

* a buyer-submitted price-match claim (buyer portal), and
* a merchant-side price drop that is evaluated against every eligible order.

Refund execution enforces hard limits independently of the recommendation: the remaining
capture balance, the per-order cap, and the daily refund budget.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import Capture, Decision, MerchantSettings, Order, OrderItem, PriceDrop, Product, Refund, now_utc
from app.serializers import add_action, as_decimal, money, money_text
from app.services import agent
from app.services.paypal import PayPalError, paypal

ACTIVE_REFUND_STATUSES = ("PENDING", "COMPLETED")
SHIPPING_COST_PER_LB = Decimal("0.75")
DEFAULT_WEIGHT_LBS = Decimal("2.00")
MIN_RETURN_PROBABILITY = 0.25


def get_settings_row(db: Session) -> MerchantSettings:
    row = db.get(MerchantSettings, "default")
    if not row:
        row = MerchantSettings(id="default")
        db.add(row)
        db.flush()
    return row


def window_days_for(product: Product, settings_row: MerchantSettings) -> int:
    return min(int(product.protection_days), int(settings_row.price_protection_window_days))


def days_since_capture(order: Order) -> int:
    started = order.captured_at or order.created_at
    return max(0, (now_utc() - started).days)


# -- refund totals -------------------------------------------------------------------
def refunds_today(db: Session, exclude_id: str | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(Refund.amount), 0)).where(
        Refund.status.in_(ACTIVE_REFUND_STATUSES), func.date(Refund.created_at) == now_utc().date())
    if exclude_id:
        query = query.where(Refund.id != exclude_id)
    return as_decimal(db.scalar(query))


def refunds_for_capture(db: Session, capture_id: str, exclude_id: str | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(Refund.amount), 0)).where(
        Refund.capture_id == capture_id, Refund.status.in_(ACTIVE_REFUND_STATUSES))
    if exclude_id:
        query = query.where(Refund.id != exclude_id)
    return as_decimal(db.scalar(query))


def reserved_recommendations(db: Session) -> Decimal:
    """Refund amounts recommended and awaiting review that have no refund row yet."""
    return as_decimal(db.scalar(
        select(func.coalesce(func.sum(Decision.refund_amount), 0)).select_from(Decision)
        .outerjoin(Refund, Refund.decision_id == Decision.id)
        .where(Decision.status.in_(["PENDING_REVIEW", "APPROVED"]), Decision.decision == "REFUND", Refund.id.is_(None))
    ))


def daily_budget_left(db: Session, settings_row: MerchantSettings) -> Decimal:
    return max(Decimal("0.00"), as_decimal(settings_row.daily_refund_budget) - refunds_today(db) - reserved_recommendations(db))


# -- price drops -------------------------------------------------------------------
def record_price_drop(db: Session, product: Product, reference_price: Decimal, new_price: Decimal, source: str,
                      offer_merchant: str | None = None, offer_url: str | None = None, dedupe: bool = True) -> PriceDrop | None:
    old_price = as_decimal(reference_price)
    new_price = as_decimal(new_price)
    if new_price >= old_price:
        return None
    if dedupe:
        recent = db.scalar(select(PriceDrop).where(
            PriceDrop.product_id == product.id, PriceDrop.new_price == new_price, PriceDrop.old_price == old_price,
            PriceDrop.source == source, PriceDrop.detected_at >= now_utc() - timedelta(hours=12)))
        if recent:
            return recent
    percent = (old_price - new_price) / old_price * Decimal("100") if old_price else Decimal("0")
    drop = PriceDrop(product_id=product.id, old_price=old_price, new_price=new_price, drop_amount=old_price - new_price,
                     drop_percentage=percent.quantize(Decimal("0.001")), source=source,
                     offer_merchant=(offer_merchant or None) and offer_merchant[:120], offer_url=(offer_url or None) and offer_url[:500])
    db.add(drop)
    db.flush()
    add_action(db, "PRICE_DROP_DETECTED", "price_drop", drop.id, {"product_id": product.id, "source": source, "old": str(old_price), "new": str(new_price)})
    return drop


# -- assessment ----------------------------------------------------------------------
@dataclass
class Assessment:
    matching_items: list[OrderItem]
    quantity: int
    purchase_value: Decimal
    unit_price: Decimal
    offer_price: Decimal
    price_difference: Decimal
    refund_amount: Decimal
    reverse_shipping: Decimal
    restocking_cost: Decimal
    open_box_loss: Decimal
    lost_margin: Decimal
    days_since: int
    window_days: int
    within_window: bool
    min_drop_ok: bool
    budget_available: bool
    baseline_probability: float
    probability: float = 0.0
    provider: str = "rules"
    report: dict = field(default_factory=dict)

    @property
    def return_cost(self) -> Decimal:
        return as_decimal(self.reverse_shipping + self.restocking_cost + self.open_box_loss)

    @property
    def loss_if_returned(self) -> Decimal:
        """A return-and-rebuy costs the return handling plus the profit on the lost sale."""
        return as_decimal(self.return_cost + self.lost_margin)

    @property
    def expected_loss(self) -> Decimal:
        return as_decimal(self.loss_if_returned * Decimal(str(self.probability)))

    @property
    def drop_percentage(self) -> float:
        return float(self.price_difference / self.purchase_value * 100) if self.purchase_value else 0.0

    @property
    def expected_savings(self) -> Decimal:
        """Probability-weighted loss avoided (return handling + lost sale margin), minus the refund paid."""
        return as_decimal(self.expected_loss - self.refund_amount)

    def recommendation(self) -> tuple[bool, str | None]:
        if not self.within_window:
            return False, f"Outside the {self.window_days}-day protection window; no refund recommended."
        if self.refund_amount <= 0:
            return False, "No refundable difference remains for this order."
        if not self.min_drop_ok:
            return False, "This drop is below the merchant's minimum amount or percentage."
        if not self.budget_available:
            return False, "The daily refund budget is reserved or exhausted."
        if self.probability < MIN_RETURN_PROBABILITY:
            return False, "Return likelihood is below the merchant's decision threshold."
        if self.expected_savings <= 0:
            return False, (f"Expected loss from a return (${float(self.expected_loss):.2f}: {self.probability:.0%} of "
                           f"${float(self.loss_if_returned):.2f}) does not exceed the refund amount.")
        return True, None


def assess_order(db: Session, order: Order, product: Product, offer_price: Decimal, settings_row: MerchantSettings,
                 budget_left: Decimal | None = None) -> Assessment | None:
    """Work out what a price match would cost on `order` compared with a likely return."""
    matching = [item for item in order.items if item.product_id == product.id or item.sku == product.sku]
    if not matching or not order.capture:
        return None
    offer_price = as_decimal(offer_price)
    quantity = sum(item.quantity for item in matching)
    purchase_value = sum((as_decimal(item.unit_price) * item.quantity for item in matching), Decimal("0"))
    price_difference = sum((max(Decimal("0"), as_decimal(item.unit_price) - offer_price) * item.quantity for item in matching), Decimal("0"))
    remaining_capture = max(Decimal("0"), as_decimal(order.capture.amount) - refunds_for_capture(db, order.capture.id))
    refund_amount = as_decimal(min(price_difference, remaining_capture, as_decimal(settings_row.max_refund_per_order)))

    weight = as_decimal(product.weight_lbs) if product.weight_lbs else DEFAULT_WEIGHT_LBS
    reverse_shipping = as_decimal(as_decimal(settings_row.return_shipping_cost) + weight * quantity * SHIPPING_COST_PER_LB)
    restocking_cost = as_decimal(purchase_value * as_decimal(settings_row.restocking_fee_percentage) / 100)
    open_box_loss = as_decimal(purchase_value * as_decimal(settings_row.open_box_discount_percentage) / 100)
    lost_margin = as_decimal(purchase_value * as_decimal(settings_row.gross_margin_percentage or 0) / 100)

    days_since = days_since_capture(order)
    window_days = window_days_for(product, settings_row)
    drop_pct = float(price_difference / purchase_value * 100) if purchase_value else 0.0
    min_drop_ok = refund_amount >= as_decimal(settings_row.min_price_drop_amount) and drop_pct >= float(settings_row.min_price_drop_percentage)
    if budget_left is None:
        budget_left = daily_budget_left(db, settings_row)
    baseline, _ = agent.deterministic_score(product.category, drop_pct, days_since)
    return Assessment(
        matching_items=matching, quantity=quantity, purchase_value=purchase_value,
        unit_price=max(as_decimal(item.unit_price) for item in matching), offer_price=offer_price,
        price_difference=price_difference, refund_amount=refund_amount,
        reverse_shipping=reverse_shipping, restocking_cost=restocking_cost, open_box_loss=open_box_loss,
        lost_margin=lost_margin, days_since=days_since, window_days=window_days, within_window=days_since <= window_days,
        min_drop_ok=min_drop_ok, budget_available=refund_amount <= budget_left, baseline_probability=baseline,
    )


async def score(assessment: Assessment, product: Product, order: Order, competitor_name: str, customer_notes: str = "") -> Assessment:
    savings_if_returned = float(assessment.loss_if_returned - assessment.refund_amount)
    probability, _reason, provider, report = await agent.explain_decision(
        category=product.category,
        drop_percentage=assessment.drop_percentage,
        days_since_purchase=assessment.days_since,
        probability=assessment.baseline_probability,
        savings=savings_if_returned,
        product_name=product.name,
        purchase_price=float(assessment.purchase_value),
        refund_amount=float(assessment.refund_amount),
        return_cost=float(assessment.loss_if_returned),
        buyer_name=order.buyer_name or "Buyer",
        competitor_name=competitor_name,
        customer_notes=customer_notes,
        window_days=assessment.window_days,
    )
    assessment.probability = float(probability)
    assessment.provider = provider
    assessment.report = report if isinstance(report, dict) else {}
    return assessment


def build_decision(assessment: Assessment, order: Order, drop: PriceDrop, competitor_name: str, *,
                   customer_claim: bool, customer_notes: str = "", evidence: dict | None = None) -> Decision:
    recommend, policy_reason = assessment.recommendation()
    report = dict(assessment.report)
    report["reasoning"] = report.get("reasoning") if recommend else policy_reason
    report["recommended_action"] = "APPROVE_PARTIAL_REFUND" if recommend else "POLICY_SKIP"
    report["return_probability"] = round(assessment.probability, 4)
    report["baseline_probability"] = round(assessment.baseline_probability, 4)
    report["evidence_source"] = "channel3_live"
    report["financial_breakdown"] = {
        "purchase_price": money(assessment.unit_price),
        "quantity": assessment.quantity,
        "purchase_value": money(assessment.purchase_value),
        "offer_price": money(assessment.offer_price),
        "price_difference": money(assessment.price_difference),
        "drop_percentage": round(assessment.drop_percentage, 1),
        "days_since_purchase": assessment.days_since,
        "protection_window_days": assessment.window_days,
        "proposed_refund": money(assessment.refund_amount),
        "estimated_return_cost": money(assessment.return_cost),
        "reverse_shipping": money(assessment.reverse_shipping),
        "restocking_cost": money(assessment.restocking_cost),
        "open_box_loss": money(assessment.open_box_loss),
        "lost_margin": money(assessment.lost_margin),
        "loss_if_returned": money(assessment.loss_if_returned),
        "expected_loss": money(assessment.expected_loss),
        "net_savings": money(assessment.expected_savings),
    }
    if evidence:
        report["channel3_offer"] = evidence
    # A buyer request always gets a merchant answer; a merchant-side scan skips non-recommended orders.
    if customer_claim:
        status = "PENDING_REVIEW" if assessment.within_window and assessment.refund_amount > 0 else "SKIPPED"
        refund_amount = assessment.refund_amount
    else:
        status = "PENDING_REVIEW" if recommend else "SKIPPED"
        refund_amount = assessment.refund_amount if recommend else Decimal("0.00")
    drafted = report.get("drafted_customer_message") or agent.generate_customer_message(
        order.buyer_name or "Buyer", drop.product.name if drop.product else "purchase", float(refund_amount), competitor_name, assessment.window_days)
    return Decision(
        price_drop_id=drop.id, capture_id=order.capture.id, order_id=order.id,
        decision="REFUND" if recommend else "SKIP", refund_amount=refund_amount,
        reasoning=json.dumps(report, default=str), return_probability=assessment.probability,
        estimated_return_cost=assessment.return_cost,
        estimated_savings=max(Decimal("0.00"), assessment.expected_savings),
        within_window=assessment.within_window, budget_available=assessment.budget_available,
        customer_claim=customer_claim, customer_notes=customer_notes, ai_drafted_message=drafted,
        competitor_name=competitor_name, competitor_price=assessment.offer_price, status=status,
    )


# -- refund execution -------------------------------------------------------------------
def _apply_completed_refund(db: Session, refund: Refund) -> None:
    capture = db.get(Capture, refund.capture_id)
    if capture:
        capture.refunded_amount = as_decimal(capture.refunded_amount) + as_decimal(refund.amount)
        capture.status = "REFUNDED" if as_decimal(capture.refunded_amount) >= as_decimal(capture.amount) else "COMPLETED"
    if refund.decision_id:
        decision = db.get(Decision, refund.decision_id)
        if decision:
            decision.status = "REFUNDED"


def mark_refund_status(db: Session, refund: Refund, status: str) -> None:
    """Move a refund to PayPal's reported status, applying the capture balance once."""
    if refund.status == "COMPLETED" or status == refund.status:
        return
    refund.status = status
    if status == "COMPLETED":
        refund.completed_at = now_utc()
        _apply_completed_refund(db, refund)
    elif status in {"FAILED", "CANCELLED"} and refund.decision_id:
        decision = db.get(Decision, refund.decision_id)
        if decision:
            decision.status = "REFUND_FAILED"


def check_refund_limits(db: Session, capture: Capture, amount: Decimal, settings_row: MerchantSettings, exclude_id: str | None = None) -> None:
    if refunds_for_capture(db, capture.id, exclude_id) + amount > as_decimal(capture.amount):
        raise HTTPException(409, "The refund exceeds the remaining captured balance.")
    if amount > as_decimal(settings_row.max_refund_per_order):
        raise HTTPException(409, "The refund exceeds the merchant per-order cap.")
    if refunds_today(db, exclude_id) + amount > as_decimal(settings_row.daily_refund_budget):
        raise HTTPException(409, "The daily refund budget has been reached.")


async def execute_decision_refund(db: Session, decision: Decision) -> Refund:
    """Send (or safely retry) the PayPal refund for an approved decision."""
    capture = db.scalar(select(Capture).where(Capture.id == decision.capture_id).with_for_update())
    if not capture or not capture.paypal_capture_id:
        raise HTTPException(409, "This claim is not attached to a refundable PayPal capture.")
    refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
    if refund and refund.status == "COMPLETED":
        return refund
    amount = as_decimal(decision.refund_amount)
    if amount <= 0:
        raise HTTPException(409, "There is no refund amount to send.")
    settings_row = get_settings_row(db)
    if refund is None:
        refund = Refund(decision_id=decision.id, capture_id=capture.id, amount=amount, currency=decision.order.currency,
                        status="PENDING", idempotency_key=f"refund-{decision.id}",
                        note_to_payer="DropBack price protection: we matched a lower price and refunded the difference.")
        db.add(refund)
    elif refund.status == "FAILED":
        # PayPal rejected the last attempt; a new attempt needs a new request ID.
        refund.idempotency_key = f"refund-{decision.id}-{uuid4().hex[:8]}"
        refund.amount = amount
        refund.status = "PENDING"
    # An existing PENDING refund keeps its key so a retry cannot pay twice.
    db.flush()
    try:
        check_refund_limits(db, capture, as_decimal(refund.amount), settings_row, exclude_id=refund.id)
    except HTTPException:
        refund.status = "FAILED"
        decision.status = "REFUND_FAILED"
        db.commit()
        raise
    decision.status = "REFUND_PENDING"
    db.commit()

    try:
        response = await paypal.refund_capture(capture.paypal_capture_id, refund.idempotency_key, money_text(refund.amount), refund.currency, refund.note_to_payer)
    except PayPalError as exc:
        if not exc.retryable:
            refund.status = "FAILED"
            decision.status = "REFUND_FAILED"
            add_action(db, "REFUND_FAILED", "refund", refund.id, {"error": str(exc)})
            db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc

    refund.paypal_refund_id = response.get("id")
    mark_refund_status(db, refund, response.get("status", "PENDING"))
    add_action(db, "REFUND_ISSUED", "refund", refund.id, {"paypal_refund_id": refund.paypal_refund_id, "amount": money(refund.amount), "status": refund.status})
    db.commit()
    return refund


async def issue_manual_refund(db: Session, capture_id: str, amount_value, currency: str, note: str, idempotency_key: str) -> dict:
    """A merchant-initiated refund on a known capture, outside the claim flow."""
    settings = get_settings()
    if settings.paypal_env.lower() != "sandbox" or "api-m.sandbox.paypal.com" not in settings.paypal_base_url.lower():
        raise HTTPException(409, "Manual refunds from the API lab are restricted to PayPal Sandbox.")
    key = (idempotency_key or "").strip()
    if not 8 <= len(key) <= 60:
        raise HTTPException(400, "Send an Idempotency-Key of 8–60 characters with each new refund.")
    try:
        submitted = Decimal(str(amount_value))
    except Exception as exc:
        raise HTTPException(422, "Enter a valid refund amount.") from exc
    amount = as_decimal(submitted)
    if submitted != amount or amount <= 0:
        raise HTTPException(422, "Refund amount must be a positive value with no more than two decimal places.")

    capture = db.scalar(select(Capture).where(Capture.paypal_capture_id == capture_id).with_for_update())
    if not capture:
        raise HTTPException(404, "Choose a captured PayPal Sandbox payment from this merchant account.")
    if currency.upper() != capture.currency.upper():
        raise HTTPException(409, "Refund currency must match the captured PayPal payment.")

    request_key = f"manual-{key}"
    existing = db.scalar(select(Refund).where(Refund.idempotency_key == request_key))
    if existing:
        if existing.capture_id != capture.id or as_decimal(existing.amount) != amount:
            raise HTTPException(409, "This Idempotency-Key was already used for a different refund.")
        if existing.status in ACTIVE_REFUND_STATUSES and existing.paypal_refund_id:
            return {"status": "SUCCESS", "replayed": True, "refund_id": existing.paypal_refund_id, "refund_status": existing.status,
                    "amount": money(existing.amount), "currency": existing.currency}
        if existing.status == "FAILED":
            raise HTTPException(409, "That refund attempt failed. Start a new refund to try again.")

    active_claim = db.scalar(select(Decision.id).where(
        Decision.capture_id == capture.id, Decision.status.in_({"PENDING_REVIEW", "APPROVED", "REFUND_PENDING"})))
    if active_claim:
        raise HTTPException(409, "This capture has an open DropBack claim. Resolve it from the claims queue.")

    refund = existing or Refund(decision_id=None, capture_id=capture.id, amount=amount, currency=capture.currency,
                                status="PENDING", idempotency_key=request_key, note_to_payer=(note or "Refund from merchant")[:255])
    if not existing:
        db.add(refund)
    db.flush()
    try:
        check_refund_limits(db, capture, amount, get_settings_row(db), exclude_id=refund.id)
    except HTTPException:
        db.delete(refund)
        db.commit()
        raise
    db.commit()

    try:
        response = await paypal.refund_capture(capture.paypal_capture_id, request_key, money_text(amount), capture.currency, refund.note_to_payer)
    except PayPalError as exc:
        if not exc.retryable:
            refund.status = "FAILED"
            db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc
    refund.paypal_refund_id = response.get("id")
    mark_refund_status(db, refund, response.get("status", "PENDING"))
    add_action(db, "MANUAL_REFUND_ISSUED", "refund", refund.id, {"paypal_refund_id": refund.paypal_refund_id, "amount": money(amount), "status": refund.status})
    db.commit()
    return {"status": "SUCCESS", "refund_id": refund.paypal_refund_id, "refund_status": refund.status,
            "amount": money(amount), "currency": refund.currency, "idempotency_key": key}
