# DropBack: 14-Day Price Protection & Return Prevention

> **Built for the PayPal AI Hackathon 2026**
> Targeting **AG Grid**, **APIMatic Context Plugins**, and **Channel3** sponsor categories.

DropBack turns return disputes into customer retention. When a customer purchases an item backed by **14-Day DropBack Insurance**, they can check live competitor prices 2–3 days later. If Channel3 detects a lower market price, the customer submits a price-match dispute instead of returning the physical box. The merchant reviews an **AG Grid** case report detailing the actuarial return cost versus a price difference settlement, customizes an AI-drafted resolution message, and executes an instant refund via **PayPal Sandbox Orders v2**, visible immediately in the customer's portal.

---

## 🏆 Hackathon Sponsor Integrations

### 1. Channel3: Live Competitor Catalog & Dispute Trigger
- **Real Indexed Catalog:** Pre-seeded with items verified in Channel3's index (`Sony WH-1000XM5`, `Breville Barista Express Espresso Machine`, `Apple AirPods Pro 2`, `Amazon Kindle Paperwhite`).
- **Live Search & Price Checks:** Channel3 extracts live retailer offers, competitor domains (B&H Photo, Macy's, Best Buy, Abt), direct product links, and item shipping weights.
- **Customer Guarantee Portal (`/portal`):** Buyers can look up their order, trigger a live Channel3 price check within their 14-day window, and submit a price-match dispute.

### 2. AG Grid ($10,000 Prize Category): Enterprise Merchant Console
- **Rich Grid Interface (`/claims`):** Enterprise-grade AG Grid console with custom cell renderers:
  - **Buyer & Order:** Initials avatar, customer name, order ID, and blue `CLAIM` pill.
  - **Channel3 Market Signal:** Live competitor badges (e.g. `B&H Photo: $298.00`) and price drop deltas.
  - **Return Risk Gauge:** Animated actuarial return probability meter with color-coded risk levels.
  - **Case Costings Column:** Side-by-side financial comparison showing estimated physical return loss vs. proactive difference settlement.
  - **AI Actuarial Analysis:** Badge indicating model provider (`OpenAI gpt-4.1-mini`, `Gemini 2.0`, or deterministic engine) with quick inspection links.
  - **Resolution Actions:** One-click `Review & Settle` button launching the case report modal.
- **Interactive Capabilities:** Global quick-filter search, sorting, column resizing, and pagination.

### 3. APIMatic: Context Plugins & PayPal Sandbox MCP Protocol
- **Zero-Hallucination Schemas:** Uses APIMatic OpenAPI 3.0 context plugins (`.context-plugins/paypal.json` and `context-plugins.config.json`) to feed modern PayPal v2 Orders and Payments schemas directly to AI agents, preventing hallucinations of deprecated v1 endpoints.
- **MCP Sandbox Explorer (`/apimatic`):** Interactive Model Context Protocol tool runner exposing 4 verified sandbox tools:
  - `paypal_check_sandbox_health`
  - `paypal_get_order_details`
  - `paypal_get_capture_status`
  - `paypal_issue_capture_refund`
- Features real-time latency measurement and verified JSON payload rendering.

---

## 🚀 End-to-End User Flow

1. **Purchase with 14-Day Guarantee:** Buyer shops at Holloway Goods (`/store`) and pays via PayPal Sandbox.
2. **Customer Claims Portal (`/portal`):** 2–3 days later, the buyer visits the portal (or clicks quick-demo chip for Maya Chen).
3. **Live Competitor Scan:** Buyer clicks *Check Live Market Price*. Channel3 scans online retailers and confirms a price drop (e.g., Sony WH-1000XM5 down to $298.00 at B&H Photo vs. $348.00 paid).
4. **Dispute Submission:** Buyer submits a claim: *"Rather than repacking and shipping the box back, please refund the difference under 14-day price cover."*
5. **AG Grid Merchant Review (`/claims`):** The merchant sees Maya's pending claim with return risk score, costing comparison, and Channel3 evidence.
6. **Actuarial Case Report & Resolution Message:** Merchant clicks *Review & Settle*, reviews the side-by-side breakdown (saving $93+ in reverse freight, restocking fees, and open-box markdown), edits the AI-drafted message to Maya, and clicks *Approve & Issue PayPal Refund*.
7. **Instant PayPal Credit:** The refund is issued via PayPal Orders v2 Sandbox. Maya's portal instantly displays a green celebration card with the credited refund amount and the merchant's personal note.

---

## 💻 Local Setup & Running

Requirements: **Python 3.11+**, **Node.js 20+**, and **npm**.

### 1. Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- API Docs: [http://127.0.0.1:8000/api/docs](http://127.0.0.1:8000/api/docs)
- APIMatic Status: [http://127.0.0.1:8000/api/v1/apimatic/status](http://127.0.0.1:8000/api/v1/apimatic/status)

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
- Merchant Console: [http://127.0.0.1:5173/login](http://127.0.0.1:5173/login) (Credentials: `demo@dropback.local` / `dropback-demo`)
- Customer 14-Day Portal: [http://127.0.0.1:5173/portal](http://127.0.0.1:5173/portal)
- Storefront: [http://127.0.0.1:5173/store](http://127.0.0.1:5173/store)
- APIMatic MCP Sandbox: [http://127.0.0.1:5173/apimatic](http://127.0.0.1:5173/apimatic)

---

## 🧪 Verification & Testing

- **Backend Pytest Suite (10 passed):**
  ```bash
  cd backend && ../.venv/bin/pytest -v
  ```
- **Frontend TypeScript & Vite Production Build (0 errors):**
  ```bash
  cd frontend && npm run build
  ```
