"""JSON shapes returned by the API, plus small money helpers."""

import json
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import AgentAction, Decision, Order, PriceDrop, Product, Refund
from app.services.agent import generate_customer_message


def as_decimal(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money(value) -> float:
    return float(as_decimal(value))


def money_text(value: Decimal) -> str:
    return f"{as_decimal(value):.2f}"


def add_action(db: Session, action_type: str, entity_type: str = "", entity_id: str = "", details: dict | None = None) -> None:
    db.add(AgentAction(action_type=action_type, entity_type=entity_type, entity_id=entity_id, details=json.dumps(details or {}, default=str)))


def _https_or_none(url: str | None) -> str | None:
    return url if (url or "").startswith("https://") else None


def product_dict(product: Product) -> dict:
    return {
        "id": product.id, "name": product.name, "sku": product.sku, "description": product.description,
        "image_url": _https_or_none(product.image_url),
        "category": product.category, "current_price": money(product.current_price), "currency": product.currency,
        "protection_days": product.protection_days, "merchant_domain": product.merchant_domain,
        "channel3_connected": bool(product.channel3_product_id), "channel3_product_id": product.channel3_product_id,
        "last_market_price": money(product.last_market_price) if product.last_market_price is not None else None,
        "competitor_name": product.competitor_name, "competitor_url": product.competitor_url,
        "weight_lbs": float(product.weight_lbs) if product.weight_lbs is not None else None,
        "active": product.active,
    }


def store_product_dict(product: Product) -> dict:
    """Public storefront view: no merchant monitoring details."""
    return {
        "id": product.id, "name": product.name, "sku": product.sku, "description": product.description,
        "image_url": _https_or_none(product.image_url), "category": product.category,
        "current_price": money(product.current_price), "currency": product.currency,
        "protection_days": product.protection_days, "channel3_connected": bool(product.channel3_product_id),
    }


def order_dict(order: Order) -> dict:
    return {
        "id": order.id, "paypal_order_id": order.paypal_order_id, "status": order.status, "source": order.source,
        "buyer_name": order.buyer_name, "buyer_email": order.buyer_email, "total_amount": money(order.total_amount),
        "currency": order.currency, "created_at": order.created_at.isoformat() if order.created_at else None,
        "captured_at": order.captured_at.isoformat() if order.captured_at else None,
        "items": [{
            "product_id": item.product_id, "sku": item.sku, "name": item.name, "quantity": item.quantity,
            "unit_price": money(item.unit_price),
            "image_url": _https_or_none(item.product.image_url) if item.product else None,
        } for item in order.items],
        "refundable": bool(order.capture and order.capture.paypal_capture_id),
    }


def parse_decision_report(decision: Decision) -> tuple[str, dict]:
    raw = decision.reasoning or ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data.get("reasoning", ""), data
    except ValueError:
        pass
    return raw, {"reasoning": raw, "return_probability": float(decision.return_probability or 0), "provider": "rules"}


def price_drop_dict(drop: PriceDrop) -> dict:
    return {
        "id": drop.id, "product_id": drop.product_id, "product_name": drop.product.name, "sku": drop.product.sku,
        "old_price": money(drop.old_price), "new_price": money(drop.new_price), "drop_amount": money(drop.drop_amount),
        "drop_percentage": float(drop.drop_percentage), "source": drop.source, "detected_at": drop.detected_at.isoformat(),
        "processed": drop.processed, "offer_merchant": drop.offer_merchant, "offer_url": drop.offer_url,
    }


def decision_dict(decision: Decision, refund: Refund | None = None) -> dict:
    reason_text, report = parse_decision_report(decision)
    product = decision.price_drop.product if decision.price_drop and decision.price_drop.product else None
    product_name = product.name if product else "Item"
    sku = product.sku if product else ""
    comp_name = decision.competitor_name or (decision.price_drop.offer_merchant if decision.price_drop else None) or "authorized retailers"
    drafted_msg = decision.ai_drafted_message or report.get("drafted_customer_message") or generate_customer_message(
        decision.order.buyer_name or "Buyer", product_name, float(decision.refund_amount), comp_name)
    capture = decision.capture
    matching_items = [item for item in decision.order.items if item.sku == sku]
    sandbox = get_settings().paypal_env.lower() == "sandbox"
    data = {
        "id": decision.id, "price_drop_id": decision.price_drop_id, "order_id": decision.order_id,
        "paypal_order_id": decision.order.paypal_order_id, "buyer_name": decision.order.buyer_name,
        "buyer_email": decision.order.buyer_email, "product_name": product_name, "sku": sku,
        "purchase_price": max((money(item.unit_price) for item in matching_items), default=0),
        "quantity": sum(item.quantity for item in matching_items),
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
        "settlement_mode": "paypal_sandbox" if sandbox else "paypal_live",
        "can_execute": bool(capture and capture.paypal_capture_id and decision.status in {"PENDING_REVIEW", "APPROVED", "REFUND_PENDING", "REFUND_FAILED"}),
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
        "reviewed_at": decision.reviewed_at.isoformat() if decision.reviewed_at else None,
    }
    if refund is not None:
        data["refund_status"] = refund.status
        data["paypal_refund_id"] = refund.paypal_refund_id
    return data


def refund_dict(row: Refund) -> dict:
    return {
        "id": row.id, "decision_id": row.decision_id, "paypal_refund_id": row.paypal_refund_id, "amount": money(row.amount),
        "currency": row.currency, "status": row.status, "note_to_payer": row.note_to_payer,
        "kind": "claim" if row.decision_id else "manual",
        "created_at": row.created_at.isoformat(), "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }
