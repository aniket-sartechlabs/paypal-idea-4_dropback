# DropBack

DropBack helps merchants protect the customer relationship when the price of an item falls. It matches the product through Channel3, finds recent orders that qualify, estimates the cost of a return, and presents a refund recommendation for merchant approval.

## Local setup

Requirements: Python 3.11+, Node.js 20.19+ (or 22.12+), and npm.

1. Copy `.env.example` to `.env` and fill in PayPal Sandbox credentials, a Channel3 API key, and an OpenAI or Gemini key if model-assisted explanations are wanted. The PayPal client secret and service API keys stay on the backend.
2. Start the API:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r backend/requirements-dev.txt
   cd backend
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

3. In a second terminal, start the merchant console:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. Open [http://127.0.0.1:5173](http://127.0.0.1:5173). In development, the first-run merchant login is `demo@dropback.local` / `dropback-demo`. Sample orders are clearly marked and cannot be refunded.

The API docs are at [http://127.0.0.1:8000/api/docs](http://127.0.0.1:8000/api/docs). Local development seeds a small sample catalog and order history in `dropback.db`.

## Demo flow

1. Open **Products** and run **Check live price**. Channel3 searches for a matching product, compares current new offers, stores its product ID, and creates an idempotent price-change subscription. Ongoing notifications require the signed webhook setup below.
2. If Channel3 reports a lower offer, open **Price drops** and select **Evaluate buyers**. DropBack checks the SKU, purchase date, protection window, minimum drop, remaining capture balance, refund cap, daily budget, and estimated return savings.
3. Open **Agent review**. Inspect each recommendation, then approve or reject it. Approving a real PayPal sandbox capture issues a partial refund with a stable idempotency key. Sample orders are never refundable.
4. Visit **Storefront** to create a real sandbox order. Sign in with a Personal sandbox account when PayPal opens. The amount is calculated from the server catalog; the browser cannot set order totals.

Channel3 is the primary source for market price signals. Merchant-entered price updates are also recorded so the merchant can handle changes made directly to their own catalog.

## API and runtime settings

See `.env.example` for the full list. Key settings:

- `PAYPAL_ENV=sandbox` and a sandbox `PAYPAL_BASE_URL` are enforced for local development.
- `CHANNEL3_API_KEY` is required for the core live price checks and must never be placed in frontend code.
- `CHANNEL3_WEBHOOK_SECRET` verifies Channel3 product-subscription events. In the Channel3 dashboard, register `https://YOUR_APP_HOST/api/v1/webhooks/channel3` and subscribe to `offer.price.changed` and `offer.availability.changed`. Product subscriptions start after the first successful product match. Without a public HTTPS URL and signing secret, manual live checks work but ongoing event delivery is not configured.
- `PAYPAL_WEBHOOK_ID` is the ID of the PayPal webhook registered for `/api/v1/webhooks/paypal`.
- `OPENAI_API_KEY` or `GEMINI_API_KEY` enables model-assisted return-likelihood scoring. Deterministic eligibility, caps, and final policy decisions remain authoritative; scoring falls back to rules if the model is unavailable.

The frontend does not receive either PayPal client secret or Channel3 key. `PAYPAL_CLIENT_ID` is public and is returned to the storefront only for SDK initialization.

## Production deployment

The current repository supports a **single merchant account** and a web app backed by PayPal credentials configured in the server environment. It is a production-minded single-merchant deployment foundation, not yet a PayPal multi-merchant SaaS onboarding product. Before real-money use, the merchant must complete PayPal production approval and webhook setup, and the operator must provision a public HTTPS host, database, secrets manager, backups, monitoring, and a merchant login secret.

For production:

- Set `ENVIRONMENT=production`, a long random `SECRET_KEY`, unique `MERCHANT_EMAIL` and `MERCHANT_PASSWORD`, `SESSION_COOKIE_SECURE=true`, an HTTPS `APP_BASE_URL`, and exact HTTPS `CORS_ORIGINS`.
- Set a PostgreSQL `DATABASE_URL`, for example `postgresql+psycopg://dropback:...@db-host/dropback`, and apply Alembic migrations before starting the API:

  ```bash
  cd backend
  alembic upgrade head
  ```

- Configure PayPal live credentials only after approval, with `PAYPAL_ENV=live` and the live API base URL. Configure PayPal webhook verification with the ID returned when the webhook is registered.
- Set `CHANNEL3_API_KEY` and `CHANNEL3_WEBHOOK_SECRET`, then register the public webhook endpoint in Channel3.
- Review data retention, account recovery, user provisioning, security monitoring, and legal requirements before onboarding other merchants.

The included Docker Compose setup runs the API, Nginx frontend, and PostgreSQL together. Fill in the production environment settings above plus `POSTGRES_PASSWORD`, point DNS and TLS termination at the web service, then run `docker compose up --build -d`.

Auto-refunds are disabled. A merchant decision is required for every refund. PayPal sandbox is hard-restricted to non-production deployments.

## Verification

Run backend checks with `cd backend && ../.venv/bin/pytest -q` and the frontend production build with `cd frontend && npm run build`.
