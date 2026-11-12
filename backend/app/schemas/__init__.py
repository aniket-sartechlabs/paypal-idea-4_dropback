"""Request bodies accepted by the DropBack API."""

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class BuyerLoginInput(BaseModel):
    order_id: str = Field(min_length=4, max_length=64)
    email: str = Field(min_length=3, max_length=254)


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
    gross_margin_percentage: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=3)
    allowed_retailers: str | None = Field(default=None, max_length=2000)
    store_url: str | None = Field(default=None, max_length=255)


class SignupInput(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=256)
    store_name: str = Field(min_length=2, max_length=120)
    invite_code: str | None = Field(default=None, max_length=128)


class PayPalConnectInput(BaseModel):
    client_id: str = Field(min_length=20, max_length=255)
    client_secret: str = Field(min_length=20, max_length=255)


class OrderImportInput(BaseModel):
    paypal_order_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")


class CheckPriceInput(BaseModel):
    order_id: str = Field(min_length=4, max_length=64)
    product_id: str | None = None


class ClaimSubmitInput(BaseModel):
    order_id: str
    product_id: str | None = None
    price_drop_id: str | None = None
    customer_notes: str = Field(default="", max_length=1500)


class ClaimResolveInput(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    refund_amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    custom_message: str | None = Field(default=None, max_length=2000)


class ToolInvokeInput(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


class LookupInput(BaseModel):
    url: str = Field(min_length=10, max_length=1000, pattern=r"^https?://")
