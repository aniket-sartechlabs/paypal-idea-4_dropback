from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="General")
    image_url: Mapped[str] = mapped_column(String(500), default="")
    current_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    protection_days: Mapped[int] = mapped_column(Integer, default=14)
    channel3_product_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    channel3_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_market_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    competitor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    competitor_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    weight_lbs: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    merchant_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paypal_order_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    request_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="CREATING", index=True)
    source: Mapped[str] = mapped_column(String(16), default="paypal")
    buyer_name: Mapped[str] = mapped_column(String(160), default="")
    buyer_email: Mapped[str] = mapped_column(String(254), default="")
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    capture: Mapped["Capture | None"] = relationship(back_populates="order", uselist=False)


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2))
    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()


class Capture(Base):
    __tablename__ = "captures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="COMPLETED")
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    refunded_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    capture_key: Mapped[str] = mapped_column(String(80), unique=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    order: Mapped[Order] = relationship(back_populates="capture")


class PriceDrop(Base):
    __tablename__ = "price_drops"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    old_price: Mapped[float] = mapped_column(Numeric(10, 2))
    new_price: Mapped[float] = mapped_column(Numeric(10, 2))
    drop_amount: Mapped[float] = mapped_column(Numeric(10, 2))
    drop_percentage: Mapped[float] = mapped_column(Numeric(7, 3))
    source: Mapped[str] = mapped_column(String(24), default="manual")
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    # The retailer and listing behind this observation, kept with the evidence so a
    # later price check on the same product cannot change what a claim cites.
    offer_merchant: Mapped[str | None] = mapped_column(String(120), nullable=True)
    offer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    product: Mapped[Product] = relationship()


class Decision(Base):
    __tablename__ = "refund_decisions"
    __table_args__ = (UniqueConstraint("price_drop_id", "order_id", name="uq_decision_drop_order"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    price_drop_id: Mapped[str] = mapped_column(ForeignKey("price_drops.id"), index=True)
    capture_id: Mapped[str] = mapped_column(ForeignKey("captures.id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    decision: Mapped[str] = mapped_column(String(24), index=True)
    refund_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    reasoning: Mapped[str] = mapped_column(Text)
    return_probability: Mapped[float] = mapped_column(Numeric(5, 4))
    estimated_return_cost: Mapped[float] = mapped_column(Numeric(10, 2))
    estimated_savings: Mapped[float] = mapped_column(Numeric(10, 2))
    within_window: Mapped[bool] = mapped_column(Boolean)
    budget_available: Mapped[bool] = mapped_column(Boolean)
    customer_claim: Mapped[bool] = mapped_column(Boolean, default=False)
    customer_notes: Mapped[str] = mapped_column(Text, default="")
    ai_drafted_message: Mapped[str] = mapped_column(Text, default="")
    merchant_message: Mapped[str] = mapped_column(Text, default="")
    competitor_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    competitor_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING_REVIEW", index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    price_drop: Mapped[PriceDrop] = relationship()
    order: Mapped[Order] = relationship()
    capture: Mapped[Capture] = relationship()


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paypal_refund_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # Null for a manual refund issued from the PayPal API lab / MCP tool.
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("refund_decisions.id"), unique=True, index=True, nullable=True)
    capture_id: Mapped[str] = mapped_column(ForeignKey("captures.id"))
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    note_to_payer: Mapped[str] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentAction(Base):
    __tablename__ = "agent_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class MerchantSettings(Base):
    __tablename__ = "merchant_settings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    merchant_name: Mapped[str] = mapped_column(String(120), default="DropBack Demo Store")
    price_protection_window_days: Mapped[int] = mapped_column(Integer, default=14)
    max_refund_per_order: Mapped[float] = mapped_column(Numeric(10, 2), default=100)
    daily_refund_budget: Mapped[float] = mapped_column(Numeric(10, 2), default=500)
    auto_refund_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    min_price_drop_percentage: Mapped[float] = mapped_column(Numeric(7, 3), default=5)
    min_price_drop_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=5)
    return_shipping_cost: Mapped[float] = mapped_column(Numeric(10, 2), default=12)
    restocking_fee_percentage: Mapped[float] = mapped_column(Numeric(7, 3), default=15)
    open_box_discount_percentage: Mapped[float] = mapped_column(Numeric(7, 3), default=25)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipts"
    event_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
