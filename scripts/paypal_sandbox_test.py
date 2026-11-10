#!/usr/bin/env python3
"""
DropBack — PayPal Sandbox Integration Test Script
Tests the full order lifecycle: OAuth → Create → Retrieve → (manual approve) → Capture → Refund
"""

import os
import sys
import json
import time
import uuid
import requests
from datetime import datetime, timezone

# ── Configuration ──────────────────────────────────────────────────────────
PAYPAL_BASE_URL = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "BAAIAAGNMwCFLL4tNSGw35IFdLHpuz0mIjPgazNV4dR6QWoxZII2p261x7zyzfvbJW6RDbjPB8FmUo2c2U")
CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "EDnQSKkq1qDkT9WBYHqyn7WsKR6qcCdXKoYf0hdzr8rpqaJVBkoa1OiPLgqAyFLlKWv0hwGV7WoiW72t")

results = {}

def log(step, msg, data=None):
    print(f"\n{'='*60}")
    print(f"STEP {step}: {msg}")
    print(f"{'='*60}")
    if data:
        print(json.dumps(data, indent=2))


# ── Step 1: OAuth Token ──────────────────────────────────────────────────
def get_access_token():
    log(1, "OAuth 2.0 Token Generation")
    resp = requests.post(
        f"{PAYPAL_BASE_URL}/v1/oauth2/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
    )
    data = resp.json()
    results["oauth"] = {
        "status_code": resp.status_code,
        "token_type": data.get("token_type"),
        "expires_in": data.get("expires_in"),
        "scope_includes_refund": "services/payments/refund" in data.get("scope", ""),
        "app_id": data.get("app_id"),
    }
    print(f"  Status: {resp.status_code}")
    print(f"  Token Type: {data.get('token_type')}")
    print(f"  Expires In: {data.get('expires_in')}s ({data.get('expires_in', 0) / 3600:.1f} hours)")
    print(f"  Refund scope: {'YES' if results['oauth']['scope_includes_refund'] else 'NO'}")
    print(f"  App ID: {data.get('app_id')}")
    assert resp.status_code == 200, f"OAuth failed: {data}"
    return data["access_token"]


# ── Step 2: Create Order with item details ────────────────────────────────
def create_order(token):
    log(2, "Create Sandbox Order (Espresso Machine $200)")
    idempotency_key = f"dropback-order-{uuid.uuid4()}"
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": f"db-ref-{uuid.uuid4().hex[:8]}",
                "description": "Premium Espresso Machine - DropBack Test",
                "soft_descriptor": "DROPBACK",
                "amount": {
                    "currency_code": "USD",
                    "value": "200.00",
                    "breakdown": {
                        "item_total": {"currency_code": "USD", "value": "200.00"}
                    },
                },
                "items": [
                    {
                        "name": "Premium Espresso Machine",
                        "description": "DeLonghi La Specialista Arte",
                        "sku": "ESPRESSO-DLG-001",
                        "unit_amount": {"currency_code": "USD", "value": "200.00"},
                        "quantity": "1",
                        "category": "PHYSICAL_GOODS",
                    }
                ],
            }
        ],
        "application_context": {
            "brand_name": "DropBack Merchant Demo",
            "landing_page": "NO_PREFERENCE",
            "user_action": "PAY_NOW",
            "return_url": "http://localhost:5173/checkout/return",
            "cancel_url": "http://localhost:5173/checkout/cancel",
        },
    }

    resp = requests.post(
        f"{PAYPAL_BASE_URL}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": idempotency_key,
        },
        json=payload,
    )
    data = resp.json()
    results["create_order"] = {
        "status_code": resp.status_code,
        "order_id": data.get("id"),
        "order_status": data.get("status"),
        "idempotency_key": idempotency_key,
    }
    print(f"  Status: {resp.status_code}")
    print(f"  Order ID: {data.get('id')}")
    print(f"  Order Status: {data.get('status')}")

    # Extract approval URL
    approve_link = next((l for l in data.get("links", []) if l["rel"] == "approve"), None)
    if approve_link:
        print(f"\n  ★ BUYER APPROVAL URL: {approve_link['href']}")
        results["create_order"]["approve_url"] = approve_link["href"]

    assert resp.status_code == 201, f"Order creation failed: {data}"
    return data["id"]


# ── Step 3: Retrieve Order ────────────────────────────────────────────────
def get_order(token, order_id):
    log(3, f"Retrieve Order {order_id}")
    resp = requests.get(
        f"{PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    data = resp.json()
    results["retrieve_order"] = {
        "status_code": resp.status_code,
        "order_status": data.get("status"),
        "amount": data.get("purchase_units", [{}])[0].get("amount", {}),
        "items_count": len(data.get("purchase_units", [{}])[0].get("items", [])),
        "payee": data.get("purchase_units", [{}])[0].get("payee", {}),
    }
    print(f"  Status: {resp.status_code}")
    print(f"  Order Status: {data.get('status')}")
    print(f"  Payee: {results['retrieve_order']['payee']}")
    print(f"  Amount: {results['retrieve_order']['amount']}")
    assert resp.status_code == 200, f"Order retrieval failed: {data}"
    return data


# ── Step 4: Capture Order ─────────────────────────────────────────────────
def capture_order(token, order_id):
    log(4, f"Capture Order {order_id}")
    resp = requests.post(
        f"{PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": f"capture-{uuid.uuid4()}",
        },
    )
    data = resp.json()

    capture_id = None
    capture_status = None
    if data.get("purchase_units"):
        captures = data["purchase_units"][0].get("payments", {}).get("captures", [])
        if captures:
            capture_id = captures[0].get("id")
            capture_status = captures[0].get("status")

    results["capture"] = {
        "status_code": resp.status_code,
        "order_status": data.get("status"),
        "capture_id": capture_id,
        "capture_status": capture_status,
    }
    print(f"  HTTP Status: {resp.status_code}")
    print(f"  Order Status: {data.get('status')}")
    print(f"  Capture ID: {capture_id}")
    print(f"  Capture Status: {capture_status}")

    if resp.status_code != 201:
        print(f"  ⚠ Capture failed (order may need buyer approval first)")
        print(f"  Response: {json.dumps(data, indent=2)}")

    return data, capture_id


# ── Step 5: Partial Refund ────────────────────────────────────────────────
def partial_refund(token, capture_id, refund_amount="40.00"):
    log(5, f"Partial Refund ${refund_amount} on capture {capture_id}")
    resp = requests.post(
        f"{PAYPAL_BASE_URL}/v2/payments/captures/{capture_id}/refund",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": f"refund-{uuid.uuid4()}",
        },
        json={
            "amount": {
                "value": refund_amount,
                "currency_code": "USD",
            },
            "note_to_payer": "DropBack Price Protection: We detected a price drop and are refunding you the difference!",
        },
    )
    data = resp.json()
    results["refund"] = {
        "status_code": resp.status_code,
        "refund_id": data.get("id"),
        "refund_status": data.get("status"),
        "refund_amount": data.get("amount"),
    }
    print(f"  HTTP Status: {resp.status_code}")
    print(f"  Refund ID: {data.get('id')}")
    print(f"  Refund Status: {data.get('status')}")
    print(f"  Refund Amount: {data.get('amount')}")

    if resp.status_code not in (200, 201):
        print(f"  Response: {json.dumps(data, indent=2)}")

    return data


# ── Step 6: Verify Refund ─────────────────────────────────────────────────
def verify_refund(token, refund_id):
    log(6, f"Verify Refund {refund_id}")
    resp = requests.get(
        f"{PAYPAL_BASE_URL}/v2/payments/refunds/{refund_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    data = resp.json()
    results["verify_refund"] = {
        "status_code": resp.status_code,
        "refund_status": data.get("status"),
    }
    print(f"  HTTP Status: {resp.status_code}")
    print(f"  Refund Status: {data.get('status')}")
    print(f"  Full Response: {json.dumps(data, indent=2)}")
    return data


# ── Step 7: Test Webhook creation endpoint ────────────────────────────────
def test_webhooks(token):
    log(7, "Test Webhook Creation Endpoint")

    # List existing webhooks
    resp = requests.get(
        f"{PAYPAL_BASE_URL}/v1/notifications/webhooks",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    data = resp.json()
    results["webhooks_list"] = {
        "status_code": resp.status_code,
        "existing_webhooks": len(data.get("webhooks", [])),
    }
    print(f"  List Status: {resp.status_code}")
    print(f"  Existing webhooks: {len(data.get('webhooks', []))}")
    for wh in data.get("webhooks", []):
        print(f"    - {wh.get('id')}: {wh.get('url')}")
        for et in wh.get("event_types", []):
            print(f"      Event: {et.get('name')}")

    # List available event types
    resp2 = requests.get(
        f"{PAYPAL_BASE_URL}/v1/notifications/webhooks-event-types",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    event_data = resp2.json()
    refund_events = [
        et for et in event_data.get("event_types", [])
        if "REFUND" in et.get("name", "") or "CAPTURE" in et.get("name", "")
    ]
    results["webhook_events"] = {
        "total_event_types": len(event_data.get("event_types", [])),
        "capture_refund_events": [et["name"] for et in refund_events],
    }
    print(f"\n  Total available event types: {results['webhook_events']['total_event_types']}")
    print(f"  Capture/Refund related events:")
    for name in results["webhook_events"]["capture_refund_events"]:
        print(f"    - {name}")

    return data


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "create"

    if mode == "create":
        # Phase 1: Create order and show approval URL
        token = get_access_token()
        order_id = create_order(token)
        get_order(token, order_id)
        test_webhooks(token)

        print(f"\n{'='*60}")
        print("PHASE 1 COMPLETE — ORDER CREATED")
        print(f"{'='*60}")
        print(f"Order ID: {order_id}")
        print(f"Approve URL: {results['create_order'].get('approve_url', 'N/A')}")
        print(f"\nTo approve, open the URL in a browser and log in with")
        print(f"sandbox buyer credentials, then run:")
        print(f"  python3 {sys.argv[0]} capture {order_id}")

    elif mode == "capture" and len(sys.argv) > 2:
        # Phase 2: Capture after buyer approval
        order_id = sys.argv[2]
        token = get_access_token()
        order_data = get_order(token, order_id)

        if order_data.get("status") != "APPROVED":
            print(f"\n⚠ Order status is '{order_data.get('status')}', not 'APPROVED'.")
            print("  Buyer must approve the order first via the checkout URL.")
            if order_data.get("status") == "CREATED":
                approve_link = next(
                    (l for l in order_data.get("links", []) if l["rel"] == "approve"), None
                )
                if approve_link:
                    print(f"  Approve URL: {approve_link['href']}")
            return

        capture_data, capture_id = capture_order(token, order_id)
        if capture_id:
            print(f"\n  ★ Capture successful! Run refund with:")
            print(f"  python3 {sys.argv[0]} refund {capture_id}")

    elif mode == "refund" and len(sys.argv) > 2:
        # Phase 3: Partial refund
        capture_id = sys.argv[2]
        refund_amount = sys.argv[3] if len(sys.argv) > 3 else "40.00"
        token = get_access_token()
        refund_data = partial_refund(token, capture_id, refund_amount)
        refund_id = refund_data.get("id")
        if refund_id:
            verify_refund(token, refund_id)

    elif mode == "full-report":
        # Just run what we can without buyer interaction
        token = get_access_token()
        order_id = create_order(token)
        get_order(token, order_id)
        test_webhooks(token)

    else:
        print("Usage:")
        print(f"  python3 {sys.argv[0]} create          — Create order + show approval URL")
        print(f"  python3 {sys.argv[0]} capture ORDER_ID — Capture after buyer approval")
        print(f"  python3 {sys.argv[0]} refund CAPTURE_ID [AMOUNT] — Issue partial refund")
        print(f"  python3 {sys.argv[0]} full-report      — Run full report (no capture)")

    # Print summary
    print(f"\n{'='*60}")
    print("TEST RESULTS SUMMARY")
    print(f"{'='*60}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
