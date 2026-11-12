from app.config import get_settings
from conftest import buy, merchant_login


def refund(client, capture_id, amount, key):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/api/v1/paypal-tools/invoke", headers=headers,
                       json={"tool": "paypal_issue_capture_refund", "arguments": {"capture_id": capture_id, "amount": amount, "currency": "USD"}})


def test_tools_status_reports_sdk_and_mcp(client):
    merchant_login(client)
    status = client.get("/api/v1/paypal-tools/status").json()
    assert status["sdk_package"] == "paypal-server-sdk" and status["sdk_version"] != "not installed"
    assert any(op["sdk_call"] == "payments.refund_captured_payment" for op in status["operations"])
    assert "paypal_issue_capture_refund" not in status["mcp"]["tools"]


def test_manual_refunds_of_the_same_amount_are_separate_requests(client, sessions, fake_paypal):
    capture_id = buy(client, sessions)["capture_id"]
    merchant_login(client)
    assert refund(client, capture_id, "5.00", None).status_code == 400

    first = refund(client, capture_id, "5.00", "manual-key-0001")
    second = refund(client, capture_id, "5.00", "manual-key-0002")
    assert first.status_code == 200 and second.status_code == 200
    assert [call["request_id"] for call in fake_paypal["refund"]] == ["manual-manual-key-0001", "manual-manual-key-0002"]

    replay = refund(client, capture_id, "5.00", "manual-key-0001")
    assert replay.json()["replayed"] is True
    assert len(fake_paypal["refund"]) == 2
    assert refund(client, capture_id, "6.00", "manual-key-0001").status_code == 409


def test_manual_refund_respects_per_order_cap(client, sessions, fake_paypal):
    capture_id = buy(client, sessions)["capture_id"]
    merchant_login(client)
    response = refund(client, capture_id, "150.00", "manual-key-cap1")
    assert response.status_code == 409
    assert fake_paypal["refund"] == []


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def mcp_call(client, method, params=None, token=None, call_id=1):
    headers = dict(MCP_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": call_id, "method": method, "params": params or {}})


def test_mcp_endpoint_is_disabled_without_a_token(client):
    assert mcp_call(client, "tools/list").status_code == 503


def test_mcp_lists_read_only_tools_with_a_valid_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "mcp_api_token", "test-mcp-token")
    assert mcp_call(client, "tools/list", token="wrong").status_code == 401
    init = mcp_call(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                            "clientInfo": {"name": "pytest", "version": "1"}}, token="test-mcp-token")
    assert init.status_code == 200, init.text
    tools = mcp_call(client, "tools/list", token="test-mcp-token", call_id=2)
    names = {tool["name"] for tool in tools.json()["result"]["tools"]}
    assert {"paypal_get_order_details", "dropback_list_claims", "dropback_get_claim"} <= names
    assert "paypal_issue_capture_refund" not in names
    listed = mcp_call(client, "tools/call", {"name": "dropback_list_claims", "arguments": {}}, token="test-mcp-token", call_id=3)
    assert listed.status_code == 200 and listed.json()["result"]["isError"] is False
