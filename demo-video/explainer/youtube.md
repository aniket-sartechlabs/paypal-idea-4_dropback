TITLE
DropBack: refund the price drop, keep the sale | PayPal AI Hackathon 2026

DESCRIPTION
When a product gets cheaper right after someone buys it, shoppers often send it back and buy it again elsewhere. The merchant pays for the return and loses the sale anyway.

DropBack is 14-day price protection for PayPal merchants. A merchant signs up, connects their own PayPal account, and DropBack plugs into the checkout they already have. The buyer checks a completed PayPal order, Channel3 finds the exact model's live price, and an AI case report weighs a partial refund against the cost of a likely return. The merchant reviews the request in an AG Grid queue and approves a PayPal refund of the difference in one click.

Everything in the demo is real, in PayPal Sandbox:
- Merchant onboarding: sign-up, connect PayPal (credentials verified, secret encrypted), orders imported from the merchant's own checkout
- Checkout, capture and refund run through the APIMatic-generated PayPal Server SDK (Orders v2, Payments v2), with idempotency keys on every refund
- Live Channel3 offers for the exact product
- AI return-risk scoring with hard policy limits that never depend on the model
- AG Grid claims queue for the merchant
- A read-only MCP server so AI agents can inspect claims

Chapters
{chapters}

Built by Sartech Labs for the PayPal AI Hackathon 2026.
Code: https://github.com/aniket-sartechlabs/paypal-idea-4_dropback

Sources: US retail returns of $890B in 2024 (16.9% of sales) are from the NRF and Happy Returns 2024 Consumer Returns report. Shopper awareness of price-adjustment policies is from Checkbook.org's survey of retailer policies. Prices, return costs and refunds in the demo come from the recorded Sandbox run; "Day 3" is an accelerated timeline.

TAGS
PayPal, PayPal Sandbox, PayPal Server SDK, APIMatic, Channel3, AG Grid, MCP, price protection, ecommerce returns, hackathon, AI agents, Sartech Labs
