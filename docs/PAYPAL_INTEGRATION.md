# DropBack — PayPal Integration Specification

**Target Environment:** PayPal Sandbox (`https://api-m.sandbox.paypal.com`)
**API Version:** Orders v2, Payments v2 (Captures/Refunds)
**SDK:** PayPal JavaScript SDK v6
**Tested:** 2026-11-10

---

## 1. Endpoints & Methods

| Purpose | Method | Endpoint | Auth | Key Headers |
|---|---|---|---|---|
| OAuth 2.0 Token | `POST` | `/v1/oauth2/token` | Basic Auth (`client_id:secret`) | `Content-Type: application/x-www-form-urlencoded` |
| Create Order | `POST` | `/v2/checkout/orders` | Bearer Token | `Content-Type: application/json`, `PayPal-Request-Id: <UUID>` |
| Retrieve Order | `GET` | `/v2/checkout/orders/{id}` | Bearer Token | `Content-Type: application/json` |
| Capture Order | `POST` | `/v2/checkout/orders/{id}/capture` | Bearer Token | `Content-Type: application/json`, `PayPal-Request-Id: <UUID>` |
| **Partial Refund** | `POST` | `/v2/payments/captures/{capture_id}/refund` | Bearer Token | `Content-Type: application/json`, `PayPal-Request-Id: <UUID>` |
| Get Refund Details | `GET` | `/v2/payments/refunds/{refund_id}` | Bearer Token | `Content-Type: application/json` |
| List Webhooks | `GET` | `/v1/notifications/webhooks` | Bearer Token | `Content-Type: application/json` |
| Create Webhook | `POST` | `/v1/notifications/webhooks` | Bearer Token | `Content-Type: application/json` |
| Verify Webhook Signature | `POST` | `/v1/notifications/verify-webhook-signature` | Bearer Token | `Content-Type: application/json` |
| List Webhook Event Types | `GET` | `/v1/notifications/webhooks-event-types` | Bearer Token | `Content-Type: application/json` |

---

## 2. Authentication & Token Management

### OAuth 2.0 Client Credentials Flow

**Request:**
```
POST /v1/oauth2/token
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
```

**Response (200 OK):**
```json
{
  "scope": "...https://uri.paypal.com/services/payments/refund...",
  "access_token": "A21AALkr...",
  "token_type": "Bearer",
  "app_id": "APP-0E076702VF501574N",
  "expires_in": 32400,
  "nonce": "2026-11-10T08:02:26Z..."
}
```

### Token Caching Strategy
- `expires_in` = 32,400 seconds (9 hours)
- Cache token in memory with a 60-second safety margin
- Refresh when `current_time >= token_acquired_time + expires_in - 60`
- Client secret NEVER leaves the backend

### Verified Scopes (Sandbox)
- ✅ `https://uri.paypal.com/services/payments/refund` — **CRITICAL for DropBack**
- ✅ `https://uri.paypal.com/services/payments/payment/authcapture`
- ✅ `https://uri.paypal.com/services/applications/webhooks`
- ✅ `https://api.paypal.com/v1/payments/.*`
- ❌ Transaction Search API — requires partner-level permissions (NOT_AUTHORIZED)

---

## 3. Order Lifecycle

### A. Create Order (`POST /v2/checkout/orders`)

**Request:**
```json
{
  "intent": "CAPTURE",
  "purchase_units": [
    {
      "reference_id": "db-ref-<uuid>",
      "description": "Premium Espresso Machine - DropBack Test",
      "soft_descriptor": "DROPBACK",
      "amount": {
        "currency_code": "USD",
        "value": "200.00",
        "breakdown": {
          "item_total": { "currency_code": "USD", "value": "200.00" }
        }
      },
      "items": [
        {
          "name": "Premium Espresso Machine",
          "description": "DeLonghi La Specialista Arte",
          "sku": "ESPRESSO-DLG-001",
          "unit_amount": { "currency_code": "USD", "value": "200.00" },
          "quantity": "1",
          "category": "PHYSICAL_GOODS"
        }
      ]
    }
  ],
  "application_context": {
    "brand_name": "DropBack Merchant Demo",
    "landing_page": "NO_PREFERENCE",
    "user_action": "PAY_NOW",
    "return_url": "http://localhost:5173/checkout/return",
    "cancel_url": "http://localhost:5173/checkout/cancel"
  }
}
```

**Response (201 Created):**
```json
{
  "id": "29143304YR052760W",
  "status": "CREATED",
  "links": [
    { "href": "https://api.sandbox.paypal.com/v2/checkout/orders/29143304YR052760W", "rel": "self", "method": "GET" },
    { "href": "https://www.sandbox.paypal.com/checkoutnow?token=29143304YR052760W", "rel": "approve", "method": "GET" },
    { "href": "https://api.sandbox.paypal.com/v2/checkout/orders/29143304YR052760W", "rel": "update", "method": "PATCH" },
    { "href": "https://api.sandbox.paypal.com/v2/checkout/orders/29143304YR052760W/capture", "rel": "capture", "method": "POST" }
  ]
}
```

### B. Retrieve Order (`GET /v2/checkout/orders/{id}`)

**Response (200 OK):**
```json
{
  "id": "29143304YR052760W",
  "intent": "CAPTURE",
  "status": "CREATED",
  "purchase_units": [
    {
      "reference_id": "dropback-test-001",
      "amount": { "currency_code": "USD", "value": "200.00" },
      "payee": {
        "email_address": "sb-oreai53359961@business.example.com",
        "merchant_id": "B5DU7MB92L246",
        "display_data": { "brand_name": "DropBack Merchant Demo" }
      },
      "items": [
        {
          "name": "Premium Espresso Machine",
          "sku": "ESPRESSO-DLG-001",
          "unit_amount": { "currency_code": "USD", "value": "200.00" },
          "quantity": "1",
          "category": "PHYSICAL_GOODS"
        }
      ]
    }
  ],
  "create_time": "2026-11-10T08:02:48Z"
}
```

### C. Buyer Approval

The buyer approves via the PayPal checkout URL or SDK button.
- URL: `https://www.sandbox.paypal.com/checkoutnow?token={order_id}`
- SDK: `onApprove(data)` callback provides `{ orderID: "..." }`
- After approval: order status transitions `CREATED` → `APPROVED`

### D. Capture Order (`POST /v2/checkout/orders/{id}/capture`)

**Response (201 Created):**
```json
{
  "id": "29143304YR052760W",
  "status": "COMPLETED",
  "purchase_units": [
    {
      "reference_id": "dropback-test-001",
      "payments": {
        "captures": [
          {
            "id": "3C0227123A812841J",
            "status": "COMPLETED",
            "amount": { "currency_code": "USD", "value": "200.00" },
            "final_capture": true,
            "seller_protection": { "status": "ELIGIBLE" }
          }
        ]
      }
    }
  ]
}
```

**⚠ Key: The `capture_id` (`3C0227123A812841J`) is needed for refunds.**

---

## 4. Partial Refund — THE CORE DROPBACK OPERATION

### Endpoint: `POST /v2/payments/captures/{capture_id}/refund`

This is the central PayPal API call for DropBack. The merchant issues a partial refund from their own captured payment back to the buyer.

**Request:**
```json
{
  "amount": {
    "value": "40.00",
    "currency_code": "USD"
  },
  "note_to_payer": "DropBack Price Protection: We detected a price drop on your recent purchase and are refunding you the difference!"
}
```

**Headers:**
```
Authorization: Bearer <access_token>
Content-Type: application/json
PayPal-Request-Id: refund-<idempotency_uuid>
```

**Response (201 Created):**
```json
{
  "id": "REFUND_ID_HERE",
  "status": "COMPLETED",
  "amount": { "value": "40.00", "currency_code": "USD" },
  "note_to_payer": "DropBack Price Protection...",
  "links": [
    { "rel": "self", "href": "https://api.sandbox.paypal.com/v2/payments/refunds/REFUND_ID", "method": "GET" },
    { "rel": "up", "href": "https://api.sandbox.paypal.com/v2/payments/captures/CAPTURE_ID", "method": "GET" }
  ]
}
```

### Refund Rules & Constraints
- **Partial refund:** Set `amount.value` to less than the captured amount
- **Full refund:** Omit the `amount` field, or set it to the full captured amount
- **Multiple partial refunds:** You can issue multiple partial refunds against the same capture (total cannot exceed original)
- **Currency must match** the original capture currency
- **`note_to_payer`:** Max 255 characters, shown to buyer in their PayPal notification
- **Refund statuses:** `COMPLETED`, `PENDING`, `CANCELLED`
- **No merchant partner assertion needed:** The merchant's own client credentials are sufficient

### Verify Refund (`GET /v2/payments/refunds/{refund_id}`)

Returns the full refund details including status, amounts, and linked capture.

---

## 5. Webhook Events

### Relevant Events for DropBack

| Event Type | When Fired |
|---|---|
| `PAYMENT.CAPTURE.COMPLETED` | A payment capture is completed (after order approval) |
| `PAYMENT.CAPTURE.REFUNDED` | A captured payment has been refunded |
| `PAYMENT.REFUND.COMPLETED` | A refund is successfully completed |
| `PAYMENT.REFUND.PENDING` | A refund is pending |
| `PAYMENT.REFUND.FAILED` | A refund failed |
| `PAYMENT.REFUND.DENIED` | A refund was denied |
| `PAYMENT.REFUND.CANCELLED` | A refund was cancelled |

### Webhook Signature Verification

```json
POST /v1/notifications/verify-webhook-signature

{
  "auth_algo": "<from header PAYPAL-AUTH-ALGO>",
  "cert_url": "<from header PAYPAL-CERT-URL>",
  "transmission_id": "<from header PAYPAL-TRANSMISSION-ID>",
  "transmission_sig": "<from header PAYPAL-TRANSMISSION-SIG>",
  "transmission_time": "<from header PAYPAL-TRANSMISSION-TIME>",
  "webhook_id": "<your registered webhook ID>",
  "webhook_event": { ...the raw event body... }
}
```

**Response:**
```json
{ "verification_status": "SUCCESS" }
```

---

## 6. Idempotency

- Every mutating call (create order, capture, refund) includes `PayPal-Request-Id: <UUID>`
- If a network timeout occurs, re-sending the same `PayPal-Request-Id` returns the original response
- Pattern: `order-{uuid}`, `capture-{uuid}`, `refund-{uuid}`
- Before retrying, query the resource (`GET /v2/checkout/orders/{id}`) to check current state

---

## 7. Error Handling

### Common Error Responses

| HTTP Status | Error Name | When |
|---|---|---|
| 400 | `INVALID_REQUEST` | Malformed request body |
| 401 | `AUTHENTICATION_FAILURE` | Bad/expired token |
| 403 | `NOT_AUTHORIZED` | Insufficient permissions |
| 404 | `RESOURCE_NOT_FOUND` | Invalid order/capture/refund ID |
| 422 | `UNPROCESSABLE_ENTITY` | Business rule violation (e.g., refund > capture) |
| 429 | Rate limited | Too many requests |
| 500 | `INTERNAL_SERVER_ERROR` | PayPal server error |

### Error Response Structure
```json
{
  "name": "RESOURCE_NOT_FOUND",
  "message": "The specified resource does not exist.",
  "debug_id": "ca5838a6738e0",
  "details": [
    {
      "issue": "INVALID_RESOURCE_ID",
      "field": "capture_id",
      "value": "FAKE_CAPTURE_ID",
      "description": "Specified resource ID does not exist.",
      "location": "path"
    }
  ],
  "links": [
    { "href": "https://developer.paypal.com/docs/api/payments/v2/#error-INVALID_RESOURCE_ID", "rel": "information_link" }
  ]
}
```

---

## 8. Sandbox Testing Results (2026-11-10)

| Test | Status | Details |
|---|---|---|
| OAuth Token | ✅ 200 OK | Bearer token, 32,400s expiry, refund scope confirmed |
| Create Order | ✅ 201 Created | Order `29143304YR052760W`, status `CREATED` |
| Retrieve Order | ✅ 200 OK | Full item/SKU data, payee merchant ID `B5DU7MB92L246` |
| Order with items | ✅ Verified | SKU `ESPRESSO-DLG-001`, category `PHYSICAL_GOODS`, amount `200.00 USD` |
| Approval URL | ✅ Present | `https://www.sandbox.paypal.com/checkoutnow?token=...` |
| Refund endpoint | ✅ Accessible | Returns proper `RESOURCE_NOT_FOUND` for invalid capture_id |
| Webhook list | ✅ 200 OK | 0 existing webhooks |
| Webhook events | ✅ 205 types | Includes `PAYMENT.CAPTURE.REFUNDED`, `PAYMENT.REFUND.COMPLETED` |
| Transaction Search | ❌ 403 | `NOT_AUTHORIZED` — requires partner permissions |

### Sandbox Accounts
- **Merchant (Business):** `sb-oreai53359961@business.example.com` (Merchant ID: `B5DU7MB92L246`)
- **Buyer (Personal):** Check PayPal Developer Dashboard for sandbox personal account

---

## 9. Limitations & Notes

1. **Sandbox only.** Live endpoints are hard-blocked.
2. **Transaction Search API unavailable** with standard sandbox credentials (requires partner-level).
   - **Workaround:** Track all orders/captures in our own database after creation.
3. **Refund endpoint is fully available** — no partner assertion or merchant consent needed when using the merchant's own credentials.
4. **Multiple partial refunds** are supported on a single capture (total ≤ original amount).
5. **`note_to_payer`** is shown to the buyer — we use this for the price-drop notification message.
6. **SKU data** is only available if the merchant sends it during order creation. Since DropBack IS the merchant tool, we control this.
