import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database
from app.config import get_settings
from app.services.channel3 import channel3
from app.services.paypal import paypal

MERCHANT = {"email": "demo@dropback.local", "password": "dropback-demo"}
SONY = "SONY-WH1000XM5-BLK"


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Isolated database plus deterministic settings (rules scoring, fake PayPal credentials)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    settings = get_settings()
    for key, value in {"paypal_client_id": "sandbox-test-client", "paypal_client_secret": "sandbox-test-secret",
                       "paypal_env": "sandbox", "paypal_base_url": "https://api-m.sandbox.paypal.com",
                       "openai_api_key": "", "gemini_api_key": "", "channel3_api_key": "test-channel3",
                       "merchant_email": "", "merchant_password": "", "mcp_api_token": ""}.items():
        monkeypatch.setattr(settings, key, value)

    from app import main

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[database.get_db] = override_get_db
    yield main.app, sessions
    main.app.dependency_overrides.clear()
    database.Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(app_env):
    with TestClient(app_env[0]) as test_client:
        yield test_client


@pytest.fixture
def make_client(app_env):
    """Extra browsers (separate cookie jars) against the same app."""
    opened = []

    def factory():
        test_client = TestClient(app_env[0])
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    yield factory
    for test_client in opened:
        test_client.__exit__(None, None, None)


@pytest.fixture
def sessions(app_env):
    return app_env[1]


@pytest.fixture
def fake_paypal(monkeypatch):
    """Records PayPal calls and returns realistic Sandbox payloads."""
    calls = {"create": [], "capture": [], "refund": []}
    counter = itertools.count(1)

    async def create_order(order_id, request_id, items, total, currency, brand):
        calls["create"].append({"order_id": order_id, "request_id": request_id, "items": items, "total": total})
        return {"id": f"PAYPAL-ORDER-{next(counter)}", "status": "CREATED"}

    async def capture_order(paypal_order_id, request_id):
        calls["capture"].append({"paypal_order_id": paypal_order_id, "request_id": request_id})
        total = calls["create"][-1]["total"]
        return {"status": "COMPLETED", "payer": {"name": {"given_name": "Sandbox", "surname": "Buyer"}, "email_address": "buyer@example.com"},
                "purchase_units": [{"payments": {"captures": [{"id": f"CAPTURE-{paypal_order_id}", "status": "COMPLETED",
                                                               "amount": {"value": total, "currency_code": "USD"}}]}}]}

    async def refund_capture(capture_id, request_id, amount, currency, note):
        calls["refund"].append({"capture_id": capture_id, "request_id": request_id, "amount": amount})
        return {"id": f"REFUND-{len(calls['refund'])}", "status": "COMPLETED"}

    monkeypatch.setattr(paypal, "create_order", create_order)
    monkeypatch.setattr(paypal, "capture_order", capture_order)
    monkeypatch.setattr(paypal, "refund_capture", refund_capture)
    return calls


@pytest.fixture
def fake_channel3(monkeypatch):
    """Channel3 returns one lower in-stock offer for the exact product."""
    offer = {"price": 348.00, "merchant": "bestbuy.com", "url": "https://www.bestbuy.com/sony-xm5", "available": True, "condition": "new"}

    async def search_and_compare(product_name, sku, local_price, currency):
        return {"matched": True, "product_id": "ch3-sony", "title": product_name, "match_confidence": 0.98,
                "best_offer": dict(offer), "all_offers": [dict(offer)], "lower_than_current": offer["price"] < local_price}

    monkeypatch.setattr(channel3, "search_and_compare", search_and_compare)
    return offer


def product_id(client_or_sessions, sku=SONY):
    from app.models.entities import Product
    with client_or_sessions() as db:
        return db.query(Product).filter(Product.sku == sku).one().id


def buy(client, sessions, quantity=1, sku=SONY, key="idem-key-0001"):
    """Create and capture a Sandbox order in `client`'s browser. Returns the capture response."""
    created = client.post("/api/v1/orders", json={"items": [{"product_id": product_id(sessions, sku), "quantity": quantity}]},
                          headers={"Idempotency-Key": key})
    assert created.status_code == 201, created.text
    captured = client.post(f"/api/v1/orders/{created.json()['order_id']}/capture")
    assert captured.status_code == 200, captured.text
    return captured.json()


def merchant_login(client):
    response = client.post("/api/v1/auth/login", json=MERCHANT)
    assert response.status_code == 200
