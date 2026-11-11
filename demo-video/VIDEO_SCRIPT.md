# DropBack Demo Video Script

Generated from `demo-video/scenes.json` by `check_scenes.py`. Total 161 s (cap 175 s; clips included), 125 wpm voice-over.

| Time | Scene | Caption | Actions | Voice-over |
|---|---|---|---|---|
| 0:00-0:12 | 01_hook | Product returns cost merchants 25% of retail value. | goto `/store`; highlight `brand`; highlight `store-page` | Product returns cost merchants 25% of sale price. When prices drop, customers dispute and return items to rebuy cheaper. |
| 0:12-0:28 | 02_buy | Sony WH-1000XM5: 14-Day DropBack Price Protection | highlight `paypal-checkout-btn`; click `paypal-checkout-btn` | Maya buys the Sony WH-1000XM5 headphones for $398 with 14 days of automatic DropBack price protection via PayPal. |
| 0:28-0:43 | 03_paypal_approval | Real PayPal Sandbox Payment Approval | **clip** `demo-video/clips/paypal_approval.mp4` (recorded by hand) | PayPal Sandbox authorizes and captures the order securely. Maya receives instant order confirmation with full protection. |
| 0:43-1:01 | 04_portal_check | Day 3: Customer Portal triggers live Channel3 price check | goto `/portal/sample-order-maya-sony`; highlight `portal-page`; click `price-check-btn` | Three days later, Maya visits the Customer Portal. She clicks check market price, and Channel3 detects a $100 price drop at B&H Photo. |
| 1:01-1:15 | 05_claim | Request Difference Refund — No return shipping or hassle | wait; click `submit-claim-btn` | Instead of mailing back the headphones, Maya requests a $100 price match refund under her 14-day guarantee. |
| 1:15-1:35 | 06_merchant_grid | AG Grid Console: 86% Return Risk, Case Cost Comparison | goto `/claims`; highlight `claims-banner`; highlight `claims-grid`; highlight `channel3-evidence`; highlight `risk-gauge` | In the AG Grid merchant console, Maya's claim appears with live Channel3 evidence, an 86% return risk gauge, and pre-calculated return costs. |
| 1:35-1:57 | 07_ai_report | AI Case Report: Returning costs $151.80 vs Settle $100. Saves $51.80 | click `settle-btn`; wait_for `claim-modal`; highlight `key-drivers` | The merchant opens the case. AI compares $151.80 in physical return shipping and open-box depreciation against a $100 difference refund, saving $51.80 in margin. |
| 1:57-2:11 | 08_approve | 1-Click Settle: AI drafts note, PayPal issues partial refund | highlight `approve-refund-btn`; click `approve-refund-btn` | With an AI-drafted resolution message ready, the merchant clicks Approve. DropBack executes a partial refund on the PayPal capture. |
| 2:11-2:25 | 09_confirmed | Customer Portal: Refund credited to PayPal account | goto `/portal/sample-order-maya-sony`; highlight `portal-page` | The refund immediately reflects in Maya's PayPal account. Maya keeps her headphones, and the merchant protects their margin. |
| 2:25-2:41 | 10_apimatic | APIMatic MCP Protocol: Validated PayPal Orders & Payments v2 | goto `/apimatic`; highlight `apimatic-page`; click `mcp-execute-btn`; highlight `mcp-response` | APIMatic context plugins eliminate LLM hallucinations with validated PayPal OpenAPI schemas, powering live MCP sandbox tool execution. |
