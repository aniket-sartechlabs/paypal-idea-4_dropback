import pytest
from fastapi.testclient import TestClient
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.database import Base
from app.models.entities import Order
from app.services.agent import deterministic_score
from app.services.channel3 import _match_score, _offer_price


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", test_sessions)

    def override_get_db():
        db = test_sessions()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_get_db
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_deterministic_risk_score_stays_in_bounds():
    probability, reason = deterministic_score("Electronics", 20, 2)
    assert 0 <= probability <= 1
    assert "Rule-based" in reason


def test_channel3_offer_price_parser_handles_nested_price():
    assert _offer_price({"price": {"price": 88.4, "currency": "USD"}}) == 88.4
    assert _offer_price({"price": "not-a-price"}) is None


def test_channel3_matcher_rejects_a_different_product_variant():
    assert _match_score("Barista Pro Espresso Machine", "ESPRESSO-01", {"title": "Barista Express Espresso Machine"}) == 0
    assert _match_score("Barista Express Espresso Machine", "ESPRESSO-01", {"title": "Barista Express Espresso Machine"}) == 1
    assert _match_score("Everyday Carry Backpack", "BAG-01", {"title": "Ranchero Everyday Carry Backpack"}) < 0.95


def test_merchant_login_protects_dashboard_and_sample_orders_cannot_be_refunded(client, monkeypatch):
    async def local_score(category, drop_percentage, days_since_purchase, probability, savings):
        return 0.7, "Local test score: likely return after a recent price drop.", "rules"

    monkeypatch.setattr(main, "explain_decision", local_score)
    assert client.get("/api/v1/agent/decisions").status_code == 401
    response = client.post("/api/v1/auth/login", json={"email": "demo@dropback.local", "password": "dropback-demo"})
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").json()["authenticated"] is True

    products = client.get("/api/v1/products").json()
    update = client.patch(f"/api/v1/products/{products[0]['id']}/price", json={"new_price": "450.00"})
    assert update.status_code == 200
    drop = update.json()["price_drop"]
    assert drop["source"] == "merchant"

    processed = client.post(f"/api/v1/price-drops/{drop['id']}/process")
    assert processed.status_code == 200
    recommendations = [row for row in processed.json() if row["decision"] == "REFUND"]
    assert recommendations
    assert all(row["source"] == "sample" for row in recommendations)

    approved = client.post(f"/api/v1/agent/decisions/{recommendations[0]['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["can_execute"] is False
    refund = client.post(f"/api/v1/refunds/{recommendations[0]['id']}/execute")
    assert refund.status_code == 409
    assert "sample order" in refund.json()["detail"].lower()


def test_auto_refunds_are_rejected(client):
    client.post("/api/v1/auth/login", json={"email": "demo@dropback.local", "password": "dropback-demo"})
    response = client.patch("/api/v1/settings", json={"auto_refund_enabled": True})
    assert response.status_code == 422
    assert "disabled" in response.json()["detail"].lower()


def test_cancelled_checkout_cannot_be_captured(client):
    order = Order(id="sandbox-cancel-test", paypal_order_id="SANDBOX-ORDER-CANCEL-TEST", request_key="cancel-test-key",
                  request_hash="", status="CREATED", source="paypal", total_amount=Decimal("10.00"), currency="USD")
    with main.SessionLocal() as db:
        db.add(order)
        db.commit()

    cancelled = client.post(f"/api/v1/orders/{order.id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    capture = client.post(f"/api/v1/orders/{order.id}/capture")
    assert capture.status_code == 409


def test_paypal_checkout_to_approved_partial_refund_lifecycle(client, monkeypatch):
    monkeypatch.setattr(main.settings, "paypal_client_id", "sandbox-test-client")
    monkeypatch.setattr(main.settings, "paypal_client_secret", "sandbox-test-secret")

    async def create_paypal_order(order_id, request_id, items, total, currency, brand):
        assert total == "499.00"
        assert currency == "USD"
        assert items[0]["sku"] == "ESPRESSO-BARISTA-01"
        return {"id": "PAYPAL-ORDER-TEST", "status": "CREATED"}

    async def capture_paypal_order(paypal_order_id, request_id):
        assert paypal_order_id == "PAYPAL-ORDER-TEST"
        return {
            "status": "COMPLETED",
            "payer": {"name": {"given_name": "Sandbox", "surname": "Buyer"}, "email_address": "buyer@example.test"},
            "purchase_units": [{"payments": {"captures": [{
                "id": "PAYPAL-CAPTURE-TEST", "status": "COMPLETED",
                "amount": {"value": "499.00", "currency_code": "USD"},
            }]}}],
        }

    refund_calls = []

    async def refund_paypal_capture(capture_id, request_id, amount, currency, note):
        refund_calls.append((capture_id, request_id, amount, currency))
        return {"id": "PAYPAL-REFUND-TEST", "status": "COMPLETED"}

    async def local_score(category, drop_percentage, days_since_purchase, probability, savings):
        return 0.95, "Test scorer: likely return after a recent price drop.", "rules"

    monkeypatch.setattr(main.paypal, "create_order", create_paypal_order)
    monkeypatch.setattr(main.paypal, "capture_order", capture_paypal_order)
    monkeypatch.setattr(main.paypal, "refund_capture", refund_paypal_capture)
    monkeypatch.setattr(main, "explain_decision", local_score)

    products = client.get("/api/v1/products").json()
    product = next(row for row in products if row["sku"] == "ESPRESSO-BARISTA-01")
    created = client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "checkout-lifecycle-test"},
        json={"items": [{"product_id": product["id"], "quantity": 1}]},
    )
    assert created.status_code == 201
    order = created.json()

    # Retrying order creation with the same key returns the same PayPal order.
    repeated = client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "checkout-lifecycle-test"},
        json={"items": [{"product_id": product["id"], "quantity": 1}]},
    )
    assert repeated.status_code == 201
    assert repeated.json()["order_id"] == "PAYPAL-ORDER-TEST"

    captured = client.post(f"/api/v1/orders/{order['internal_order_id']}/capture")
    assert captured.status_code == 200
    assert captured.json()["status"] == "COMPLETED"
    assert captured.json()["amount"] == 499.0

    login = client.post("/api/v1/auth/login", json={"email": "demo@dropback.local", "password": "dropback-demo"})
    assert login.status_code == 200
    changed = client.patch(f"/api/v1/products/{product['id']}/price", json={"new_price": "450.00"})
    assert changed.status_code == 200
    drop_id = changed.json()["price_drop"]["id"]
    evaluated = client.post(f"/api/v1/price-drops/{drop_id}/process")
    assert evaluated.status_code == 200
    recommendation = next(row for row in evaluated.json() if row["order_id"] == order["internal_order_id"])
    assert recommendation["decision"] == "REFUND"
    assert recommendation["refund_amount"] == 49.0
    assert recommendation["estimated_savings"] > 0

    approved = client.post(f"/api/v1/agent/decisions/{recommendation['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["can_execute"] is True
    refunded = client.post(f"/api/v1/refunds/{recommendation['id']}/execute")
    assert refunded.status_code == 200
    assert refunded.json()["status"] == "COMPLETED"
    assert refunded.json()["amount"] == 49.0
    assert refund_calls == [("PAYPAL-CAPTURE-TEST", f"refund-{recommendation['id']}", "49.00", "USD")]

    # A retry returns the recorded refund rather than sending another provider request.
    repeated_refund = client.post(f"/api/v1/refunds/{recommendation['id']}/execute")
    assert repeated_refund.status_code == 200
    assert repeated_refund.json()["refund_id"] == "PAYPAL-REFUND-TEST"
    assert len(refund_calls) == 1
