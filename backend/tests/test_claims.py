from datetime import timedelta

from app.models.entities import Capture, Order, Product, now_utc
from app.services import agent
from app.services.paypal import PayPalError, paypal
from conftest import buy, merchant_login


def submit_claim(client, order_id):
    check = client.post("/api/v1/claims/check-price", json={"order_id": order_id})
    assert check.status_code == 200, check.text
    assert check.json()["price_drop_detected"] is True
    claim = client.post("/api/v1/claims/submit", json={"order_id": order_id, "price_drop_id": check.json()["price_drop_id"],
                                                       "customer_notes": "Found it cheaper."})
    assert claim.status_code == 200, claim.text
    return claim.json()


def test_claim_refund_counts_quantity_and_uses_rule_score(client, sessions, fake_paypal, fake_channel3):
    order_id = buy(client, sessions, quantity=2)["internal_order_id"]
    claim = submit_claim(client, order_id)

    # Two units bought at $398, best live offer $348: $100 difference (per-order cap is also $100).
    assert claim["status"] == "PENDING_REVIEW"
    assert claim["quantity"] == 2
    assert claim["refund_amount"] == 100.0
    assert claim["competitor_name"] == "bestbuy.com"
    baseline, _ = agent.deterministic_score("Electronics", 50 * 2 / (398 * 2) * 100, 0)
    assert abs(claim["return_probability"] - baseline) < 1e-4
    assert claim["analysis_report"]["provider"] == "rules"
    assert claim["analysis_report"]["financial_breakdown"]["quantity"] == 2


def test_buyer_price_check_does_not_change_merchant_catalog(client, sessions, fake_paypal, fake_channel3):
    order_id = buy(client, sessions)["internal_order_id"]
    with sessions() as db:
        before = db.query(Product).filter(Product.sku == "SONY-WH1000XM5-BLK").one()
        before_state = (before.last_market_price, before.competitor_name, before.competitor_url)
    client.post("/api/v1/claims/check-price", json={"order_id": order_id})
    with sessions() as db:
        after = db.query(Product).filter(Product.sku == "SONY-WH1000XM5-BLK").one()
        assert (after.last_market_price, after.competitor_name, after.competitor_url) == before_state


def test_claim_window_uses_merchant_setting(client, sessions, fake_paypal, fake_channel3):
    order_id = buy(client, sessions)["internal_order_id"]
    with sessions() as db:
        db.get(Order, order_id).captured_at = now_utc() - timedelta(days=3)
        db.commit()
    merchant_login(client)
    client.patch("/api/v1/settings", json={"price_protection_window_days": 2})
    check = client.post("/api/v1/claims/check-price", json={"order_id": order_id}).json()
    assert check["protection_window_days"] == 2 and check["protection_active"] is False
    response = client.post("/api/v1/claims/submit", json={"order_id": order_id, "price_drop_id": check["price_drop_id"]})
    assert response.status_code == 409
    assert "2-day" in response.json()["detail"]


def test_merchant_approval_refunds_through_paypal(client, sessions, fake_paypal, fake_channel3):
    order_id = buy(client, sessions)["internal_order_id"]
    claim = submit_claim(client, order_id)
    assert client.post(f"/api/v1/claims/{claim['id']}/resolve", json={"action": "approve"}).status_code == 401

    merchant_login(client)
    too_much = client.post(f"/api/v1/claims/{claim['id']}/resolve", json={"action": "approve", "refund_amount": "75.00"})
    assert too_much.status_code == 422
    resolved = client.post(f"/api/v1/claims/{claim['id']}/resolve", json={"action": "approve", "refund_amount": "40.00"})
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "REFUNDED" and body["refund_status"] == "COMPLETED"
    assert fake_paypal["refund"] == [{"capture_id": fake_paypal["refund"][0]["capture_id"], "request_id": f"refund-{claim['id']}", "amount": "40.00"}]
    with sessions() as db:
        assert float(db.query(Capture).one().refunded_amount) == 40.0
    # The buyer sees the result.
    assert client.get(f"/api/v1/orders/lookup/{order_id}").json()["claim"]["refund_status"] == "COMPLETED"


def test_network_failure_keeps_refund_pending_and_retry_reuses_request_id(client, sessions, fake_paypal, fake_channel3, monkeypatch):
    claim = submit_claim(client, buy(client, sessions)["internal_order_id"])
    merchant_login(client)
    original = paypal.refund_capture
    attempts = []

    async def flaky(capture_id, request_id, amount, currency, note):
        attempts.append(request_id)
        if len(attempts) == 1:
            raise PayPalError("PayPal could not be reached.", 502, retryable=True)
        return await original(capture_id, request_id, amount, currency, note)

    monkeypatch.setattr(paypal, "refund_capture", flaky)
    first = client.post(f"/api/v1/claims/{claim['id']}/resolve", json={"action": "approve"})
    assert first.status_code == 502
    decisions = client.get("/api/v1/agent/decisions").json()
    assert decisions[0]["status"] == "REFUND_PENDING"
    second = client.post(f"/api/v1/claims/{claim['id']}/resolve", json={"action": "approve"})
    assert second.status_code == 200 and second.json()["status"] == "REFUNDED"
    assert attempts[0] == attempts[1]


def test_rejected_refund_can_be_retried_with_a_new_request_id(client, sessions, fake_paypal, fake_channel3, monkeypatch):
    claim = submit_claim(client, buy(client, sessions)["internal_order_id"])
    merchant_login(client)
    original = paypal.refund_capture
    attempts = []

    async def rejecting(capture_id, request_id, amount, currency, note):
        attempts.append(request_id)
        if len(attempts) == 1:
            raise PayPalError("PayPal refund failed: rejected", 502, retryable=False)
        return await original(capture_id, request_id, amount, currency, note)

    monkeypatch.setattr(paypal, "refund_capture", rejecting)
    assert client.post(f"/api/v1/claims/{claim['id']}/resolve", json={"action": "approve"}).status_code == 502
    assert client.get("/api/v1/agent/decisions").json()[0]["status"] == "REFUND_FAILED"
    retry = client.post(f"/api/v1/claims/{claim['id']}/resolve", json={"action": "approve"})
    assert retry.status_code == 200 and retry.json()["status"] == "REFUNDED"
    assert attempts[0] != attempts[1]


def test_merchant_price_drop_scan_evaluates_captured_orders(client, sessions, fake_paypal):
    buy(client, sessions, quantity=1)
    merchant_login(client)
    products = client.get("/api/v1/products").json()
    sony = next(row for row in products if row["sku"] == "SONY-WH1000XM5-BLK")
    drop = client.patch(f"/api/v1/products/{sony['id']}/price", json={"new_price": "350.00"}).json()["price_drop"]
    decisions = client.post(f"/api/v1/price-drops/{drop['id']}/process").json()
    assert len(decisions) == 1
    assert decisions[0]["analysis_report"]["financial_breakdown"]["price_difference"] == 48.0
    assert decisions[0]["status"] in {"PENDING_REVIEW", "SKIPPED"}
