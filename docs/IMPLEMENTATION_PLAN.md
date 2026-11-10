# DropBack for Merchants — Full Implementation Plan

> **Deadline:** Nov 12, 2026 at 12:00pm PST (Thu 21:00 IST)
> **Repository:** https://github.com/aniket-sartechlabs/paypal-idea-4.git
> **Status:** Core implementation is built. Sandbox buyer approval is currently blocked because the configured PayPal sandbox seller rejected USD. Production provider setup also remains outstanding; see Sections 8 and 16.

---

## 1. The Idea (Refined)

**DropBack for Merchants** — an AI-assisted price-protection agent that helps merchants proactively offer partial refunds to recent buyers when prices drop, reducing costly full-item returns. Every refund remains under merchant approval.

### The Problem (Merchant-Side)
When a merchant lowers a product price, recent buyers who paid more often:
1. Return the item entirely (costing the merchant double-shipping + restocking + open-box discount)
2. Buy it again at the lower price
3. Leave negative reviews ("I paid $200 and it's $160 now!")

**A full return + repurchase costs the merchant $30–$50 per order.** A proactive $40 partial refund costs only $40 and retains the customer.

### How DropBack Works
1. **A single merchant configures DropBack** with its PayPal account credentials. Multi-merchant installation and PayPal partner onboarding are future work.
2. **Orders flow in** — captured via PayPal Orders v2 with full SKU/item data
3. **Price drop detected** — via Channel3 API monitoring or merchant manually triggering a price change
4. **DropBack evaluates each eligible order:**
   - Is it within the price-protection window (default: 14 days)?
   - Does the SKU/product match?
   - Is the refund amount within the per-order and daily budget caps?
   - Is the probability-weighted return cost higher than the proposed refund?
5. **The merchant approves a recommendation**, then the backend issues the partial refund via `POST /v2/payments/captures/{id}/refund` with a customer-friendly `note_to_payer`. DropBack never issues a refund automatically.
6. **Customer sees** "$40 back in your PayPal" with message: "We dropped the price — here's the difference back!"
7. **Merchant dashboard** shows: orders exposed, refunds issued, estimated returns avoided, net savings

### Why This Wins
- ✅ **Every PayPal API call is legitimate** — merchant's own credentials, own captures, own refunds
- ✅ **AI supports a real merchant decision** — deterministic policy rules remain authoritative and a human approves each refund
- ✅ **Directly targets multiple prize categories** — Best Agentic Commerce, Most Impactful, AG Grid, Channel3
- ✅ **The sandbox money flow is real** — checkout, capture, and refunds use PayPal Sandbox; buyer approval is required to complete checkout
- ✅ **Post-purchase is an underserved niche** — most teams will build checkout agents

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    REACT + VITE FRONTEND                        │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ Merchant      │  │ Order        │  │ AG Grid Dashboard     │ │
│  │ Storefront    │  │ History      │  │ - Price Exposure      │ │
│  │ (PayPal SDK   │  │ View         │  │ - Refunds Issued      │ │
│  │  Checkout)    │  │              │  │ - Returns Avoided     │ │
│  └──────┬───────┘  └──────┬───────┘  │ - Net Savings         │ │
│         │                 │          │ - Agent Decisions Log  │ │
│         │                 │          └───────────┬────────────┘ │
│         └────────┬────────┘                      │              │
│                  │         REST / JSON            │              │
└──────────────────┼───────────────────────────────┼──────────────┘
                   │                               │
                   ▼                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FASTAPI BACKEND                               │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ PayPal Service Layer                                     │   │
│  │ ├── OAuth Token Manager (cached, auto-refresh)          │   │
│  │ ├── Order Creator (with items/SKU/breakdown)            │   │
│  │ ├── Order Capturer (idempotent)                         │   │
│  │ ├── Partial Refund Issuer (the CORE operation)          │   │
│  │ └── Webhook Handler (signature verification)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ DropBack AI Agent                                        │   │
│  │ ├── Price Monitor (Channel3 polling + manual trigger)   │   │
│  │ ├── Eligibility Engine (window, SKU match, budget)      │   │
│  │ ├── Return-Cost Estimator (AI-scored probability)       │   │
│  │ ├── Refund Decision Engine (deterministic + LLM reason) │   │
│  │ └── Agent Action Logger (full audit trail)              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Data Layer (SQLite → PostgreSQL)                         │   │
│  │ ├── products          ├── price_drops                   │   │
│  │ ├── orders            ├── refund_decisions              │   │
│  │ ├── captures          ├── refunds                       │   │
│  │ └── agent_actions     └── merchant_settings             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                   │                               │
                   ▼                               ▼
         ┌──────────────┐               ┌──────────────────┐
         │ PayPal        │               │ Channel3 API     │
         │ Sandbox       │               │ (Price Data)     │
         │ REST API      │               │                  │
         └──────────────┘               └──────────────────┘
```

---

## 3. Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Backend** | Python 3.11+ / FastAPI | REST API, PayPal integration, agent logic |
| **Frontend** | React 18 + Vite + TypeScript | Merchant dashboard, checkout demo |
| **Dashboard** | AG Grid Community (React) | Order grid, refund log, analytics (sponsor prize) |
| **Database** | SQLite (dev) / PostgreSQL (prod) | Order tracking, agent decisions |
| **ORM** | SQLAlchemy 2.0 | Database models & queries |
| **PayPal** | REST API v2 + JS SDK v6 | Orders, Captures, Refunds, Webhooks |
| **Price Data** | Channel3 API | Product price monitoring (sponsor prize) |
| **AI/LLM** | Gemini API / OpenAI GPT-4o-mini | Agent reasoning, refund decision explanations |
| **Styling** | Tailwind CSS | Responsive, clean UI |

---

## 4. PayPal API Integration Map

### APIs Used (All Verified Working in Sandbox)

| API | Endpoint | Purpose in DropBack |
|---|---|---|
| OAuth 2.0 | `POST /v1/oauth2/token` | Authenticate all API calls |
| Create Order | `POST /v2/checkout/orders` | Merchant creates orders with SKU/item data |
| Get Order | `GET /v2/checkout/orders/{id}` | Verify order details before refund |
| Capture Order | `POST /v2/checkout/orders/{id}/capture` | Complete payment after buyer approval |
| **Partial Refund** | `POST /v2/payments/captures/{capture_id}/refund` | **THE CORE OPERATION** — issue price-drop refund |
| Get Refund | `GET /v2/payments/refunds/{refund_id}` | Verify refund status |
| Webhooks | `POST /v1/notifications/webhooks` | Register for capture/refund events |
| Verify Webhook | `POST /v1/notifications/verify-webhook-signature` | Secure webhook processing |

### Key Webhook Events

| Event | Trigger |
|---|---|
| `PAYMENT.CAPTURE.COMPLETED` | Order payment captured → store in DB |
| `PAYMENT.CAPTURE.REFUNDED` | Refund processed → update dashboard |
| `PAYMENT.REFUND.COMPLETED` | Refund confirmed → notify merchant |

---

## 5. Database Schema

```sql
-- Products the merchant sells
CREATE TABLE products (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sku TEXT UNIQUE NOT NULL,
    description TEXT,
    current_price REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    category TEXT,
    image_url TEXT,
    channel3_product_id TEXT,        -- Link to Channel3 data
    price_protection_days INTEGER DEFAULT 14,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders placed through PayPal
CREATE TABLE orders (
    id TEXT PRIMARY KEY,             -- Internal UUID
    paypal_order_id TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,            -- CREATED, APPROVED, COMPLETED, REFUNDED
    buyer_email TEXT,
    buyer_name TEXT,
    total_amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Individual items within an order
CREATE TABLE order_items (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_id TEXT REFERENCES products(id),
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,        -- Price at time of purchase
    currency TEXT DEFAULT 'USD'
);

-- PayPal captures (payment confirmations)
CREATE TABLE captures (
    id TEXT PRIMARY KEY,             -- Internal UUID
    paypal_capture_id TEXT UNIQUE NOT NULL,
    order_id TEXT NOT NULL REFERENCES orders(id),
    status TEXT NOT NULL,            -- COMPLETED, PENDING, REFUNDED
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    refunded_amount REAL DEFAULT 0,  -- Running total of refunds issued
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Price drop events detected by the agent
CREATE TABLE price_drops (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES products(id),
    old_price REAL NOT NULL,
    new_price REAL NOT NULL,
    drop_amount REAL NOT NULL,       -- old_price - new_price
    drop_percentage REAL NOT NULL,
    source TEXT NOT NULL,            -- 'channel3', 'manual', 'competitor'
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE
);

-- AI agent refund decisions
CREATE TABLE refund_decisions (
    id TEXT PRIMARY KEY,
    price_drop_id TEXT NOT NULL REFERENCES price_drops(id),
    capture_id TEXT NOT NULL REFERENCES captures(id),
    order_id TEXT NOT NULL REFERENCES orders(id),
    decision TEXT NOT NULL,          -- 'REFUND', 'SKIP', 'PENDING_REVIEW'
    refund_amount REAL,
    reasoning TEXT NOT NULL,         -- AI-generated explanation
    return_probability REAL,         -- 0.0 to 1.0
    estimated_return_cost REAL,
    estimated_savings REAL,          -- return_cost - refund_amount
    within_window BOOLEAN NOT NULL,
    budget_available BOOLEAN NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Actual refunds issued via PayPal
CREATE TABLE refunds (
    id TEXT PRIMARY KEY,
    paypal_refund_id TEXT UNIQUE,
    decision_id TEXT NOT NULL REFERENCES refund_decisions(id),
    capture_id TEXT NOT NULL REFERENCES captures(id),
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    status TEXT NOT NULL,            -- COMPLETED, PENDING, FAILED
    note_to_payer TEXT,
    idempotency_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Agent action audit log
CREATE TABLE agent_actions (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,       -- PRICE_CHECK, ELIGIBILITY_EVAL, REFUND_DECISION, REFUND_ISSUED
    entity_type TEXT,                -- 'order', 'product', 'refund'
    entity_id TEXT,
    details TEXT NOT NULL,           -- JSON blob with full context
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Merchant configuration
CREATE TABLE merchant_settings (
    id TEXT PRIMARY KEY DEFAULT 'default',
    merchant_name TEXT DEFAULT 'Demo Merchant',
    price_protection_window_days INTEGER DEFAULT 14,
    max_refund_per_order REAL DEFAULT 100.00,
    daily_refund_budget REAL DEFAULT 500.00,
    auto_refund_enabled BOOLEAN DEFAULT FALSE,  -- Require approval by default
    min_price_drop_percentage REAL DEFAULT 5.0,
    min_price_drop_amount REAL DEFAULT 5.00,
    return_shipping_cost REAL DEFAULT 12.00,     -- Estimated per-return cost
    restocking_fee_percentage REAL DEFAULT 15.0,
    open_box_discount_percentage REAL DEFAULT 25.0
);
```

---

## 6. API Routes

### Backend REST API (`/api/v1/`)

#### Orders & Checkout
| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/orders` | Create PayPal order (server-controlled amounts) |
| `POST` | `/api/v1/orders/{order_id}/capture` | Capture order after buyer approval |
| `GET` | `/api/v1/orders` | List all orders (with filtering) |
| `GET` | `/api/v1/orders/{order_id}` | Get order details |

#### Products
| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/products` | List all products |
| `POST` | `/api/v1/products` | Add product to catalog |
| `PATCH` | `/api/v1/products/{id}/price` | Update product price (triggers price drop detection) |

#### Price Drops & Agent
| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/price-drops` | List detected price drops |
| `POST` | `/api/v1/price-drops/check` | Manually trigger Channel3 price check |
| `POST` | `/api/v1/price-drops/{id}/process` | Have agent process a price drop |
| `GET` | `/api/v1/agent/decisions` | List all agent decisions with reasoning |
| `POST` | `/api/v1/agent/decisions/{id}/approve` | Merchant approves a refund decision |
| `POST` | `/api/v1/agent/decisions/{id}/reject` | Merchant rejects a refund decision |

#### Refunds
| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/refunds` | List all refunds |
| `POST` | `/api/v1/refunds/{decision_id}/execute` | Execute approved refund via PayPal |
| `GET` | `/api/v1/refunds/{id}/status` | Check refund status |

#### Dashboard & Analytics
| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/dashboard/stats` | Aggregate stats (exposure, savings, refunds) |
| `GET` | `/api/v1/dashboard/timeline` | Refund activity over time |

#### Webhooks
| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/webhooks/paypal` | Receive PayPal webhook events |
| `POST` | `/api/v1/webhooks/channel3` | Receive signed Channel3 price-change events |

#### Settings
| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/v1/settings` | Get merchant settings |
| `PATCH` | `/api/v1/settings` | Update settings (budget, window, etc.) |

---

## 7. Agent Decision Logic (Deterministic + AI)

### Step-by-Step Refund Decision Flow

```
Price Drop Detected
        │
        ▼
┌───────────────────┐
│ 1. Find Eligible  │  Query: orders with matching SKU
│    Orders          │  captured within price_protection_window_days
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ 2. For Each Order │
│    Check Rules    │
│                   │
│  ├─ SKU match?    │  DETERMINISTIC
│  ├─ Within window?│
│  ├─ Already       │
│  │  refunded?     │
│  ├─ Budget cap?   │
│  └─ Min drop %?   │
└────────┬──────────┘
         │ All pass
         ▼
┌───────────────────┐
│ 3. Calculate      │
│    Financials     │  DETERMINISTIC
│                   │
│  refund_amount = old_price - new_price
│  return_cost = shipping_both_ways + restock_loss + open_box_loss
│  expected_net_savings = return_probability × return_cost - refund_amount
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ 4. AI Scoring     │  LLM-ASSISTED
│                   │
│  Return probability (0–1) based on:
│  ├─ Price drop magnitude
│  ├─ Product category (electronics = high return risk)
│  ├─ Days since purchase
│  └─ Drop as % of price
│
│  Generate human-readable reasoning
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ 5. Decision       │  DETERMINISTIC (final authority)
│                   │
│  IF expected_net_savings > 0 AND return_prob > threshold:
│    → RECOMMEND REFUND
│  ELSE:
│    → SKIP (explain why)
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ 6. Merchant       │
│    Review         │  HUMAN-IN-THE-LOOP
│                   │
│  Show decision + reasoning in dashboard
│  Merchant clicks APPROVE or REJECT
│  Automatic approval is disabled
└────────┬──────────┘
         │ Approved
         ▼
┌───────────────────┐
│ 7. Execute Refund │
│                   │
│  POST /v2/payments/captures/{id}/refund
│  with idempotency key
│  note_to_payer: "Price dropped! Here's $X back."
└───────────────────┘
```

### Return Cost Estimation Formula

Using merchant's configurable settings:

```
return_shipping_cost = settings.return_shipping_cost × 2  (merchant pays both ways)
restocking_loss = item_price × settings.restocking_fee_percentage / 100
open_box_loss = item_price × settings.open_box_discount_percentage / 100

total_return_cost = return_shipping_cost + restocking_loss + open_box_loss

net_savings = total_return_cost - refund_amount

IF net_savings > 0 → refund costs less than a return
```

**Example (from the pitch):**
- Espresso machine: $200, drops to $160 → refund = $40
- Return cost: $24 shipping + $30 restock + $50 open-box = $104
- Net savings: $104 - $40 = **$64 saved per avoided return**

---

## 8. Channel3 Integration

### Purpose and current API flow
Channel3 is required for live product matching and market-price signals. The current Channel3 API uses `POST https://api.trychannel3.com/v1/search` with an `x-api-key` header. The backend compares the matched product's in-stock new offers in the same currency, stores the stable Channel3 product ID, then creates a product subscription for `offer.price.changed` and `offer.availability.changed`.

The old sketch above assumed a polled response shape and `result.sku`; those fields are not guaranteed by the current API. The matcher checks distinguishing model/size/color tokens and title coverage before using a candidate, with a strict 0.95 confidence threshold. Generic or ambiguous product names are not auto-linked; use the exact Channel3 title or a matching SKU. A rejected prior link is unsubscribed and cleared so later events cannot create a false recommendation. Returned affiliate offer links do not affect refund decisions.

### Price event behavior
- A merchant can run an immediate live check from Products. A lower matched offer creates a price-drop candidate; drop size and percent thresholds are evaluated against the buyer's purchase price when recommendations are calculated.
- Channel3 product subscriptions refresh on their provider cadence and send signed Svix events to `/api/v1/webhooks/channel3`. The backend verifies timestamp and signature, deduplicates event IDs, and fetches the latest product before recording a lower price.
- Channel3 price signals are market offers. They do not change the merchant's storefront price. A price signal only creates recommendations; a merchant still reviews every refund.
- A direct merchant price edit is retained as a secondary event source when the merchant updates its own catalog.
- `CHANNEL3_API_KEY` is required for live checks. Automated subscription delivery requires `CHANNEL3_WEBHOOK_SECRET` and a public HTTPS webhook registered in Channel3's dashboard.

Channel3 documents product subscriptions as daily refresh based notifications, not instant continuous polling. Their exact event schema can evolve, so the webhook implementation refetches product data by the stable product ID instead of trusting a price embedded in the event. Expected net savings are calculated as `return_probability × estimated_return_cost − refund_amount`; this prevents low-probability returns from being presented as guaranteed savings.

---

## 9. AG Grid Dashboard

### Panels

#### 1. Price Exposure Grid
Shows all captured orders within the protection window that would be affected by a price drop.

| Column | Type | Description |
|---|---|---|
| Order ID | Text | PayPal order ID |
| Product | Text | Product name + SKU |
| Purchase Price | Currency | What buyer paid |
| Current Price | Currency | Today's price |
| Drop | Currency (red) | Difference |
| Days Remaining | Number (badge) | Days left in protection window |
| Status | Badge | Exposed / Refunded / Expired |

#### 2. Refund Decisions Grid
Agent decisions awaiting merchant review.

| Column | Type | Description |
|---|---|---|
| Order | Link | Click to expand |
| Buyer | Text | Email/name |
| Refund Amount | Currency | Recommended refund |
| Return Probability | Progress bar | 0–100% |
| Est. Return Cost | Currency | If buyer returns instead |
| Net Savings | Currency (green) | Savings from refunding vs. return |
| Agent Reasoning | Expandable text | LLM-generated explanation |
| Action | Buttons | Approve / Reject |

#### 3. Analytics Summary Grid
| Column | Type |
|---|---|
| Total Orders Exposed | Count |
| Refunds Issued | Count |
| Total Refunded | Currency |
| Estimated Returns Avoided | Count |
| Estimated Savings | Currency |
| Avg. Refund Amount | Currency |

### AG Grid Features Used
- `cellRenderer` — Custom React components for badges, progress bars, action buttons
- `valueFormatter` — Currency formatting
- `sortable` + `filter` — All columns
- `ag-theme-quartz` — Modern theme
- `quickFilterText` — Global search
- Row selection for batch approval
- Pagination for large datasets

---

## 10. Frontend Pages

| Route | Component | Purpose |
|---|---|---|
| `/` | `Dashboard` | Main analytics view with AG Grid panels |
| `/store` | `StoreFront` | Demo storefront with PayPal checkout (SDK v6) |
| `/orders` | `OrdersView` | All orders with status |
| `/price-drops` | `PriceDrops` | Detected price drops + trigger manual check |
| `/agent` | `AgentDecisions` | Review agent decisions, approve/reject |
| `/settings` | `Settings` | Merchant configuration |
| `/checkout/return` | `CheckoutReturn` | PayPal return URL after buyer approval |
| `/checkout/cancel` | `CheckoutCancel` | PayPal cancel URL |

---

## 11. Development Phases (72-Hour Plan)

### Phase 1: Foundation (Hours 0–8) — COMPLETE
- [x] Repository setup
- [x] PayPal API research & verification
- [x] Sandbox credential testing
- [x] Documentation
- [x] Project scaffolding (FastAPI + Vite + React)
- [x] Database models & migrations
- [x] PayPal service layer (OAuth, Orders, Captures, Refunds)
- [x] Basic API routes

### Phase 2: Core Engine (Hours 8–20)
- [x] Product catalog with seed data
- [x] Order creation → capture → store flow implemented; sandbox order creation verified through the browser
- [x] PayPal JS SDK v6 checkout integration
- [x] Price drop detection (merchant update + Channel3 live checks and subscriptions)
- [x] Refund recommendation engine (deterministic eligibility and budget rules)
- [x] Partial refund execution via PayPal API after merchant approval
- [ ] End-to-end sandbox test: buyer approval → capture → Channel3 price drop → approved refund (blocked until the PayPal sandbox Business seller accepts USD)

### Phase 3: AI Agent (Hours 20–32)
- [x] Optional LLM integration (Gemini/OpenAI) for return probability scoring, with deterministic fallback
- [x] Agent reasoning generation (human-readable explanations)
- [x] Agent action logging & audit trail
- [x] Human review and approval flow; automatic refunds are intentionally disabled
- [x] Channel3 API integration for live price monitoring and subscriptions

### Phase 4: Dashboard & UX (Hours 32–48)
- [x] AG Grid dashboard (orders, price drops, and refund decisions)
- [ ] Dedicated price-exposure chart (current exposure and summary metrics are available)
- [x] Refund decision review UI with approve/reject
- [x] Analytics summary cards
- [x] Merchant settings page
- [x] Demo storefront with product cards + PayPal checkout

### Phase 5: Polish & Submit (Hours 48–72)
- [x] PayPal and Channel3 webhook handlers with signature verification; provider registration still requires production HTTPS setup
- [x] Error handling & edge cases for core payment, price, and refund paths
- [x] Development seed data with clearly non-refundable sample orders
- [ ] Full end-to-end demo flow scripting (pending a successful sandbox buyer approval after seller currency setup)
- [x] README.md with setup instructions
- [ ] Record 3-minute demo video
- [ ] Devpost submission

---

## 12. File Structure

```
paypal-idea-4/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app entry
│   │   ├── config.py               # Environment & settings
│   │   ├── database.py             # SQLAlchemy setup
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── product.py
│   │   │   ├── order.py
│   │   │   ├── capture.py
│   │   │   ├── price_drop.py
│   │   │   ├── refund_decision.py
│   │   │   ├── refund.py
│   │   │   ├── agent_action.py
│   │   │   └── settings.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── paypal_auth.py      # OAuth token manager
│   │   │   ├── paypal_orders.py    # Create, get, capture orders
│   │   │   ├── paypal_refunds.py   # Issue & verify refunds
│   │   │   ├── paypal_webhooks.py  # Webhook handler
│   │   │   ├── channel3.py         # Price monitoring
│   │   │   ├── agent.py            # DropBack AI agent
│   │   │   └── llm.py              # LLM integration
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── orders.py
│   │   │   ├── products.py
│   │   │   ├── price_drops.py
│   │   │   ├── refunds.py
│   │   │   ├── agent.py
│   │   │   ├── dashboard.py
│   │   │   ├── webhooks.py
│   │   │   └── settings.py
│   │   └── schemas/
│   │       ├── __init__.py
│   │       └── *.py                # Pydantic models
│   ├── requirements.txt
│   └── seed_data.py                # Populate demo data
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/
│   │   │   ├── Dashboard/
│   │   │   │   ├── ExposureGrid.tsx
│   │   │   │   ├── DecisionsGrid.tsx
│   │   │   │   ├── AnalyticsSummary.tsx
│   │   │   │   └── StatsCards.tsx
│   │   │   ├── Store/
│   │   │   │   ├── ProductCard.tsx
│   │   │   │   └── PayPalCheckout.tsx
│   │   │   ├── Agent/
│   │   │   │   ├── DecisionCard.tsx
│   │   │   │   └── ReasoningPanel.tsx
│   │   │   └── Layout/
│   │   │       ├── Sidebar.tsx
│   │   │       └── Header.tsx
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── StoreFront.tsx
│   │   │   ├── Orders.tsx
│   │   │   ├── PriceDrops.tsx
│   │   │   ├── AgentDecisions.tsx
│   │   │   └── Settings.tsx
│   │   ├── hooks/
│   │   │   └── usePayPal.ts
│   │   ├── services/
│   │   │   └── api.ts
│   │   └── types/
│   │       └── index.ts
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── docs/
│   ├── PAYPAL_INTEGRATION.md
│   ├── ARCHITECTURE.md
│   └── IMPLEMENTATION_PLAN.md
├── scripts/
│   ├── paypal_sandbox_test.py
│   └── seed_orders.py
├── .env
├── .env.example
├── .gitignore
├── README.md
├── Dockerfile
├── docker-compose.yml
└── LICENSE
```

---

## 13. Prize Strategy

| Prize | Amount | How DropBack Qualifies |
|---|---|---|
| **1st Place** | $12,000 | Strong across all criteria |
| **Best Use of Agentic Commerce** | $5,000 | AI estimates return risk; merchant approves each partial refund |
| **Most Impactful** | $5,000 | Saves merchants money, improves customer experience |
| **AG Grid** (1st) | $5,000 | Dashboard built entirely with AG Grid |
| **AG Grid** (2nd) | $2,000 | (backup) |
| **Channel3** | $1,500 | Product price monitoring via Channel3 API |
| **Best Demo** | $5,000 | Clear 3-min demo showing real sandbox refund |

**Total potential:** Up to $35,500 across categories.

---

## 14. Demo Flow (3-Minute Video Script)

1. **0:00–0:20** — "Every day, merchants lose money when customers return items just to rebuy at a lower price. DropBack fixes this."
2. **0:20–0:50** — Show storefront. Buy an espresso machine through PayPal Sandbox and complete buyer approval.
3. **0:50–1:10** — Run the Channel3 live price check. If no lower market offer is available during the demo, use the merchant price-update control to exercise the fallback workflow.
4. **1:10–1:40** — DropBack scores eligible orders and compares probability-weighted return costs with each proposed refund.
5. **1:40–2:10** — Merchant reviews the reasoning in the dashboard and approves an individual recommendation. The backend executes the sandbox refund.
6. **2:10–2:30** — Show the sandbox buyer account and the completed refund.
7. **2:30–2:50** — Dashboard summary: "5 refunds issued ($200 total), ~5 returns avoided, $320 estimated savings."
8. **2:50–3:00** — "DropBack: proactive refunds that save merchants money and delight customers."

---

## 15. Environment Variables (`.env`)

```bash
# Server
ENVIRONMENT=development
PORT=8000
HOST=0.0.0.0
CORS_ORIGINS=["http://localhost:5173","http://127.0.0.1:5173"]

# Database
DATABASE_URL=sqlite:///./dropback.db

# PayPal Sandbox
PAYPAL_ENV=sandbox
PAYPAL_CLIENT_ID=<from sandbox>
PAYPAL_CLIENT_SECRET=<from sandbox>
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com

# Channel3 API
CHANNEL3_API_KEY=<get from trychannel3.com>

# LLM
LLM_PROVIDER=gemini          # or openai
GEMINI_API_KEY=<key>
OPENAI_API_KEY=<key>

# Security
SECRET_KEY=<random-string>
MERCHANT_EMAIL=<merchant login>
MERCHANT_PASSWORD=<merchant password>
APP_BASE_URL=https://<public-host>
PAYPAL_WEBHOOK_ID=<registered webhook id>
CHANNEL3_WEBHOOK_SECRET=<Svix signing secret>
```

## 16. Implementation Review and Production Boundaries

- DropBack requires merchant sign-in for dashboard data and actions. Local demo credentials are development-only. Production requires explicit merchant login credentials and a strong session signing key.
- PayPal order totals are built from server-side catalog prices. Client secrets remain on the backend. Capture, refund, and webhook verification use stable idempotency or event IDs. Refunds require merchant approval; automatic refund execution is disabled.
- Sample orders exist only in local development and are marked as samples. They cannot be refunded because they have no real PayPal capture. Production does not seed sample orders.
- Currency amounts use decimal database columns and money values are rounded to two decimal places. PostgreSQL is supported through SQLAlchemy/Alembic; local development uses SQLite.
- This implementation is single-merchant. It does not implement PayPal partner onboarding, merchant consent, per-merchant credentials, account recovery, or multi-tenant data isolation. A public multi-merchant SaaS release needs those capabilities before inviting unrelated merchants.
- Real money use also requires production PayPal approval, live credentials, registered PayPal and Channel3 webhooks, a public HTTPS host, PostgreSQL backups, secret management, monitoring, and operational recovery procedures. Development is hard-restricted to PayPal Sandbox.
