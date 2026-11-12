# DropBack · 14-day price protection for PayPal merchants

When a product gets cheaper right after someone buys it, shoppers often return it and buy it again elsewhere. The merchant pays for the return and loses the sale anyway. DropBack plugs into a merchant's existing PayPal checkout: the buyer checks their order, **Channel3** finds the exact model's live price and price history, an AI case report weighs a partial refund against a likely return, and the merchant approves a **PayPal** refund of the difference in an **AG Grid** queue.

Built for the PayPal AI Hackathon 2026 with the PayPal, Channel3, AG Grid, and APIMatic sponsor integrations.

**At a glance**

| | |
| :--- | :--- |
| Payments | PayPal Orders v2 + Payments v2 in Sandbox, through the APIMatic-generated PayPal Server SDK; idempotency keys on every refund |
| Market evidence | Channel3: search with retailer filters, price history, retailer details, URL lookup, product subscriptions, price tracking, signed webhooks |
| Decision | Rule baseline + OpenAI (bounded to ±0.15), with hard policy limits in code; a person approves every refund |
| Merchant UI | Sign-up, 5-step setup wizard, AG Grid claims queue, case report, PayPal API lab |
| Agents | Read-only DropBack MCP server; APIMatic Context Plugin for coding agents |
| Deploy | One Docker service + Postgres on Render (`render.yaml`) |
| Tests | `cd backend && pytest` (37 tests, including a migrations-match-models check) |

## For judges

- **Demo video (under 3 minutes):** see the YouTube link in the Devpost submission.
- **Try it hosted:** the Render URL and merchant login are in the Devpost testing instructions. Buy in `/store` with a PayPal **Sandbox personal** account, request the difference in `/portal`, and approve it in the merchant console (`/login` → Claims).
- **Run it yourself:** `cp .env.example .env`, add PayPal Sandbox and Channel3 keys, `make setup && make dev`, open http://127.0.0.1:5173. Tests: `cd backend && pytest`.
- **Built during the hackathon:** merchant sign-up and setup wizard, connect-your-own-PayPal with order import, Channel3 evidence (price history, retailer details, URL lookup, approved-retailer filters, tracking), the lost-sale return economics, the PayPal Server SDK migration and MCP server, and the single-service Render deployment.
- **License:** MIT (see `LICENSE`).

## How a merchant uses DropBack

DropBack is an add-on to a merchant's existing PayPal checkout, not a new store.

1. **Sign up** at `/login` → "Create a merchant workspace" (store name, email, password). One owner per workspace; the password is stored as a PBKDF2 hash.
2. **Connect PayPal** in the setup wizard (`/setup`): paste the REST app client ID and secret from developer.paypal.com. DropBack verifies them with an OAuth token request, stores the secret encrypted (Fernet, keyed from `SECRET_KEY`), and runs every Orders v2 / Payments v2 call as that merchant. On a public HTTPS deployment it also registers DropBack's webhook on the merchant's app.
3. **Orders come in from the merchant's own checkout:**
   - `PAYMENT.CAPTURE.COMPLETED` webhooks import the paid order automatically (needs public HTTPS).
   - A buyer can open `/portal` with their PayPal order ID and email; an order DropBack has not seen is fetched from PayPal with the merchant's credentials, so only orders paid to that merchant can be imported.
   - The merchant can import an order by ID from the wizard (`POST /api/v1/orders/import`).
   Items are matched to the protected catalog by SKU, then by name.
4. **Set the policy:** protection window, per-order cap, daily budget, the retailers they price-match (empty = any in-stock new offer), and the return-cost model including gross margin.
5. **Pick products** from the live Channel3 catalog, then **go live**: the wizard gives the buyer-portal link and a line for the order-confirmation email.
6. **Day to day:** claims arrive in the AG Grid queue with Channel3 evidence and the AI case report; every refund needs the merchant's click.

The case report compares a refund with what a return-and-rebuy costs: return shipping + restocking + open-box markdown + the margin on the lost sale, weighted by the return probability. The refund is recommended only when that expected loss exceeds it.

The bundled Holloway storefront stands in for the merchant's existing store in the demo.

## The real buyer-to-merchant flow

1. The buyer selects an item in the Holloway storefront and checks out through PayPal Orders v2 in Sandbox.
2. The automated walkthrough signs into the PayPal Sandbox buyer account using credentials stored only in the ignored local `.env` file, then approves and captures the order.
3. The buyer portal opens the captured order. The demo presents an accelerated Day 3 scenario, checks the exact product against live Channel3 offers, and submits the buyer's request with that evidence.
4. The merchant reviews the case in AG Grid, including the buyer note, Channel3 offer, AI return likelihood, estimated return costs, and a drafted response.
5. Merchant approval calls PayPal Payments v2 to refund the verified price difference to the captured Sandbox payment. The app records the returned PayPal status and refund ID.
6. The buyer portal shows the resulting claim and refund status. No seeded buyer orders or local-only sample refunds are used in this walkthrough.

The Sandbox walkthrough creates a real test payment and refund in the configured PayPal Sandbox account. Run it once per intended demo; inspect `demo-video/out/latest_run.json` and the merchant dashboard before attempting recovery after an interrupted run.

## Sponsor integrations

### Channel3

Channel3 is the evidence behind every refund. DropBack never pays on a buyer's word or a screenshot: the offer, the retailer, and the price history all come from Channel3, live, for the exact model.

| Channel3 API | Where DropBack uses it |
| :--- | :--- |
| `POST /v1/search` with `filters` (`conditions: new`, `availability: InStock`, `website_ids` = the merchant's approved retailers) | Buyer price check and merchant catalog checks: lowest new, in-stock offer for the exact model, only from retailers the merchant price-matches |
| `GET /v0/price-tracking/history/{id}` | 90-day price chart and low/average/high/"typical" rating in the buyer's price check and the merchant's case report; the same facts go to the AI as market context (is this a lasting price or a blip?) |
| `GET /v1/websites/{domain}` | Retailer name and logo on the evidence ("Beach Camera", not just a domain) |
| `POST /v1/lookup` | Merchant adds a product by pasting any product page URL; Channel3 resolves the exact product |
| `GET /v1/products/{id}` | Verifies a selected listing before it is added, and refreshes it when a webhook arrives |
| `POST /v1/product-subscriptions` + signed webhooks (`offer.price.changed`, `offer.availability.changed`, …) | Every linked product is watched; a verified (Svix-signed) event creates a price signal the merchant can evaluate against all eligible orders |
| `POST /v0/price-tracking/start` | Started for every linked product so its price history keeps building |

Guardrails: an offer must be explicitly `new` and in stock; titles must match the merchant's product; buyer price checks are rate-limited and never change the merchant's catalog; when Channel3 is unavailable, no claim is created (no saved fixture is substituted). See `backend/app/services/channel3.py`.

### AG Grid

- `/claims` is the merchant's actual case queue. Columns show the buyer/order, product, current Channel3 offer, return-versus-settle economics, status, and resolution.
- Merchants can sort, resize, filter, and inspect rows, then open a case for the evidence and AI report before choosing a resolution.
- The grid uses separate compact column sizing and clipped/wrapped cell content to remain readable at narrower widths.

### APIMatic: PayPal Server SDK and MCP

- **Every PayPal call uses the APIMatic-generated [PayPal Server SDK](https://pypi.org/project/paypal-server-sdk/)** (`paypalserversdk`): `orders.create_order`, `orders.capture_order`, `orders.get_order`, `payments.refund_captured_payment`, `payments.get_captured_payment`, and `payments.get_refund`. Requests are built from the SDK's typed models (`OrderRequest`, `PurchaseUnitRequest`, `Item`, `Money`, `RefundRequest`), and the SDK manages OAuth. See `backend/app/services/paypal.py`. The only call outside the SDK is PayPal webhook signature verification, which the SDK doesn't cover.
- **DropBack MCP server** at `http://127.0.0.1:8000/mcp/` (streamable HTTP, `Authorization: Bearer $MCP_API_TOKEN`). It exposes read-only tools: `paypal_check_sandbox_health`, `paypal_get_order_details`, `paypal_get_capture_status`, `dropback_list_claims`, and `dropback_get_claim`. Refunds are deliberately not available over MCP; money only moves after a merchant clicks approve.
- **APIMatic Context Plugin** (`https://chatbotapi.apimatic.io/mcp/plugins`) is registered in `.mcp.json`. AI coding agents such as Claude Code or Cursor get current PayPal Server SDK docs and samples while working on this repository.
- `/apimatic` (the PayPal API lab) lists the SDK operations, shows MCP status, and runs the SDK tools against Sandbox. A manual refund there needs a fresh idempotency key per refund and respects the capture balance, per-order cap, and daily budget.

## Security model

- **Merchant console:** the workspace owner created at sign-up, or `MERCHANT_EMAIL` / `MERCHANT_PASSWORD` from `.env`; signed httponly cookie, rate-limited attempts.
- **Merchant PayPal credentials:** verified before saving, secret encrypted at rest, never returned by the API (the client ID is masked).
- **Buyers:** the browser that starts a checkout can open that order. From any other browser, the buyer signs in at `/portal` with the order ID and the email on their PayPal account. Order lookup, price checks, claims, and claim status all require that buyer session (or a merchant session).
- Channel3 search, the product catalog API, and the PayPal API lab are merchant-only. Buyer price checks are rate-limited per order and never change the merchant's catalog data.

## AI scoring

The return-likelihood score starts from a rule-based model (category, size of the drop, days since purchase). With `OPENAI_API_KEY` (or `GEMINI_API_KEY` and `LLM_PROVIDER=gemini`) set in `.env`, `gpt-4.1-mini` reviews the case, drafts the buyer message, and can move the score by at most ±0.15. The buyer's note is passed to the model as fenced, untrusted text. Policy checks (window, minimum drop, caps, budget) never depend on the model. Without a key, the rule model is used and the case report says so.

## Setup

Requirements: Python 3.11+, Node.js, npm, and (for video rendering) `ffmpeg` plus `ffprobe`.

```bash
cp .env.example .env
make setup
```

Set the PayPal Sandbox client ID and secret, Channel3 API key, and Sandbox buyer email/password in `.env`. Optionally set `OPENAI_API_KEY` (AI scoring) and `MCP_API_TOKEN` (MCP server). The buyer credentials are consumed only by the local Playwright runner; they are not sent to the browser app. Keep `.env` private. The runner refuses to transact unless PayPal is configured for the official Sandbox API endpoint.

Development uses SQLite (`dropback.db`, created on first start). If you ran an earlier version, delete `dropback.db` or run `alembic upgrade head` in `backend/` so the schema includes the new columns.

Start the API and frontend with hot reload:

```bash
make dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The local merchant preview is available at `/login`; the buyer storefront is `/store`; the buyer portal is `/portal`; the merchant queue is `/claims`; and the API lab is `/apimatic`.

For the one-click-free automated presentation, open [http://127.0.0.1:5173/demo/run](http://127.0.0.1:5173/demo/run). Visiting this dedicated URL starts the full Sandbox buyer-to-merchant run and opens its browser window; there is no launcher button in the merchant navigation. Keep the launch page and demo browser open. The launcher is local-development-only and refuses production or non-Sandbox PayPal settings. It performs a real Sandbox purchase and refund.

## Run and record the real Sandbox walkthrough

```bash
make sandbox-check
make sandbox-demo
make demo-video-check
make demo-video
```

`make sandbox-demo` performs one PayPal Sandbox purchase, runs a live Channel3 check, submits a claim, approves the merchant refund, and records the browser flow. Add `ARGS="--headless"` for a hidden browser, or set `ARGS="--slow-mo 180"` for a slower presentation. It records `demo-video/out/screen.webm`, the same-window PayPal modal approval clip, stage timings, and a redacted run report. Launch output is logged to `logs/sandbox-demo-runner.log`; the outcome is saved to `demo-video/out/latest_run.json`. `make demo-video` combines those real recordings with captions and optional local narration into `demo-video/out/dropback-sandbox-demo.mp4`.

If a run stops after payment creation or capture, use the saved report and the PayPal order in the merchant view to inspect its status before starting another run. The runner records partial progress to help with that recovery.

## Developer commands

- `make api` runs only the FastAPI server.
- `make frontend` runs only the Vite frontend.
- `make watch` is an alias for `make dev`.
- `make sandbox-check` checks local PayPal/Channel3 readiness without creating an order.
- `make demo-video-check` validates scene targets, narration timing, and the hackathon video duration.
- `make submission-check` validates the video scenes, builds the frontend, and checks integration configuration.

The demo timeline accelerates the real 14-day protection period into a clearly labeled Day 3 scenario; it does not alter PayPal's payment or refund behavior.

## Deploy to Render

`render.yaml` is a Render Blueprint: one Docker web service (the root `Dockerfile` builds the React app and FastAPI serves it, so the buyer portal, merchant console, API, MCP endpoint, and PayPal webhook share one HTTPS URL) plus a free Render Postgres database. Migrations run on every start (`alembic upgrade head`).

1. Render dashboard → **New → Blueprint** → select this repository.
2. Fill in the values marked `sync: false`:
   - `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`: a PayPal **Sandbox** REST app (or leave them empty and connect PayPal from the setup wizard after signing up).
   - `CHANNEL3_API_KEY` (required), `OPENAI_API_KEY` (optional; rule scoring without it).
   - `SIGNUP_CODE`: the invite code needed to create the merchant workspace. Without it, production sign-up is closed.
   - Optional: `MERCHANT_EMAIL` / `MERCHANT_PASSWORD` for a fixed console login, `PAYPAL_WEBHOOK_ID`, `CHANNEL3_WEBHOOK_SECRET`.
3. Deploy. `SECRET_KEY` and `MCP_API_TOKEN` are generated by Render; `APP_BASE_URL` defaults to the service's `RENDER_EXTERNAL_URL`. `DEMO_CATALOG=true` seeds the Sony / AirPods / Kindle catalog on an empty database.
4. Open `https://<service>.onrender.com/login` → **Create a merchant workspace** with the invite code → the setup wizard. In **Products to protect**, click **Link products with Channel3**: the public store lists only products linked to a live Channel3 listing. Connecting PayPal there registers the webhook `https://<service>.onrender.com/api/v1/webhooks/paypal` on that PayPal app, so paid orders are imported automatically.

**Judge access:** set `MERCHANT_EMAIL` / `MERCHANT_PASSWORD` on Render and share them (with a PayPal Sandbox *personal* buyer login for checkout) in the submission notes. Judges can then buy in `/store`, request the difference in `/portal`, and approve it in the merchant console.

The free web service sleeps when idle; the first request after a pause takes about a minute.

To run the same image locally: `docker build -t dropback . && docker run -p 8000:8000 --env-file .env -e ENVIRONMENT=production -e APP_BASE_URL=https://localhost dropback` (with a Postgres `DATABASE_URL`), or use `docker compose up` for the separate nginx + API + Postgres setup.
