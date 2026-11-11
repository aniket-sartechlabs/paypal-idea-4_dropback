# DropBack demo video

The final presentation cut is built from the already verified Sandbox purchase, live Channel3 check, merchant review, completed PayPal refund, and APIMatic captures. It does not start a new payment.

```bash
make demo-video-final
```

Output: `demo-video/out/dropback-final.mp4` (1080p, narrated). Buyer identity is masked in the PayPal and merchant-review footage. The closing buyer portal panel shows the completed `$78.01` PayPal refund and the merchant's message.

The separate automated runner below performs a new Sandbox purchase and refund. Use it only when you intend to create another Sandbox transaction.

`scenes.json` defines the scenes, narration, captions, and UI targets. The real browser recording and PayPal Sandbox approval clip come from `make sandbox-demo`; the buyer's credential fields are visually masked during capture. Generated recordings and videos are ignored by Git.

```bash
make sandbox-demo
make demo-video-check
make demo-video
```

The final file is `demo-video/out/dropback-sandbox-demo.mp4`. The builder inserts the recorded PayPal approval clip, cuts the browser recording to each scene's timing, burns in captions, and synthesizes narration locally when `espeak` or `espeak-ng` is available. The cut is checked against the configured video duration cap.

Use `make sandbox-demo ARGS="--headless"` for a hidden browser run. The walkthrough creates a real Sandbox payment and refund. If it stops after a payment step, inspect `demo-video/out/latest_run.json` and the merchant queue before attempting another run.
