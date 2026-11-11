import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.database import Base
from app.models.entities import Order, Product, Capture


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test_claims.db'}", connect_args={"check_same_thread": False})
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


def test_apimatic_status_endpoint(client):
    res = client.get("/api/v1/apimatic/status")
    assert res.status_code == 200
    data = res.json()
    assert data["apimatic_enabled"] is True
    assert "tools" in data
    assert len(data["tools"]) >= 4
    tool_names = [t["name"] for t in data["tools"]]
    assert "paypal_get_order_details" in tool_names
    assert "paypal_check_sandbox_health" in tool_names


def test_customer_claim_flow(client, monkeypatch):
    # Mock channel3 compare to return a $50 drop
    async def mock_search_and_compare(product_name, sku, local_price, currency):
        return {
            "matched": True,
            "product_id": "test-p1",
            "title": product_name,
            "best_offer": {"price": local_price - 50.0, "merchant": "bhphotovideo.com", "url": "https://example.com/bh"},
            "all_offers": [{"price": local_price - 50.0, "merchant": "bhphotovideo.com"}],
            "lower_than_current": True,
        }

    monkeypatch.setattr(main.channel3, "search_and_compare", mock_search_and_compare)

    # 1. Login merchant and get products
    login = client.post("/api/v1/auth/login", json={"email": "demo@dropback.local", "password": "dropback-demo"})
    assert login.status_code == 200
    prods = client.get("/api/v1/products").json()
    product = prods[0]

    # 2. Check price for claim
    check_resp = client.post("/api/v1/claims/check-price", json={"product_id": product["id"]})
    assert check_resp.status_code == 200
    check_data = check_resp.json()
    assert check_data["price_drop_detected"] is True
    assert check_data["competitor_name"] == "bhphotovideo.com"
    assert check_data["drop_amount"] == 50.0

    # 3. Create a captured order
    orders = client.get("/api/v1/orders").json()
    sample_order = orders[0]

    # 4. Submit claim from customer POV
    claim_resp = client.post("/api/v1/claims/submit", json={
        "order_id": sample_order["id"],
        "product_id": product["id"],
        "customer_notes": "Saw lower price on B&H. Requesting difference credit under DropBack 14-day cover.",
    })
    assert claim_resp.status_code == 200
    claim_data = claim_resp.json()
    assert claim_data["customer_claim"] is True
    assert "B&H" in claim_data["customer_notes"]
    assert claim_data["status"] == "PENDING_REVIEW"
    assert "drafted_customer_message" in claim_data["analysis_report"] or len(claim_data["ai_drafted_message"]) > 0

    # 5. Lookup claim
    claim_id = claim_data["id"]
    status_resp = client.get(f"/api/v1/claims/{claim_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == claim_id

    # 6. Merchant resolves claim
    resolve_resp = client.post(f"/api/v1/claims/{claim_id}/resolve", json={
        "action": "approve",
        "custom_message": "Approved! Credited $50 to your PayPal account. Enjoy your machine without returning!",
    })
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "APPROVED"
    assert "Enjoy your machine" in resolve_resp.json()["merchant_message"]

    # 7. Customer looks up their order by ID and sees approved claim and merchant message
    lookup_resp = client.get(f"/api/v1/orders/lookup/{sample_order['id']}")
    assert lookup_resp.status_code == 200
    lookup_data = lookup_resp.json()
    assert lookup_data["claim"] is not None
    assert lookup_data["claim"]["status"] == "APPROVED"
    assert "Enjoy your machine" in lookup_data["claim"]["merchant_message"]


def test_apimatic_mcp_invoke(client, monkeypatch):
    async def mock_access_token():
        return "mock-access-token-12345"

    async def mock_get_order(order_id):
        return {"id": order_id, "status": "COMPLETED", "intent": "CAPTURE"}

    monkeypatch.setattr(main.paypal, "access_token", mock_access_token)
    monkeypatch.setattr(main.paypal, "get_order", mock_get_order)

    login = client.post("/api/v1/auth/login", json={"email": "demo@dropback.local", "password": "dropback-demo"})
    assert login.status_code == 200

    # 1. Invoke paypal_check_sandbox_health
    health_resp = client.post("/api/v1/apimatic/mcp/invoke", json={
        "tool": "paypal_check_sandbox_health",
        "arguments": {},
    })
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["tool"] == "paypal_check_sandbox_health"
    assert health_data["status"] == "SUCCESS"

    # 2. Invoke paypal_get_order_details
    order_resp = client.post("/api/v1/apimatic/mcp/invoke", json={
        "tool": "paypal_get_order_details",
        "arguments": {"order_id": "sample-order-maya-sony"},
    })
    assert order_resp.status_code == 200
    order_data = order_resp.json()
    assert order_data["status"] == "SUCCESS"
    assert "data" in order_data
    assert order_data["data"]["status"] == "COMPLETED"

