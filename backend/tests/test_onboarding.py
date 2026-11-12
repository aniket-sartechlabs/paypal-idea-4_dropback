"""Merchant onboarding: sign-up, connecting PayPal, importing orders, retailer policy, claim economics."""

from app.models.entities import MerchantSettings, Order
from app.services.paypal import PayPalError, paypal
from conftest import SONY, buy, merchant_login

OWNER = {"email": "owner@holloway.example", "password": "a-long-password", "store_name": "Holloway Goods"}
CLIENT_ID = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
CLIENT_SECRET = "SeCrEtSeCrEtSeCrEtSeCrEt0123456789"


def paypal_order(order_id="5O190127TN364715T", sku=SONY, email="shopper@example.com", price="398.00"):
    """A completed Orders v2 payload, as PayPal returns it for an order paid on the merchant's own checkout."""
    return {
        "id": order_id, "status": "COMPLETED", "create_time": "2026-11-12T09:00:00Z",
        "payer": {"name": {"given_name": "Ada", "surname": "Shopper"}, "email_address": email},
        "purchase_units": [{
            "items": [{"name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones", "sku": sku, "quantity": "1",
                       "unit_amount": {"value": price, "currency_code": "USD"}}],
            "payments": {"captures": [{"id": f"CAP-{order_id}", "status": "COMPLETED", "create_time": "2026-11-12T09:01:00Z",
                                       "amount": {"value": price, "currency_code": "USD"}}]},
        }],
    }


def fake_get_order(monkeypatch, known: dict):
    async def get_order(order_id):
        if order_id not in known:
            raise PayPalError("PayPal get order failed: not found", 502)
        return known[order_id]
    monkeypatch.setattr(paypal, "get_order", get_order)


def test_signup_creates_the_one_workspace_owner(client, make_client):
    assert client.get("/api/v1/auth/signup").json()["open"] is True
    created = client.post("/api/v1/auth/signup", json=OWNER)
    assert created.status_code == 201, created.text
    assert client.get("/api/v1/auth/me").json()["email"] == OWNER["email"]
    assert client.get("/api/v1/auth/signup").json() == {"open": False, "store_name": "Holloway Goods", "code_required": False}

    other = make_client()
    assert other.post("/api/v1/auth/signup", json={**OWNER, "email": "intruder@example.com"}).status_code == 409
    assert other.post("/api/v1/auth/login", json={"email": OWNER["email"], "password": "wrong-password"}).status_code == 401
    assert other.post("/api/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}).status_code == 200


def test_connect_paypal_verifies_and_encrypts_the_secret(client, sessions, monkeypatch):
    client.post("/api/v1/auth/signup", json=OWNER)

    async def reject(client_id, client_secret):
        raise PayPalError("PayPal rejected these credentials.", 400)
    monkeypatch.setattr(paypal, "verify_credentials", reject)
    assert client.post("/api/v1/setup/paypal", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}).status_code == 400
    assert paypal.credential_source == "env"

    async def accept(client_id, client_secret):
        return None
    monkeypatch.setattr(paypal, "verify_credentials", accept)
    response = client.post("/api/v1/setup/paypal", json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["webhook"]["registered"] is False  # local http URL: PayPal needs public HTTPS
    assert body["setup"]["paypal"]["source"] == "merchant"
    assert CLIENT_ID not in str(body) and CLIENT_SECRET not in str(body)
    assert paypal.client_id == CLIENT_ID and paypal.client_secret == CLIENT_SECRET
    with sessions() as db:
        row = db.get(MerchantSettings, "default")
        assert row.paypal_client_secret_enc and CLIENT_SECRET not in row.paypal_client_secret_enc

    assert client.delete("/api/v1/setup/paypal").json()["paypal"]["source"] == "env"


def test_buyer_portal_imports_an_order_from_the_merchants_own_checkout(client, sessions, monkeypatch, fake_channel3, make_client):
    fake_get_order(monkeypatch, {"5O190127TN364715T": paypal_order()})
    buyer = make_client()
    wrong = buyer.post("/api/v1/buyer/login", json={"order_id": "5O190127TN364715T", "email": "someone@else.com"})
    assert wrong.status_code == 401
    unknown = buyer.post("/api/v1/buyer/login", json={"order_id": "9ZZ00000AA000000Z", "email": "shopper@example.com"})
    assert unknown.status_code == 401

    signed_in = buyer.post("/api/v1/buyer/login", json={"order_id": "5O190127TN364715T", "email": "shopper@example.com"})
    assert signed_in.status_code == 200, signed_in.text
    with sessions() as db:
        order = db.query(Order).filter(Order.paypal_order_id == "5O190127TN364715T").one()
        assert order.source == "import" and order.capture.paypal_capture_id == "CAP-5O190127TN364715T"
        assert order.items[0].product_id is not None
        order_id = order.id

    check = buyer.post("/api/v1/claims/check-price", json={"order_id": order_id})
    assert check.status_code == 200 and check.json()["drop_amount"] == 50.0


def test_paypal_capture_webhook_imports_unknown_orders(client, sessions, monkeypatch):
    fake_get_order(monkeypatch, {"7XY12345AB678901C": paypal_order("7XY12345AB678901C")})

    async def verified(headers, event):
        return True
    monkeypatch.setattr(paypal, "verify_webhook", verified)
    event = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED",
             "resource": {"id": "CAP-7XY12345AB678901C", "supplementary_data": {"related_ids": {"order_id": "7XY12345AB678901C"}}}}
    assert client.post("/api/v1/webhooks/paypal", json=event).status_code == 200
    with sessions() as db:
        assert db.query(Order).filter(Order.paypal_order_id == "7XY12345AB678901C").count() == 1


def test_merchant_can_import_by_paypal_order_id(client, monkeypatch):
    fake_get_order(monkeypatch, {"3AB45678CD901234E": paypal_order("3AB45678CD901234E")})
    merchant_login(client)
    assert client.post("/api/v1/orders/import", json={"paypal_order_id": "NOTPAIDTOTHISAPP1"}).status_code == 404
    imported = client.post("/api/v1/orders/import", json={"paypal_order_id": "3AB45678CD901234E"})
    assert imported.status_code == 200, imported.text
    assert imported.json()["source"] == "import"
    setup = client.get("/api/v1/setup").json()
    assert setup["orders"]["imported"] == 1
    assert client.post("/api/v1/setup/complete").json()["completed"] is True


def test_allowed_retailers_limit_price_matching(client, sessions, fake_paypal, fake_channel3):
    order_id = buy(client, sessions)["internal_order_id"]
    merchant_login(client)
    saved = client.patch("/api/v1/settings", json={"allowed_retailers": "https://www.Target.com/, walmart.com"}).json()
    assert saved["allowed_retailers"] == ["target.com", "walmart.com"]
    check = client.post("/api/v1/claims/check-price", json={"order_id": order_id}).json()
    assert check["matched"] is False  # the only offer is from bestbuy.com
    client.patch("/api/v1/settings", json={"allowed_retailers": "bestbuy.com"})
    assert client.post("/api/v1/claims/check-price", json={"order_id": order_id}).json()["matched"] is True


def test_claim_economics_include_the_lost_sale(client, sessions, fake_paypal, fake_channel3):
    order_id = buy(client, sessions)["internal_order_id"]
    check = client.post("/api/v1/claims/check-price", json={"order_id": order_id}).json()
    claim = client.post("/api/v1/claims/submit", json={"order_id": order_id, "price_drop_id": check["price_drop_id"]}).json()
    fin = claim["analysis_report"]["financial_breakdown"]
    assert fin["lost_margin"] == round(398 * 0.30, 2)
    assert abs(fin["loss_if_returned"] - (fin["estimated_return_cost"] + fin["lost_margin"])) < 0.01
    expected = claim["return_probability"] * fin["loss_if_returned"] - fin["proposed_refund"]
    assert abs(fin["net_savings"] - expected) < 0.02


def test_production_signup_needs_the_invite_code(client, monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "signup_code", "")
    assert client.get("/api/v1/auth/signup").json()["open"] is False
    assert client.post("/api/v1/auth/signup", json=OWNER).status_code == 403

    monkeypatch.setattr(settings, "signup_code", "judge-invite-2026")
    assert client.get("/api/v1/auth/signup").json() == {"open": True, "store_name": "DropBack Demo Store", "code_required": True}
    assert client.post("/api/v1/auth/signup", json={**OWNER, "invite_code": "wrong"}).status_code == 403
    assert client.post("/api/v1/auth/signup", json={**OWNER, "invite_code": "judge-invite-2026"}).status_code == 201


def test_render_urls_are_normalized(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://dropback.onrender.com")
    settings = Settings(_env_file=None, database_url="postgresql://u:p@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://u:p@host:5432/db"
    assert settings.app_base_url == "https://dropback.onrender.com"
    assert "https://dropback.onrender.com" in settings.cors_origins
