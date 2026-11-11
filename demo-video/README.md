# DropBack demo video

`scenes.json` defines the scenes, narration, captions, and UI targets. The real browser recording and PayPal Sandbox approval clip come from `make sandbox-demo`; the buyer's credential fields are visually masked during capture. Generated recordings and videos are ignored by Git.

```bash
make sandbox-demo
make demo-video-check
make demo-video
```

The final file is `demo-video/out/dropback-sandbox-demo.mp4`. The builder inserts the recorded PayPal approval clip, cuts the browser recording to each scene's timing, burns in captions, and synthesizes narration locally when `espeak` or `espeak-ng` is available. The cut is checked against the configured video duration cap.

Use `make sandbox-demo ARGS="--headless"` for a hidden browser run. The walkthrough creates a real Sandbox payment and refund. If it stops after a payment step, inspect `demo-video/out/latest_run.json` and the merchant queue before attempting another run.
