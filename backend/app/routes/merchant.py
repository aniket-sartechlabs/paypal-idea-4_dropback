"""Merchant console: claims queue, settlement, refunds, dashboard, and settings."""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.deps import Db
from app.models.entities import AgentAction, Capture, Decision, Order, PriceDrop, Refund, now_utc
from app.schemas import ClaimResolveInput, SettingsUpdate, ToolInvokeInput
from app.security import Merchant
from app.serializers import add_action, as_decimal, decision_dict, money, parse_decision_report, refund_dict
from app.services import claims, paypal_tools
from app.services.paypal import PayPalError, paypal

log = logging.getLogger("dropback.merchant")
router = APIRouter(prefix="/api/v1")
settings = get_settings()


def _decision_query():
    return select(Decision).options(
        joinedload(Decision.order).joinedload(Order.items), joinedload(Decision.order).joinedload(Order.capture),
        joinedload(Decision.capture), joinedload(Decision.price_drop).joinedload(PriceDrop.product))


def _with_refund(db, decision: Decision) -> dict:
    refund = db.scalar(select(Refund).where(Refund.decision_id == decision.id))
    data = decision_dict(decision, refund)
    if refund is None:
        data.update(refund_status=None, paypal_refund_id=None)
    return data


@router.get("/agent/decisions")
def list_decisions(db: Db, _: Merchant):
    rows = db.scalars(_decision_query().order_by(Decision.created_at.desc()).limit(500)).unique().all()
    refunds = {row.decision_id: row for row in db.scalars(select(Refund).where(Refund.decision_id.in_([d.id for d in rows]))).all()} if rows else {}
    return [decision_dict(row, refunds.get(row.id)) for row in rows]


@router.post("/claims/{decision_id}/resolve")
async def resolve_claim(decision_id: str, body: ClaimResolveInput, db: Db, _: Merchant):
    """Approve (sends the PayPal refund) or reject a claim. Approving again retries a pending or failed refund."""
    decision = db.scalar(_decision_query().where(Decision.id == decision_id))
    if not decision:
        raise HTTPException(404, "Claim not found.")

    if body.action == "reject":
        if decision.status not in {"PENDING_REVIEW", "APPROVED", "REFUND_FAILED"}:
            raise HTTPException(409, "This claim can no longer be rejected.")
        decision.status = "REJECTED"
        decision.reviewed_at = now_utc()
        decision.merchant_message = body.custom_message or "Your request was reviewed and could not be approved under the current price-protection policy."
        add_action(db, "CLAIM_REJECTED", "decision", decision.id, {"note": decision.merchant_message})
        db.commit()
        return _with_refund(db, decision)

    if decision.status == "REFUNDED":
        return _with_refund(db, decision)
    if decision.status not in {"PENDING_REVIEW", "APPROVED", "REFUND_PENDING", "REFUND_FAILED"}:
        raise HTTPException(409, "This claim is no longer awaiting a settlement decision.")
    if not decision.within_window:
        raise HTTPException(409, "This purchase is outside its price-protection window.")
    if decision.status != "REFUND_PENDING":
        # The amount can be changed only before a refund request has gone to PayPal.
        if body.refund_amount is not None:
            _, report = parse_decision_report(decision)
            verified = as_decimal((report.get("financial_breakdown") or {}).get("proposed_refund", decision.refund_amount))
            if as_decimal(body.refund_amount) > verified:
                raise HTTPException(422, "The refund cannot exceed the verified price difference in this claim.")
            decision.refund_amount = as_decimal(body.refund_amount)
        decision.merchant_message = body.custom_message or decision.ai_drafted_message
        decision.decision = "REFUND"
        decision.status = "APPROVED"
        decision.reviewed_at = now_utc()
        db.commit()

    try:
        refund = await claims.execute_decision_refund(db, decision)
    except HTTPException as exc:
        log.warning("Refund for claim %s did not complete: %s", decision.id, exc.detail)
        raise
    add_action(db, "CLAIM_SETTLEMENT_RESOLVED", "decision", decision.id, {"refund_amount": money(decision.refund_amount), "refund_status": refund.status})
    db.commit()
    db.expire_all()
    return _with_refund(db, db.scalar(_decision_query().where(Decision.id == decision.id)))


@router.get("/refunds")
def list_refunds(db: Db, _: Merchant):
    return [refund_dict(row) for row in db.scalars(select(Refund).order_by(Refund.created_at.desc()).limit(500)).all()]


@router.get("/refunds/{refund_id}/status")
async def refund_status(refund_id: str, db: Db, _: Merchant):
    row = db.get(Refund, refund_id)
    if not row:
        raise HTTPException(404, "Refund not found.")
    if row.paypal_refund_id and row.status == "PENDING":
        try:
            remote = await paypal.get_refund(row.paypal_refund_id)
        except PayPalError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        claims.mark_refund_status(db, row, remote.get("status", row.status))
        db.commit()
    return refund_dict(row)


@router.get("/dashboard/stats")
def dashboard_stats(db: Db, _: Merchant):
    settings_row = claims.get_settings_row(db)
    orders = db.scalars(select(Order).options(joinedload(Order.capture))).unique().all()
    decisions = db.scalars(select(Decision)).all()
    completed = db.scalars(select(Refund).where(Refund.status == "COMPLETED", Refund.decision_id.is_not(None))).all()
    window = settings_row.price_protection_window_days
    return {
        "orders_exposed": sum(1 for order in orders if order.capture and order.captured_at and (now_utc() - order.captured_at).days <= window),
        "refunds_issued": len(completed),
        "total_refunded": round(sum(money(row.amount) for row in completed), 2),
        "recommendations_pending": sum(1 for row in decisions if row.status == "PENDING_REVIEW"),
        "estimated_returns_avoided": len(completed),
        "estimated_savings": round(sum(money(row.estimated_savings) for row in decisions if row.status == "REFUNDED"), 2),
        "orders_total": len(orders), "decisions_total": len(decisions),
        "paypal_configured": settings.paypal_ready, "channel3_configured": bool(settings.channel3_api_key),
    }


@router.get("/dashboard/timeline")
def dashboard_timeline(db: Db, _: Merchant):
    rows = db.scalars(select(Refund).order_by(Refund.created_at.desc()).limit(30)).all()
    return [{"date": row.created_at.date().isoformat(), "amount": money(row.amount), "status": row.status} for row in rows]


@router.get("/settings")
def read_settings(db: Db, _: Merchant):
    row = claims.get_settings_row(db)
    return {"merchant_name": row.merchant_name, "price_protection_window_days": row.price_protection_window_days,
            "max_refund_per_order": money(row.max_refund_per_order), "daily_refund_budget": money(row.daily_refund_budget),
            "auto_refund_enabled": False, "min_price_drop_percentage": float(row.min_price_drop_percentage),
            "min_price_drop_amount": money(row.min_price_drop_amount), "return_shipping_cost": money(row.return_shipping_cost),
            "restocking_fee_percentage": float(row.restocking_fee_percentage), "open_box_discount_percentage": float(row.open_box_discount_percentage),
            "channel3_configured": bool(settings.channel3_api_key), "paypal_environment": settings.paypal_env,
            "llm_configured": bool(settings.openai_api_key or settings.gemini_api_key)}


@router.patch("/settings")
def update_settings(body: SettingsUpdate, db: Db, merchant: Merchant):
    if body.auto_refund_enabled:
        raise HTTPException(422, "Automatic refunds are disabled in this build. Merchant approval is required before every payment action.")
    row = claims.get_settings_row(db)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    db.commit()
    return read_settings(db, merchant)


@router.get("/agent/actions")
def list_agent_actions(db: Db, _: Merchant):
    rows = db.scalars(select(AgentAction).order_by(AgentAction.created_at.desc()).limit(100)).all()
    return [{"id": row.id, "action_type": row.action_type, "entity_type": row.entity_type, "entity_id": row.entity_id,
             "details": json.loads(row.details or "{}"), "created_at": row.created_at.isoformat()} for row in rows]


# -- PayPal API lab (Server SDK tools) -------------------------------------------------------
@router.get("/paypal-tools/status")
def paypal_tools_status(_: Merchant):
    return paypal_tools.status()


@router.get("/paypal-tools/sandbox-orders")
def paypal_sandbox_orders(db: Db, _: Merchant):
    rows = db.scalars(select(Order).options(joinedload(Order.capture), joinedload(Order.items))
                      .where(Order.paypal_order_id.is_not(None)).order_by(Order.created_at.desc()).limit(10)).unique().all()
    return [{
        "order_id": row.paypal_order_id, "capture_id": row.capture.paypal_capture_id if row.capture else None,
        "buyer_name": row.buyer_name, "item_name": row.items[0].name if row.items else "PayPal order",
        "amount": money(row.total_amount), "currency": row.currency, "status": row.status,
        "refundable_balance": money(as_decimal(row.capture.amount) - claims.refunds_for_capture(db, row.capture.id)) if row.capture else 0,
    } for row in rows]


@router.post("/paypal-tools/invoke")
async def paypal_tools_invoke(body: ToolInvokeInput, db: Db, _: Merchant,
                              idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    if body.tool != "paypal_issue_capture_refund":
        return await paypal_tools.run_read_tool(body.tool, body.arguments)
    args = body.arguments
    capture_id = str(args.get("capture_id", "")).strip()
    if not db.scalar(select(Capture.id).where(Capture.paypal_capture_id == capture_id)):
        raise HTTPException(404, "Choose a captured PayPal Sandbox payment from this merchant account.")
    result = await claims.issue_manual_refund(db, capture_id, args.get("amount"), str(args.get("currency", "USD")),
                                              str(args.get("note_to_payer", "")), idempotency_key or "")
    return {"tool": body.tool, **result}
