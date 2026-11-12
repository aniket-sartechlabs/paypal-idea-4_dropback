"""DropBack MCP server (streamable HTTP at /mcp/).

Lets an MCP client (Claude Code, Cursor, Claude Desktop, ...) read PayPal Sandbox orders
and captures through the PayPal Server SDK and inspect DropBack's price-match claims.

All tools are read-only: issuing a refund needs a merchant's click in the console.
Requests must send `Authorization: Bearer <MCP_API_TOKEN>`; without MCP_API_TOKEN set
the endpoint answers 503.
"""

import hmac
import json
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import database
from app.config import get_settings
from app.models.entities import Decision, Order, PriceDrop, Refund
from app.serializers import decision_dict
from app.services import paypal_tools

CLAIM_FIELDS = ("id", "status", "decision", "buyer_name", "product_name", "sku", "quantity", "purchase_price", "competitor_name",
                "competitor_price", "refund_amount", "return_probability", "estimated_return_cost", "estimated_savings",
                "within_window", "paypal_order_id", "refund_status", "paypal_refund_id", "created_at")


def _claims(where=None, limit: int = 20) -> list[dict]:
    with database.SessionLocal() as db:
        query = select(Decision).options(
            joinedload(Decision.order).joinedload(Order.items), joinedload(Decision.capture),
            joinedload(Decision.price_drop).joinedload(PriceDrop.product)).order_by(Decision.created_at.desc()).limit(limit)
        if where is not None:
            query = query.where(where)
        rows = db.scalars(query).unique().all()
        refunds = {r.decision_id: r for r in db.scalars(select(Refund).where(Refund.decision_id.in_([d.id for d in rows]))).all()} if rows else {}
        return [decision_dict(row, refunds.get(row.id)) for row in rows]


def build_mcp() -> FastMCP:
    mcp = FastMCP(
        "dropback",
        instructions="DropBack price-protection data and read-only PayPal Sandbox lookups via the PayPal Server SDK. Refunds are not available over MCP.",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        # Requests are authenticated with a bearer token, so Host-header pinning is not needed.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    async def paypal_check_sandbox_health() -> dict[str, Any]:
        """Confirm the PayPal Server SDK can obtain an OAuth token for the configured environment."""
        return await paypal_tools.run_read_tool("paypal_check_sandbox_health", {})

    @mcp.tool()
    async def paypal_get_order_details(order_id: str) -> dict[str, Any]:
        """Read a PayPal Orders v2 order by its PayPal order ID."""
        return await paypal_tools.run_read_tool("paypal_get_order_details", {"order_id": order_id})

    @mcp.tool()
    async def paypal_get_capture_status(capture_id: str) -> dict[str, Any]:
        """Read a captured PayPal payment, including its refund status."""
        return await paypal_tools.run_read_tool("paypal_get_capture_status", {"capture_id": capture_id})

    @mcp.tool()
    def dropback_list_claims(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """List recent price-match claims. Optional status: PENDING_REVIEW, REFUNDED, REJECTED, SKIPPED, REFUND_FAILED."""
        rows = _claims(Decision.status == status.upper() if status else None, max(1, min(limit, 100)))
        return [{key: row.get(key) for key in CLAIM_FIELDS} for row in rows]

    @mcp.tool()
    def dropback_get_claim(claim_id: str) -> dict[str, Any]:
        """Full case report for one claim: evidence, return-cost breakdown, AI reasoning, and refund status."""
        rows = _claims(Decision.id == claim_id, 1)
        if not rows:
            return {"error": f"Claim {claim_id} not found."}
        return json.loads(json.dumps(rows[0], default=str))

    return mcp


class BearerProtectedMCP:
    """ASGI wrapper: checks the bearer token, then forwards to the current MCP app."""

    def __init__(self, get_app: Callable[[], Any]):
        self.get_app = get_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return
        token = get_settings().mcp_api_token
        if not token:
            return await _json(send, 503, {"detail": "The DropBack MCP endpoint is disabled. Set MCP_API_TOKEN to enable it."})
        auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
        if not hmac.compare_digest(auth.encode(), f"Bearer {token}".encode()):
            return await _json(send, 401, {"detail": "Missing or invalid bearer token."}, {"www-authenticate": "Bearer"})
        app = self.get_app()
        if app is None:
            return await _json(send, 503, {"detail": "MCP server is starting."})
        await app(scope, receive, send)


async def _json(send, status: int, body: dict, extra_headers: dict | None = None) -> None:
    payload = json.dumps(body).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in (extra_headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
