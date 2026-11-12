# DropBack Demo Video Script

Generated from `demo-video/scenes.json` by `check_scenes.py`. Total 130 s (cap 175 s; clips included), 125 wpm voice-over.

| Time | Scene | Caption | Actions | Voice-over |
|---|---|---|---|---|
| 0:00-0:12 | 01_store | Holloway storefront · Sony WH-1000XM5 · 14-day protection | goto `/store?demo=sandbox`; highlight `product-SONY-WH1000XM5-BLK` | A buyer chooses the Sony headphones from Holloway Goods, with fourteen days of DropBack price protection. |
| 0:12-0:30 | 02_checkout | Real PayPal Orders v2 checkout · $398.00 | click `add-to-cart-SONY-WH1000XM5-BLK`; click `paypal-checkout-btn` | The storefront creates a real PayPal Sandbox order for the selected product and sends the buyer to PayPal checkout. |
| 0:30-0:45 | 03_paypal_approval | PayPal Sandbox buyer login and payment approval | **clip** `demo-video/clips/paypal_approval.mp4` (recorded by hand) | The automated Sandbox buyer signs in and approves the payment. PayPal captures the order before DropBack opens the buyer portal. |
| 0:45-1:03 | 04_price_check | Scenario replay · Day 3 · live Channel3 offer | highlight `portal-page`; click `price-check-btn` | In an accelerated third-day scenario, the buyer asks Channel3 to check the exact model against current in-stock offers. |
| 1:03-1:17 | 05_buyer_claim | Buyer requests the verified price difference | click `submit-claim-btn` | Channel3 finds a lower price. The buyer submits the live evidence and asks for the verified difference instead of returning the item. |
| 1:17-1:42 | 06_case_report | Merchant review · AG Grid case queue and AI report | goto `/claims`; click `settle-btn`; highlight `key-drivers` | The merchant reviews the buyer note, verified market offer, return probability, return costs, and a clearly drafted message in AG Grid. |
| 1:42-1:58 | 07_refund_result | Merchant approval · PayPal Payments v2 refund | click `approve-refund-btn`; goto `/portal` | After merchant approval, DropBack sends the difference to the buyer through PayPal Payments v2 with a request idempotency key. |
| 1:58-2:10 | 08_apimatic | PayPal Server SDK by APIMatic · Orders v2 and Payments v2 | goto `/apimatic`; highlight `apimatic-page` | Every PayPal call, from order to capture to refund, runs through the APIMatic-generated PayPal Server SDK, and DropBack exposes read-only tools over MCP. |
