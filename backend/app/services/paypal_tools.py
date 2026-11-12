"""PayPal operations exposed as tools: the API lab page and the DropBack MCP server.

Every tool calls PayPal through the APIMatic-generated PayPal Server SDK
(`app.services.paypal`). The read tools are shared by the REST API lab and the MCP
server. Refunds are deliberately not an MCP tool: money only moves after a merchant
clicks approve in the console (claims queue or the API lab's manual refund form).
"""

import time
from importlib import metadata
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.paypal import PayPalError, paypal

ROOT = Path(__file__).resolve().parents[3]
APIMATIC_CONTEXT_PLUGIN_URL = "https://chatbotapi.apimatic.io/mcp/plugins"

# SDK operations DropBack calls, with the PayPal REST route each one maps to.
SDK_OPERATIONS = [
    {"sdk_call": "orders.create_order", "method": "POST", "path": "/v2/checkout/orders", "used_for": "Storefront checkout (OrderRequest, PurchaseUnitRequest, Item, Money)"},
    {"sdk_call": "orders.capture_order", "method": "POST", "path": "/v2/checkout/orders/{id}/capture", "used_for": "Capture after buyer approval"},
    {"sdk_call": "orders.get_order", "method": "GET", "path": "/v2/checkout/orders/{id}", "used_for": "API lab / MCP order lookup"},
    {"sdk_call": "payments.get_captured_payment", "method": "GET", "path": "/v2/payments/captures/{capture_id}", "used_for": "API lab / MCP capture lookup"},
    {"sdk_call": "payments.refund_captured_payment", "method": "POST", "path": "/v2/payments/captures/{capture_id}/refund", "used_for": "Approved price-match refunds (RefundRequest)"},
    {"sdk_call": "payments.get_refund", "method": "GET", "path": "/v2/payments/refunds/{refund_id}", "used_for": "Refund status polling"},
    {"sdk_call": "oauth_2.fetch_token", "method": "POST", "path": "/v1/oauth2/token", "used_for": "Client-credentials OAuth managed by the SDK"},
]

TOOLS = [
    {"name": "paypal_check_sandbox_health", "description": "Fetch an OAuth token through the PayPal Server SDK to confirm Sandbox connectivity.",
     "parameters": {"type": "object", "properties": {}}, "mcp": True},
    {"name": "paypal_get_order_details", "description": "Read a PayPal Orders v2 order.",
     "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}, "mcp": True},
    {"name": "paypal_get_capture_status", "description": "Read a captured payment and its refund status.",
     "parameters": {"type": "object", "properties": {"capture_id": {"type": "string"}}, "required": ["capture_id"]}, "mcp": True},
    {"name": "paypal_issue_capture_refund", "description": "Refund part or all of a captured Sandbox payment. Console only; requires a merchant click and an Idempotency-Key.",
     "parameters": {"type": "object", "properties": {"capture_id": {"type": "string"}, "amount": {"type": "string"}, "currency": {"type": "string"}, "note_to_payer": {"type": "string"}},
                    "required": ["capture_id", "amount"]}, "mcp": False},
]


def sdk_version() -> str:
    try:
        return metadata.version("paypal-server-sdk")
    except metadata.PackageNotFoundError:
        return "not installed"


def status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "sdk_package": "paypal-server-sdk",
        "sdk_version": sdk_version(),
        "sdk_generator": "APIMatic",
        "environment": settings.paypal_env,
        "sandbox_ready": settings.paypal_ready,
        "operations": SDK_OPERATIONS,
        "tools": [{k: v for k, v in tool.items() if k != "mcp"} | {"available_over_mcp": tool["mcp"]} for tool in TOOLS],
        "mcp": {
            "enabled": bool(settings.mcp_api_token),
            "path": "/mcp/",
            "transport": "streamable-http",
            "auth": "Authorization: Bearer <MCP_API_TOKEN>",
            "tools": [tool["name"] for tool in TOOLS if tool["mcp"]] + ["dropback_list_claims", "dropback_get_claim"],
        },
        "apimatic_context_plugin": {
            "url": APIMATIC_CONTEXT_PLUGIN_URL,
            "configured_in_repo": (ROOT / ".mcp.json").exists(),
            "purpose": "Gives AI coding agents current PayPal Server SDK docs and samples while developing DropBack.",
        },
    }


async def run_read_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one of the read-only PayPal tools. Returns a result payload; never raises."""
    started = time.perf_counter()

    def done(payload: dict) -> dict:
        return {"tool": name, "latency_ms": round((time.perf_counter() - started) * 1000, 1), **payload}

    try:
        if name == "paypal_check_sandbox_health":
            token = await paypal.access_token()
            return done({"status": "SUCCESS", "environment": get_settings().paypal_env, "oauth_token_active": bool(token), "sdk_version": sdk_version()})
        if name == "paypal_get_order_details":
            order_id = str(arguments.get("order_id", "")).strip()
            if not order_id:
                return done({"status": "ERROR", "error": "order_id is required"})
            data = await paypal.get_order(order_id)
            return done({"status": "SUCCESS", "order_id": order_id, "order_status": data.get("status"), "intent": data.get("intent"), "data": data})
        if name == "paypal_get_capture_status":
            capture_id = str(arguments.get("capture_id", "")).strip()
            if not capture_id:
                return done({"status": "ERROR", "error": "capture_id is required"})
            data = await paypal.get_capture(capture_id)
            return done({"status": "SUCCESS", "capture_id": capture_id, "capture_status": data.get("status"), "data": data})
        return done({"status": "ERROR", "error": f"Unknown tool: {name}", "available_tools": [tool["name"] for tool in TOOLS]})
    except PayPalError as exc:
        return done({"status": "PAYPAL_ERROR", "error": str(exc), "detail": exc.detail})
