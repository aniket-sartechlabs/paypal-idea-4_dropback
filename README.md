# DropBack · 14-day price protection

DropBack helps a merchant retain a sale when an item becomes cheaper soon after purchase. A buyer checks a completed PayPal order, Channel3 looks up current offers, and the buyer sends a price-match request. The merchant reviews the evidence, return-risk estimate, and cost comparison in an AG Grid queue, then can send a drafted message or approve a refund to the original PayPal payment.

This prototype is designed for the PayPal AI Hackathon and demonstrates the AG Grid, Channel3, and APIMatic sponsor integrations.

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

- Merchant catalog search discovers Channel3 listings and imports a selected product using its live product ID.
- The walkthrough verifies an exact live product match before checkout. A buyer price check queries Channel3 again and records the observed offer and source with the claim.
- Claims require a completed PayPal capture and live Channel3 evidence. No saved offer fixture is substituted when a live lookup fails.

### AG Grid

- `/claims` is the merchant's actual case queue. Columns show the buyer/order, product, current Channel3 offer, return-versus-settle economics, status, and resolution.
- Merchants can sort, resize, filter, and inspect rows, then open a case for the evidence and AI report before choosing a resolution.
- The grid uses separate compact column sizing and clipped/wrapped cell content to remain readable at narrower widths.

### APIMatic Context Plugin

- `.context-plugins/paypal.json` is the source for the PayPal API contract and MCP tool schemas shown in the app.
- `/apimatic` displays the manifest and exposes DropBack's authenticated server-side bridge for PayPal Sandbox health, order lookup, capture lookup, and manual refund calls.
- The bridge executes against PayPal Sandbox; this prototype does not claim to use an APIMatic-hosted runtime. Manual refunds are constrained to known merchant captures and the remaining capture balance.

## Setup

Requirements: Python 3.11+, Node.js, npm, and (for video rendering) `ffmpeg` plus `ffprobe`.

```bash
cp .env.example .env
make setup
```

Set the PayPal Sandbox client ID and secret, Channel3 API key, and Sandbox buyer email/password in `.env`. The buyer credentials are consumed only by the local Playwright runner; they are not sent to the browser app. Keep `.env` private. The runner refuses to transact unless PayPal is configured for the official Sandbox API endpoint.

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
