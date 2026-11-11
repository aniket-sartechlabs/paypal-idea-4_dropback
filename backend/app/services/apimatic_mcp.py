"""DropBack's MCP bridge, grounded by the repository APIMatic PayPal context manifest.

The APIMatic Context Plugin is the source of the OpenAPI contracts and tool schemas.
This server-side bridge executes the supported read and refund operations against
PayPal Sandbox; it is not an APIMatic-hosted runtime service.
"""

import hashlib
import json
import logging
import time
from typing import Any
from decimal import Decimal
from pathlib import Path

import httpx

from app.config import get_settings
from app.services.paypal import paypal, PayPalError

log = logging.getLogger("dropback.apimatic")

ROOT = Path(__file__).resolve().parents[3]
CONTEXT_PLUGIN_PATH = ROOT / ".context-plugins" / "paypal.json"
CONTEXT_PLUGIN = json.loads(CONTEXT_PLUGIN_PATH.read_text(encoding="utf-8"))
APIMATIC_PAYPAL_SCHEMA_VERSION = str(CONTEXT_PLUGIN.get("version", "unknown"))
APIMATIC_PLUGIN_NAME = "apimatic-paypal-orders-v2"
OPENAPI_PATHS = CONTEXT_PLUGIN.get("openapi_spec", {}).get("paths", {})
APIMATIC_API_SPECS: dict[str, Any] = {
    "plugin": {
        "name": APIMATIC_PLUGIN_NAME,
        "version": APIMATIC_PAYPAL_SCHEMA_VERSION,
        "author": "APIMatic Context Plugins",
        "description": CONTEXT_PLUGIN.get("description", ""),
        "doc_url": CONTEXT_PLUGIN.get("docs"),
    },
    "contracts": {
        operation.get("operationId", f"{method}_{path}"): {
            "method": method.upper(),
            "path": path,
            "summary": operation.get("summary", ""),
        }
        for path, path_item in OPENAPI_PATHS.items()
        for method, operation in path_item.items()
        if isinstance(operation, dict) and method.lower() in {"get", "post", "patch", "delete"}
    },
    "mcp_tools": [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        }
        for tool in CONTEXT_PLUGIN.get("mcp_tools", [])
    ],
}


class APIMaticPayPalMCP:
    """MCP-style tool bridge using schemas from the APIMatic context manifest."""

    def __init__(self):
        self.settings = get_settings()

    def get_plugin_manifest(self) -> dict[str, Any]:
        """Return the loaded context manifest and its PayPal API contracts."""
        has_credentials = bool(self.settings.paypal_client_id and self.settings.paypal_client_secret)
        return {
            "apimatic_enabled": True,
            "version": APIMATIC_PAYPAL_SCHEMA_VERSION,
            "plugin_name": APIMATIC_PLUGIN_NAME,
            "context_plugin_name": CONTEXT_PLUGIN.get("name"),
            "contract_source": ".context-plugins/paypal.json",
            "environment": self.settings.paypal_env,
            "sandbox_ready": has_credentials,
            "tools_count": len(APIMATIC_API_SPECS["mcp_tools"]),
            "tools": APIMATIC_API_SPECS["mcp_tools"],
            "schemas": APIMATIC_API_SPECS["contracts"],
            "manifest_loaded": CONTEXT_PLUGIN_PATH.exists(),
        }

    async def invoke_mcp_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute an APIMatic MCP tool call against the PayPal Developer Sandbox."""
        start_time = time.time()
        try:
            if tool_name == "paypal_check_sandbox_health":
                token = await paypal.access_token()
                latency_ms = round((time.time() - start_time) * 1000, 2)
                return {
                    "tool": tool_name,
                    "status": "SUCCESS",
                    "latency_ms": latency_ms,
                    "environment": self.settings.paypal_env,
                    "oauth_token_active": bool(token),
                    "apimatic_contract_status": "LOADED_FROM_CONTEXT_MANIFEST",
                }

            elif tool_name == "paypal_get_order_details":
                order_id = arguments.get("order_id", "").strip()
                if not order_id:
                    return {"tool": tool_name, "status": "ERROR", "error": "order_id parameter is required"}
                data = await paypal.get_order(order_id)
                latency_ms = round((time.time() - start_time) * 1000, 2)
                return {
                    "tool": tool_name,
                    "status": "SUCCESS",
                    "latency_ms": latency_ms,
                    "order_id": order_id,
                    "order_status": data.get("status"),
                    "intent": data.get("intent"),
                    "data": data,
                }

            elif tool_name == "paypal_get_capture_status":
                capture_id = arguments.get("capture_id", "").strip()
                if not capture_id:
                    return {"tool": tool_name, "status": "ERROR", "error": "capture_id parameter is required"}
                data = await paypal.get_capture(capture_id)
                latency_ms = round((time.time() - start_time) * 1000, 2)
                return {
                    "tool": tool_name,
                    "status": "SUCCESS",
                    "latency_ms": latency_ms,
                    "capture_id": capture_id,
                    "capture_status": data.get("status"),
                    "data": data,
                }

            elif tool_name == "paypal_issue_capture_refund":
                capture_id = arguments.get("capture_id", "").strip()
                amount = arguments.get("amount")
                currency = arguments.get("currency", "USD")
                note = arguments.get("note_to_payer", "DropBack Price Protection Refund")
                if not capture_id or not amount:
                    return {"tool": tool_name, "status": "ERROR", "error": "capture_id and amount are required"}
                
                amount_decimal = Decimal(str(amount)).quantize(Decimal("0.01"))
                if amount_decimal <= 0:
                    return {"tool": tool_name, "status": "ERROR", "error": "amount must be greater than zero"}
                req_digest = hashlib.sha256(f"{capture_id}:{currency.upper()}:{amount_decimal:.2f}".encode()).hexdigest()[:32]
                req_id = f"db-{req_digest}"
                refund_resp = await paypal.refund_capture(
                    paypal_capture_id=capture_id,
                    request_id=req_id,
                    amount=f"{amount_decimal:.2f}",
                    currency=currency.upper(),
                    note=note,
                )
                latency_ms = round((time.time() - start_time) * 1000, 2)
                refund_status = refund_resp.get("status")
                ok = refund_status in {"COMPLETED", "PENDING"}
                return {
                    "tool": tool_name,
                    "status": "SUCCESS" if ok else "PAYPAL_ERROR",
                    "latency_ms": latency_ms,
                    "refund_id": refund_resp.get("id"),
                    "refund_status": refund_status,
                    "amount": amount,
                    "currency": currency,
                    "contract_source": ".context-plugins/paypal.json",
                    **({} if ok else {"error": f"PayPal returned refund status {refund_status or 'unknown'}."}),
                }

            else:
                return {
                    "tool": tool_name,
                    "status": "ERROR",
                    "error": f"Unknown APIMatic MCP tool: {tool_name}",
                    "available_tools": [t["name"] for t in APIMATIC_API_SPECS["mcp_tools"]],
                }

        except PayPalError as exc:
            latency_ms = round((time.time() - start_time) * 1000, 2)
            return {
                "tool": tool_name,
                "status": "PAYPAL_ERROR",
                "latency_ms": latency_ms,
                "error": str(exc),
                "status_code": exc.status_code,
            }
        except Exception as exc:
            latency_ms = round((time.time() - start_time) * 1000, 2)
            return {
                "tool": tool_name,
                "status": "EXCEPTION",
                "latency_ms": latency_ms,
                "error": str(exc),
            }


apimatic_mcp = APIMaticPayPalMCP()
