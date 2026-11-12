# DropBack demo video (16:9, 1920x1080, for YouTube)

The same pipeline as the SARA (idea 1) video: real PayPal Sandbox screen recordings plus animated explainer scenes, word-synced captions, the Sariga voice from ElevenLabs, and synthesized music and sound effects (no third-party audio), mixed to -14 LUFS.

| File | What it does |
| :--- | :--- |
| `storyboard.template.json` | Every scene: the ElevenLabs line (`say`, with v3 tags), caption (`*accent*` words, ` / ` page breaks), theme (`paper` for the problem, `midnight` for DropBack), chapter, and visual. Recording scenes name a start and end mark; prices use `{paid}`, `{offer}`, `{diff}`, `{retailer}`, `{return_cost}`, `{probability}`, `{refund}`. |
| `record_live.py` | Records the real Sandbox flow in a visible browser at 1600x900: store → PayPal checkout → buyer price check (Channel3) and request → merchant AG Grid queue → AI case report → approve (PayPal refund) → buyer sees the refund → overview → API lab. Saves `video-out/rec_live/live.webm`, `marks.json`, `rects.json` and `facts.json`. Uses the Sandbox buyer from `.env` and masks it on screen. `--paypal-proof` also records the buyer's PayPal activity; a person signs in there. |
| `make_storyboard.py` | Fills the template with the run's numbers, clip timings and highlight boxes → `storyboard.json`, and writes `vo_sariga.txt` for ElevenLabs. `--sample` makes a graphics-only preview with sample numbers. |
| `import_take.py` | Splits one ElevenLabs MP3 into per-scene narration using Whisper word timings. |
| `engine.html` | The deterministic frame renderer (from idea 1, rebranded: DropBack mark, teal/mint palette). |
| `build.py` | Voice (OpenAI TTS fallback), recording frames sped to fit each line, every frame rendered in Chromium → H.264, then music, effects and voice mixed. Also writes the `.srt` captions and `.youtube.txt` (title, description, chapters). |

## Make the video

Prerequisites in `.env`: PayPal Sandbox client ID/secret, `PAYPAL_SANDBOX_BUYER_EMAIL` / `PAYPAL_SANDBOX_BUYER_PASSWORD`, `CHANNEL3_API_KEY`, and `OPENAI_API_KEY` (Whisper timings and the TTS fallback).

```bash
# 1. Record (creates one real Sandbox payment and refund). API and frontend are started if needed.
python demo-video/explainer/record_live.py

# 2. Storyboard and the Sariga script from the run's real numbers
python demo-video/explainer/make_storyboard.py

# 3. Paste demo-video/explainer/vo_sariga.txt into ElevenLabs (voice: Sariga, Eleven v3), download the MP3, then:
python demo-video/explainer/import_take.py ~/Downloads/<take>.mp3 --storyboard storyboard.json

# 4. Check a few scenes, then render everything
python demo-video/explainer/build.py --storyboard storyboard.json --skip-voice --only-preview R05,R08 --at boxes
python demo-video/explainer/build.py --storyboard storyboard.json --skip-voice
```

Output: `video-out/dropback-demo.mp4`, `.srt` (upload as YouTube captions) and `.youtube.txt`. Without step 3, drop `--skip-voice` to use OpenAI TTS (voice `marin`) instead.

## Sources for on-screen facts

| Claim | Source |
| :--- | :--- |
| $890B US retail returns in 2024, 16.9% of sales | [NRF and Happy Returns, 2024 Consumer Returns report](https://nrf.com/media-center/press-releases/nrf-and-happy-returns-report-2024-retail-returns-total-890-billion) |
| Most shoppers don't know price-adjustment policies exist; return-and-rebuy as the workaround | [Checkbook.org, price-matching and price-adjustment policies](https://www.checkbook.org/washington-area/pricematching/) |
| Paid price, Channel3 offer, return-cost estimate, return risk, refund | The recorded Sandbox run (`video-out/rec_live/facts.json`) |
