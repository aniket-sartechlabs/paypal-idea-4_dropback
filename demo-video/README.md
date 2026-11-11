# DropBack Demo Video Tooling

`scenes.json` is the single source of truth for the demo video: captions, narration, UI actions (anchored by `data-testid`), and durations.
The entire cut, including the recorded PayPal sandbox clip, stays **at or under 175 s** (under the 3-minute hackathon hard limit).

| Command | What it does |
|---|---|
| `make demo-video-check` (`python scripts/tasks.py demo-video-check`) | Validates `scenes.json` (durations, <= 125 wpm voiceover, verified `data-testid` in UI components), outputs `VIDEO_SCRIPT.md`. |
| `make demo-video` (`python scripts/tasks.py demo-video`) | `build_video.py`: cuts screen scenes and clips into `demo-video/out/demo_silent.mp4` using ffmpeg. |

## The PayPal Sandbox Approval Clip (`03_paypal_approval`)

The PayPal checkout window is PayPal's official sandbox authentication site (`sandbox.paypal.com`).
The 15-second clip can be recorded or auto-run with `python scripts/sandbox_buyer.py`:
- File: `demo-video/clips/paypal_approval.mp4` (gitignored).
- At most 15 seconds.
