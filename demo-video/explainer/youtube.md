TITLE
DropBack: Refund the Price Drop, Keep the Sale | PayPal × Channel3 | PayPal AI Hackathon 2026

DESCRIPTION
A shopper pays $398. Three days later it's $298 somewhere else, so they return it and buy it again. The merchant eats a ~$291 return to avoid a $100 gap. DropBack fixes that with one PayPal refund.

DropBack is 14-day price protection for PayPal merchants. It plugs into the checkout a merchant already has. When a price drops, Channel3 proves it with the exact model's live offers and price history. An AI case report weighs a partial refund against the cost of a likely return. The merchant approves a PayPal refund of the difference in one click. The buyer keeps the item; the merchant keeps the sale.

▶ Try it: https://dropback-i3yz.onrender.com
▶ Code (MIT): https://github.com/sartech-labs/paypal-idea-4_dropback

━━━━━━━━━━━━━━━━━━━━
WHAT YOU'RE SEEING IS REAL
━━━━━━━━━━━━━━━━━━━━
No mock data: the merchant sign-up, PayPal payment, Channel3 prices and PayPal refund in this video are one continuous run in PayPal Sandbox with live Channel3 data. Only the calendar is accelerated ("Day 3").

━━━━━━━━━━━━━━━━━━━━
HOW IT'S BUILT
━━━━━━━━━━━━━━━━━━━━
PayPal
• Orders v2 + Payments v2 through the APIMatic-generated PayPal Server SDK (typed models, SDK-managed OAuth)
• Every refund carries an idempotency key, so a retry can never pay twice
• Merchants connect their own PayPal app: credentials verified with PayPal, secret encrypted at rest, webhook registered for them; paid orders from their existing checkout are imported automatically

Channel3: the evidence behind every refund
• Search filtered by Channel3 to new, in-stock offers for the exact model, from the retailers the merchant price-matches
• 90-day price history and Channel3's low / typical / high rating, shown to the buyer, the merchant and the AI
• Retailer details (name and logo), product lookup by URL, product subscriptions with signed webhooks, and price tracking

AI with guardrails
• Return risk starts from a rule model; OpenAI can adjust it by at most ±0.15 and writes the case report and buyer message
• The buyer's note is treated as untrusted input
• Refund caps, the protection window and the daily budget are enforced in code, never by the model, and a person approves every refund

Merchant experience
• Sign-up and a 5-step setup wizard, an AG Grid claims queue, a case report comparing return-and-rebuy cost (shipping, restocking, markdown, lost sale) with the refund
• A read-only MCP server so AI agents can inspect claims; deployed as one service on Render

━━━━━━━━━━━━━━━━━━━━
CHAPTERS
━━━━━━━━━━━━━━━━━━━━
0:00 DropBack, powered by PayPal × Channel3
0:08 The $890B returns problem
0:24 Why a return costs more than the difference
0:35 How DropBack works
0:49 Merchant sign-up and setup
1:06 Shopper checks out with PayPal
1:23 Day 3: live price check
1:29 Channel3 finds the exact model cheaper
1:40 Verified by Channel3: price history
1:51 Buyer asks for the difference
1:57 Merchant queue in AG Grid
2:01 AI case report and the numbers
2:17 One-click PayPal refund
2:25 Buyer keeps the item, merchant keeps the sale
2:30 Under the hood: Server SDK, MCP, Render
2:39 Why it matters

━━━━━━━━━━━━━━━━━━━━
Built by Sartech Labs for the PayPal AI Hackathon 2026.

Sources: US retail returns of $890B in 2024 (16.9% of sales): NRF and Happy Returns, 2024 Consumer Returns report. Shopper awareness of price-adjustment policies: Checkbook.org's survey of retailer policies. All prices, return costs and refunds come from the recorded Sandbox run.

TAGS
PayPal, PayPal Developer, PayPal Sandbox, PayPal Server SDK, PayPal AI Hackathon, Channel3, APIMatic, AG Grid, Render, MCP, Model Context Protocol, AI agents, agentic commerce, price protection, price matching, ecommerce returns, retail returns, merchant tools, fintech, hackathon demo, Sartech Labs
