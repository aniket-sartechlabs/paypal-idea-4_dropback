import base64
import time
from typing import Any

import httpx

from app.config import get_settings


class PayPalError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class PayPalClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _ensure_configured(self) -> None:
        if not self.settings.paypal_ready:
            raise PayPalError("PayPal is not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET.", 503)
        if self.settings.is_production and "sandbox" in self.settings.paypal_base_url.lower():
            raise PayPalError("Production is configured with a sandbox PayPal endpoint.", 503)
        if not self.settings.is_production and "sandbox" not in self.settings.paypal_base_url.lower():
            raise PayPalError("Development checkout is restricted to the PayPal sandbox.", 503)

    async def _access_token(self) -> str:
        self._ensure_configured()
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        client = httpx.AsyncClient(timeout=15)
        try:
            response = await client.post(
                f"{self.settings.paypal_base_url.rstrip('/')}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self.settings.paypal_client_id, self.settings.paypal_client_secret),
                headers={"Accept": "application/json", "Accept-Language": "en_US"},
            )
        except httpx.HTTPError as exc:
            raise PayPalError("PayPal authentication could not be reached.") from exc
        finally:
            await client.aclose()
        if response.is_error:
            raise PayPalError("PayPal authentication failed.", 502, _safe_error(response))
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 300))
        return self._token

    async def request(self, method: str, path: str, *, request_id: str | None = None, json: dict | None = None) -> dict:
        token = await self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                response = await client.request(method, f"{self.settings.paypal_base_url.rstrip('/')}{path}", headers=headers, json=json)
            except httpx.HTTPError as exc:
                raise PayPalError("PayPal could not be reached. Retry this operation in a moment.") from exc
        if response.is_error:
            raise PayPalError("PayPal rejected the request.", 502, _safe_error(response))
        return response.json() if response.content else {}

    async def create_order(self, order_id: str, request_id: str, items: list[dict], total: str, currency: str, brand: str) -> dict:
        paypal_items = []
        for item in items:
            paypal_items.append({
                "name": item["name"][:127],
                "sku": item["sku"][:127],
                "unit_amount": {"currency_code": currency, "value": item["unit_price"]},
                "quantity": str(item["quantity"]),
                "category": "PHYSICAL_GOODS",
            })
        body = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": order_id,
                "description": f"{brand} order {order_id[:8]}",
                "amount": {"currency_code": currency, "value": total,
                           "breakdown": {"item_total": {"currency_code": currency, "value": total}}},
                "items": paypal_items,
            }],
            "application_context": {
                "brand_name": brand[:127], "landing_page": "NO_PREFERENCE", "user_action": "PAY_NOW",
                "return_url": f"{self.settings.app_base_url.rstrip('/')}/checkout/return",
                "cancel_url": f"{self.settings.app_base_url.rstrip('/')}/checkout/cancel",
            },
        }
        return await self.request("POST", "/v2/checkout/orders", request_id=request_id, json=body)

    async def access_token(self) -> str:
        return await self._access_token()

    async def get_order(self, paypal_order_id: str) -> dict:
        return await self.request("GET", f"/v2/checkout/orders/{paypal_order_id}")

    async def get_capture(self, paypal_capture_id: str) -> dict:
        return await self.request("GET", f"/v2/payments/captures/{paypal_capture_id}")

    async def capture_order(self, paypal_order_id: str, request_id: str) -> dict:
        return await self.request("POST", f"/v2/checkout/orders/{paypal_order_id}/capture", request_id=request_id, json={})

    async def refund_capture(self, paypal_capture_id: str, request_id: str, amount: str, currency: str, note: str) -> dict:
        body = {"amount": {"value": amount, "currency_code": currency}, "note_to_payer": note[:255]}
        return await self.request("POST", f"/v2/payments/captures/{paypal_capture_id}/refund", request_id=request_id, json=body)

    async def get_refund(self, paypal_refund_id: str) -> dict:
        return await self.request("GET", f"/v2/payments/refunds/{paypal_refund_id}")

    async def verify_webhook(self, headers: dict[str, str], event: dict) -> bool:
        if not self.settings.paypal_webhook_id:
            return False
        verification = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": self.settings.paypal_webhook_id,
            "webhook_event": event,
        }
        result = await self.request("POST", "/v1/notifications/verify-webhook-signature", json=verification)
        return result.get("verification_status") == "SUCCESS"


def _safe_error(response: httpx.Response) -> dict:
    try:
        payload = response.json()
        return {"name": payload.get("name"), "message": payload.get("message"), "debug_id": payload.get("debug_id")}
    except ValueError:
        return {"status_code": response.status_code}


paypal = PayPalClient()
