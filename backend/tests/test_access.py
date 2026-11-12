from decimal import Decimal

from app.models.entities import Order
from conftest import MERCHANT, buy, merchant_login, product_id


def test_merchant_endpoints_require_sign_in(client):
    for path in ["/api/v1/agent/decisions", "/api/v1/products", "/api/v1/orders", "/api/v1/channel3/search?query=sony",
                 "/api/v1/paypal-tools/status", "/api/v1/refunds", "/api/v1/settings"]:
        assert client.get(path).status_code == 401, path
    merchant_login(client)
    assert client.get("/api/v1/auth/me").json()["authenticated"] is True
    assert client.get("/api/v1/products").status_code == 200


def test_wrong_merchant_password_is_rejected(client):
    assert client.post("/api/v1/auth/login", json={**MERCHANT, "password": "nope"}).status_code == 401


def test_auto_refunds_are_rejected(client):
    merchant_login(client)
    response = client.patch("/api/v1/settings", json={"auto_refund_enabled": True})
    assert response.status_code == 422
    assert "disabled" in response.json()["detail"].lower()


def test_storefront_hides_merchant_monitoring_fields(client, sessions):
    from app.models.entities import Product
    with sessions() as db:
        db.query(Product).update({"channel3_product_id": "ch3-x", "competitor_name": "rival.com"})
        db.commit()
    rows = client.get("/api/v1/store/products").json()
    assert rows and all("competitor_name" not in row and "channel3_product_id" not in row for row in rows)


def test_only_the_buying_browser_or_a_signed_in_buyer_can_open_an_order(client, make_client, sessions, fake_paypal):
    capture = buy(client, sessions)
    order_id = capture["internal_order_id"]
    assert client.get(f"/api/v1/orders/lookup/{order_id}").status_code == 200

    stranger = make_client()
    assert stranger.get(f"/api/v1/orders/lookup/{order_id}").status_code == 403
    assert stranger.post("/api/v1/claims/check-price", json={"order_id": order_id}).status_code == 403
    assert stranger.post("/api/v1/claims/submit", json={"order_id": order_id}).status_code == 403

    wrong = stranger.post("/api/v1/buyer/login", json={"order_id": order_id, "email": "someone@else.com"})
    assert wrong.status_code == 401
    ok = stranger.post("/api/v1/buyer/login", json={"order_id": fake_paypal["capture"][0]["paypal_order_id"], "email": "BUYER@example.com"})
    assert ok.status_code == 200
    assert stranger.get(f"/api/v1/orders/lookup/{order_id}").status_code == 200
    assert [row["id"] for row in stranger.get("/api/v1/buyer/orders").json()["orders"]] == [order_id]

    stranger.post("/api/v1/buyer/logout")
    assert stranger.get(f"/api/v1/orders/lookup/{order_id}").status_code == 403


def test_capture_and_cancel_need_the_checkout_browser(client, make_client, sessions, fake_paypal):
    created = client.post("/api/v1/orders", json={"items": [{"product_id": product_id(sessions), "quantity": 1}]},
                          headers={"Idempotency-Key": "idem-key-cancel"})
    paypal_order_id = created.json()["order_id"]
    other = make_client()
    assert other.post(f"/api/v1/orders/{paypal_order_id}/capture").status_code == 403
    assert other.post(f"/api/v1/orders/{paypal_order_id}/cancel").status_code == 403
    assert client.post(f"/api/v1/orders/{paypal_order_id}/cancel").json()["status"] == "CANCELLED"
    assert client.post(f"/api/v1/orders/{paypal_order_id}/capture").status_code == 409


def test_buyer_sign_in_requires_a_captured_order(client, sessions):
    with sessions() as db:
        db.add(Order(id="uncaptured-1", paypal_order_id="PP-UNCAPTURED", request_key="k-uncaptured", status="CREATED",
                     source="paypal", total_amount=Decimal("10.00"), currency="USD", buyer_email="buyer@example.com"))
        db.commit()
    assert client.post("/api/v1/buyer/login", json={"order_id": "PP-UNCAPTURED", "email": "buyer@example.com"}).status_code == 401
