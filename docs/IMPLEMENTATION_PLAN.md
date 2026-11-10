# DropBack for Merchants — Full Implementation Plan

> **Deadline:** Nov 12, 2026 at 12:00pm PST (Thu 21:00 IST)
> **Repository:** https://github.com/aniket-sartechlabs/paypal-idea-4.git
> **Status:** Research complete. Ready to build.

---

## 1. The Idea (Refined)

**DropBack for Merchants** — an AI-powered autonomous price-protection agent that helps merchants proactively issue partial refunds to recent buyers when prices drop, eliminating costly full-item returns.

### The Problem (Merchant-Side)
When a merchant lowers a product price, recent buyers who paid more often:
1. Return the item entirely (costing the merchant double-shipping + restocking + open-box discount)
2. Buy it again at the lower price
3. Leave negative reviews ("I paid $200 and it's $160 now!")

**A full return + repurchase costs the merchant $30–$50 per order.** A proactive $40 partial refund costs only $40 and retains the customer.

### How DropBack Works
1. **Merchant installs DropBack** and connects their PayPal merchant account
2. **Orders flow in** — captured via PayPal Orders v2 with full SKU/item data
3. **Price drop detected** — via Channel3 API monitoring or merchant manually triggering a price change
4. **AI Agent evaluates each eligible order:**
   - Is it within the price-protection window (default: 14 days)?
   - Does the SKU/product match?
   - Is the refund amount ≤ the configurable budget cap?
   - Is the projected return cost higher than the refund? (return probability scoring)
5. **Agent issues partial refund** via `POST /v2/payments/captures/{id}/refund` with a customer-friendly `note_to_payer`
6. **Customer sees** "$40 back in your PayPal" with message: "We dropped the price — here's the difference back!"
7. **Merchant dashboard** shows: orders exposed, refunds issued, estimated returns avoided, net savings

### Why This Wins
- ✅ **Every PayPal API call is legitimate** — merchant's own credentials, own captures, own refunds
- ✅ **AI makes a real financial decision** — not just automating a form
- ✅ **Directly targets multiple prize categories** — Best Agentic Commerce, Most Impactful, AG Grid, Channel3
- ✅ **The "money moment" is real** — sandbox buyer actually receives the refund
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
│  net_savings = return_cost - refund_amount
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
│  IF net_savings > 0 AND return_prob > threshold:
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
│  (or auto-approve if enabled in settings)
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

### Purpose
Monitor product prices across retailers to detect price drops automatically.

### Implementation
```python
# Price check flow
async def check_prices(product: Product) -> Optional[PriceDrop]:
    """Query Channel3 for current price of a product."""
    response = await channel3_client.search(
        query=product.name,
        filters={"website_ids": [product.merchant_domain]}  # optional
    )

    for result in response.products:
        if result.sku == product.sku or fuzzy_match(result.title, product.name):
            current_price = min(offer.price for offer in result.offers)
            if current_price < product.current_price:
                drop = product.current_price - current_price
                return PriceDrop(
                    product_id=product.id,
                    old_price=product.current_price,
                    new_price=current_price,
                    source="channel3"
                )
    return None
```

### Fallback
If Channel3 API is unavailable:
1. Manual price update via merchant dashboard (always available)
2. Simulated price drops for demo purposes

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

### Phase 1: Foundation (Hours 0–8) — CURRENT
- [x] Repository setup
- [x] PayPal API research & verification
- [x] Sandbox credential testing
- [x] Documentation
- [ ] Project scaffolding (FastAPI + Vite + React)
- [ ] Database models & migrations
- [ ] PayPal service layer (OAuth, Orders, Captures, Refunds)
- [ ] Basic API routes

### Phase 2: Core Engine (Hours 8–20)
- [ ] Product catalog with seed data
- [ ] Order creation → capture → store flow
- [ ] PayPal JS SDK v6 checkout integration
- [ ] Price drop detection (manual + Channel3)
- [ ] Refund decision engine (deterministic rules)
- [ ] Partial refund execution via PayPal API
- [ ] End-to-end test: order → price drop → refund

### Phase 3: AI Agent (Hours 20–32)
- [ ] LLM integration (Gemini/OpenAI) for return probability scoring
- [ ] Agent reasoning generation (human-readable explanations)
- [ ] Agent action logging & audit trail
- [ ] Auto-process vs. manual review modes
- [ ] Channel3 API integration for automated price monitoring

### Phase 4: Dashboard & UX (Hours 32–48)
- [ ] AG Grid dashboard (3 panels)
- [ ] Price exposure visualization
- [ ] Refund decision review UI with approve/reject
- [ ] Analytics summary cards
- [ ] Merchant settings page
- [ ] Demo storefront with product cards + PayPal checkout

### Phase 5: Polish & Submit (Hours 48–72)
- [ ] Webhook integration (PAYMENT.CAPTURE.COMPLETED, PAYMENT.CAPTURE.REFUNDED)
- [ ] Error handling & edge cases
- [ ] Seed data: 20 demo orders with various states
- [ ] Full end-to-end demo flow scripting
- [ ] README.md with setup instructions
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
| **Best Use of Agentic Commerce** | $5,000 | AI agent autonomously decides & executes partial refunds |
| **Most Impactful** | $5,000 | Saves merchants money, improves customer experience |
| **AG Grid** (1st) | $5,000 | Dashboard built entirely with AG Grid |
| **AG Grid** (2nd) | $2,000 | (backup) |
| **Channel3** | $1,500 | Product price monitoring via Channel3 API |
| **Best Demo** | $5,000 | Clear 3-min demo showing real sandbox refund |

**Total potential:** Up to $35,500 across categories.

---

## 14. Demo Flow (3-Minute Video Script)

1. **0:00–0:20** — "Every day, merchants lose money when customers return items just to rebuy at a lower price. DropBack fixes this."
2. **0:20–0:50** — Show storefront. Buy espresso machine for $200 via PayPal checkout. Capture completes.
3. **0:50–1:10** — Merchant lowers price to $160. DropBack detects the $40 drop.
4. **1:10–1:40** — AI agent evaluates: "5 orders eligible. Return cost per order: $104. Refund cost: $40. Net savings: $64 per order."
5. **1:40–2:10** — Merchant reviews decisions in AG Grid dashboard. Approves batch. Refunds execute via PayPal.
6. **2:10–2:30** — Show sandbox buyer account: "$40 refund from DropBack Merchant Demo — We dropped the price!"
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
```
