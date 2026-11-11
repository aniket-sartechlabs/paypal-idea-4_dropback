"""Run the real PayPal Sandbox buyer-to-merchant walkthrough.

The buyer credentials are read only from the ignored project .env file. The run
uses the storefront and PayPal checkout UI, fetches a live Channel3 offer, opens
the merchant review case, issues the PayPal capture refund, and records video.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout, async_playwright

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://127.0.0.1:5173"
API = f"{BACKEND}/api/v1"
OUT = ROOT / "demo-video" / "out"
RECORDINGS = OUT / "recordings"
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402

SONY_SKU = "SONY-WH1000XM5-BLK"
STAGES: list[dict[str, Any]] = []
stage_clock = time.monotonic()


def stage_start(scene_id: str, title: str, detail: str) -> None:
    global stage_clock
    if STAGES and STAGES[-1].get("end") is None:
        STAGES[-1]["end"] = round(time.monotonic() - stage_clock, 2)
    STAGES.append({"id": scene_id, "title": title, "detail": detail, "start": round(time.monotonic() - stage_clock, 2), "end": None})
    print(f"[{scene_id}] {title}", flush=True)


def stage_finish() -> None:
    if STAGES and STAGES[-1].get("end") is None:
        STAGES[-1]["end"] = round(time.monotonic() - stage_clock, 2)


async def show_caption(page: Page, title: str, detail: str) -> None:
    await page.evaluate(
        """([title, detail]) => {
          let box = document.getElementById('dropback-demo-caption');
          if (!box) {
            box = document.createElement('div');
            box.id = 'dropback-demo-caption';
            box.style.cssText = 'position:fixed;z-index:2147483000;left:50%;bottom:18px;transform:translateX(-50%);width:min(760px,calc(100vw - 36px));padding:12px 16px;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:rgba(24,37,39,.93);color:#fff;box-shadow:0 12px 36px rgba(18,30,30,.24);font:600 13px/1.4 system-ui,-apple-system,sans-serif;pointer-events:none;backdrop-filter:blur(12px)';
            const heading = document.createElement('div'); heading.dataset.role='heading'; heading.style.cssText='font-weight:750;letter-spacing:.02em';
            const sub = document.createElement('div'); sub.dataset.role='detail'; sub.style.cssText='font-size:11px;font-weight:450;color:#c5d4ce;margin-top:3px';
            box.append(heading, sub); document.body.append(box);
          }
          box.querySelector('[data-role=heading]').textContent = title;
          box.querySelector('[data-role=detail]').textContent = detail;
        }""",
        [title, detail],
    )


async def find_visible(page: Page, selectors: tuple[str, ...], timeout_ms: int = 600) -> Any | None:
    for frame in page.frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector).first
                await locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception:
                continue
    return None


async def click_first(page: Page, selectors: tuple[str, ...], label: str | None = None) -> bool:
    locator = await find_visible(page, selectors)
    if locator is not None:
        await locator.click(timeout=8000)
        return True
    if label:
        for frame in page.frames:
            try:
                locator = frame.get_by_role("button", name=re.compile(label, re.I)).first
                await locator.wait_for(state="visible", timeout=500)
                await locator.click(timeout=8000)
                return True
            except Exception:
                continue
    return False


async def approve_sandbox_page(page: Page, email: str, password: str) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
    except PlaywrightTimeout:
        pass

    email_input = await find_visible(page, ("#email", "input[name='email']", "input[type='email']", "input[autocomplete='username']", "input[placeholder*='email' i]"), 350)
    if email_input is not None:
        await email_input.fill(email)
        if not await click_first(page, ("#btnNext", "button[name='next']"), r"^next$"):
            raise RuntimeError("PayPal Sandbox sign-in did not show its Next button.")

    password_input = await find_visible(page, (
        "#password", "input[name='password']", "input[type='password']",
        "input[autocomplete='current-password']", "input[placeholder*='password' i]",
    ), 900)
    if password_input is None:
        for frame in page.frames:
            try:
                password_input = frame.get_by_label(re.compile("password", re.I)).first
                await password_input.wait_for(state="visible", timeout=500)
                break
            except Exception:
                password_input = None
    if password_input is not None:
        await password_input.fill(password)
        if not await click_first(page, ("#btnLogin", "button[name='login']", "button[type='submit']"), r"sign in|log in|continue"):
            raise RuntimeError("PayPal Sandbox sign-in did not show its login button.")
        print("  PayPal Sandbox password submitted.", flush=True)
    else:
        # Report the UI structure without exposing field values or page text.
        frame_info = []
        for frame in page.frames:
            if "paypal.com" not in frame.url.lower():
                continue
            try:
                frame_info.append({"host": frame.url.split("/")[2], "password_inputs": await frame.locator("input[type=password],input[autocomplete=current-password]").count(), "buttons": await frame.locator("button").count()})
            except Exception:
                continue
        print(f"  PayPal sign-in fields not detected; safe frame diagnostics: {frame_info}", flush=True)

    await page.wait_for_timeout(1400)
    selectors = (
        "#consentButton",
        "button[data-testid='consentButton']",
        "#confirmButtonTop",
        "#payment-submit-btn",
        "button[name='continue']",
    )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if await click_first(page, selectors, r"agree|continue|pay now|complete purchase|confirm|approve"):
            print("  PayPal Sandbox buyer approved the checkout.", flush=True)
            return
        for frame in page.frames:
            try:
                text = (await frame.locator("body").inner_text(timeout=500)).lower()
                if "payment approved" in text or "you approved" in text:
                    return
            except Exception:
                pass
        await page.wait_for_timeout(350)
    raise RuntimeError("PayPal Sandbox approval control did not appear; no payment was captured by the runner.")


async def wait_for_paypal_frame(page: Page, timeout_seconds: int = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if any("paypal.com" in frame.url.lower() for frame in page.frames if frame != page.main_frame):
            return
        await page.wait_for_timeout(250)
    raise RuntimeError("PayPal Sandbox did not open inside the storefront checkout modal.")


def _redact(message: str, settings: Settings) -> str:
    for secret in (
        settings.paypal_sandbox_buyer_email,
        settings.paypal_sandbox_buyer_password,
        settings.paypal_client_secret,
        settings.channel3_api_key,
    ):
        if secret:
            message = message.replace(secret, "[redacted]")
    return message


def preflight(settings: Settings) -> None:
    if settings.environment.lower() == "production":
        raise RuntimeError("Refusing to run a demo from a production application environment.")
    if settings.paypal_env.lower() != "sandbox" or "api-m.sandbox.paypal.com" not in settings.paypal_base_url.lower():
        raise RuntimeError("Refusing to run: PayPal is not configured for the Sandbox endpoint.")
    if not settings.paypal_ready:
        raise RuntimeError("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in the ignored project .env file.")
    if not settings.paypal_sandbox_buyer_email or not settings.paypal_sandbox_buyer_password:
        raise RuntimeError("Set the PayPal Sandbox buyer email and password in the ignored project .env file.")
    if not settings.channel3_api_key:
        raise RuntimeError("Set CHANNEL3_API_KEY before starting the real buyer walkthrough.")


def _service_ready(url: str) -> bool:
    try:
        response = httpx.get(url, timeout=2)
        return response.is_success
    except httpx.HTTPError:
        return False


def ensure_services() -> list[subprocess.Popen]:
    OUT.mkdir(parents=True, exist_ok=True)
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    children: list[subprocess.Popen] = []

    if not _service_ready(f"{BACKEND}/api/v1/health"):
        log_file = (log_dir / "backend.log").open("ab")
        children.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
            cwd=ROOT / "backend", stdout=log_file, stderr=subprocess.STDOUT,
        ))
    if not _service_ready(FRONTEND):
        log_file = (log_dir / "frontend.log").open("ab")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        children.append(subprocess.Popen(
            [npm, "run", "dev", "--", "--host", "127.0.0.1"],
            cwd=ROOT / "frontend", stdout=log_file, stderr=subprocess.STDOUT,
        ))

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if _service_ready(f"{BACKEND}/api/v1/health") and _service_ready(FRONTEND):
            if children:
                print("Started the local API and storefront; live reload is enabled.", flush=True)
            return children
        if any(child.poll() is not None for child in children):
            raise RuntimeError("A local service stopped during startup. Inspect logs/backend.log and logs/frontend.log.")
        time.sleep(0.4)
    raise RuntimeError("The local API and storefront did not become ready within 60 seconds.")


async def live_channel3_preflight(settings: Settings) -> dict[str, Any]:
    merchant_email = settings.merchant_email or "demo@dropback.local"
    merchant_password = settings.merchant_password or "dropback-demo"
    async with httpx.AsyncClient(base_url=API, timeout=35) as client:
        login = await client.post("/auth/login", json={"email": merchant_email, "password": merchant_password})
        if login.is_error:
            raise RuntimeError("Could not sign in to the local merchant API before starting the demo.")
        products_response = await client.get("/products")
        products_response.raise_for_status()
        products = products_response.json()
        product = next((row for row in products if row.get("sku") == SONY_SKU), None)
        if not product:
            raise RuntimeError("The Sony WH-1000XM5 is missing from the live merchant catalog.")
        linked: list[str] = []
        signal: dict[str, Any] | None = None
        # Resolve the public catalog against Channel3 before exposing it to buyers.
        for candidate in products:
            checked = await client.post(f"/products/{candidate['id']}/channel3-check")
            if checked.is_error:
                if candidate["id"] == product["id"]:
                    raise RuntimeError(f"Channel3 live product verification failed ({checked.status_code}).")
                continue
            observation = checked.json()
            if observation.get("matched") and observation.get("product_id"):
                linked.append(candidate["sku"])
                if candidate["id"] == product["id"]:
                    signal = observation
        if not signal:
            raise RuntimeError("Channel3 did not return an exact live Sony WH-1000XM5 listing.")
        if not signal.get("matched") or not signal.get("product_id"):
            raise RuntimeError("Channel3 did not return an exact live Sony WH-1000XM5 listing.")
        offer = signal.get("best_offer") or {}
        if not offer.get("price") or float(offer["price"]) >= float(product["current_price"]):
            raise RuntimeError("Channel3's current in-stock offer is no longer below the Holloway selling price; no checkout was created.")
        print(f"Channel3 verified: {len(linked)} live catalog listings; exact Sony offer ${float(offer['price']):.2f} at {offer.get('merchant', 'retailer')} vs ${float(product['current_price']):.2f} paid price.", flush=True)
        return {"product_id": product["id"], "sku": SONY_SKU, "title": product["name"], "merchant_price": float(product["current_price"]), "offer_price": float(offer["price"]), "retailer": offer.get("merchant"), "channel3_product_id": signal["product_id"], "channel3_verified_skus": linked}


async def run_browser(settings: Settings, channel3_signal: dict[str, Any], headless: bool, slow_mo_ms: int) -> dict[str, Any]:
    global stage_clock
    STAGES.clear()
    stage_clock = time.monotonic()
    if RECORDINGS.exists():
        shutil.rmtree(RECORDINGS)
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    for stale in (OUT / "screen.webm", OUT / "paypal_approval.webm", OUT / "timing.json", OUT / "latest_run.json"):
        stale.unlink(missing_ok=True)
    popup_pages: list[Page] = []
    main_video: Path | None = None
    popup_video: Path | None = None
    result: dict[str, Any] = {"channel3": channel3_signal, "environment": "sandbox", "timeline": "accelerated_day_3_scenario"}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, slow_mo=slow_mo_ms, args=["--window-size=1280,720"])
        context = await browser.new_context(
            # Match a typical 1366×768 laptop display. The former 1920×1080
            # layout overflowed the actual screen, clipping the PayPal modal.
            viewport={"width": 1280, "height": 640},
            record_video_dir=str(RECORDINGS),
            record_video_size={"width": 1920, "height": 1080},
        )
        buyer_email = json.dumps(settings.paypal_sandbox_buyer_email)
        await context.add_init_script(f"""(() => {{
          if (location.hostname.toLowerCase().endsWith('paypal.com')) {{
            const css = document.createElement('style');
            css.textContent = 'input,textarea,[id*=email],[data-testid*=email]{{-webkit-text-fill-color:transparent!important;color:transparent!important;text-shadow:0 0 7px #738198!important;caret-color:transparent!important}}';
            (document.head || document.documentElement).appendChild(css);
          }}
          const redactRoot = root => {{
            const target = {buyer_email};
            if (!target) return;
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            let node; while ((node = walker.nextNode())) {{ if (!node.nodeValue) continue; const index = node.nodeValue.toLowerCase().indexOf(target.toLowerCase()); if (index >= 0) node.nodeValue = node.nodeValue.slice(0, index) + 'Sandbox buyer' + node.nodeValue.slice(index + target.length); }}
            root.querySelectorAll?.('*').forEach(el => {{ if (el.shadowRoot) redactRoot(el.shadowRoot); }});
          }};
          const redact = () => redactRoot(document.body || document.documentElement);
          new MutationObserver(redact).observe(document.documentElement, {{childList:true,subtree:true,characterData:true}});
          redact(); setInterval(redact, 250);
        }})();""")
        page = await context.new_page()
        # Align scene offsets with the page video; browser startup happens
        # before its recording timeline begins.
        stage_clock = time.monotonic()
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(60000)
        context.on("page", lambda child: popup_pages.append(child) if child is not page else None)
        created_order: dict[str, Any] | None = None
        capture_data: dict[str, Any] | None = None
        claim_data: dict[str, Any] | None = None
        refund_result: dict[str, Any] | None = None
        run_error: Exception | None = None

        try:
            stage_start("01_store", "A protected purchase starts here", "Holloway storefront · Sony WH-1000XM5 · 14-day DropBack cover")
            await page.goto(f"{FRONTEND}/store?demo=sandbox", wait_until="domcontentloaded")
            await page.locator(f'[data-testid="product-{SONY_SKU}"]').wait_for(state="visible", timeout=45000)
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            await page.locator("#catalog").scroll_into_view_if_needed()
            await page.locator(f'[data-testid="add-to-cart-{SONY_SKU}"]').click()

            stage_start("02_checkout", "Review the bag and continue with PayPal", "The buyer reviews the Sony headphones and $398.00 total before secure checkout.")
            await page.locator("#store-cart").evaluate("element => element.scrollIntoView({ block: 'center', behavior: 'instant' })")
            await page.locator('[data-testid="paypal-checkout-btn"]').wait_for(state="visible")
            await page.wait_for_function("!document.querySelector('[data-testid=paypal-checkout-btn]')?.disabled", timeout=60000)
            await page.wait_for_timeout(500)
            await page.screenshot(path=str(OUT / "checkout-before-paypal.png"), full_page=False)
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            async with page.expect_response(
                    lambda response: response.url.endswith("/api/v1/orders") and response.request.method == "POST",
                    timeout=45000,
            ) as created_response_info:
                await page.locator('[data-testid="paypal-checkout-btn"]').click()
            created_response = await created_response_info.value
            if not created_response.ok:
                raise RuntimeError(f"PayPal order creation failed ({created_response.status}).")
            created_order = await created_response.json()
            result["paypal_order_id"] = created_order.get("order_id")
            result["internal_order_id"] = created_order.get("internal_order_id")

            stage_start("03_paypal_approval", "Real PayPal Sandbox approval", "PayPal opens in the same-window modal; the buyer signs in and approves the $398.00 purchase.")
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            await wait_for_paypal_frame(page)
            async with page.expect_response(
                    lambda response: response.url.endswith(f"/orders/{result.get('paypal_order_id')}/capture") and response.request.method == "POST",
                    timeout=120000,
            ) as capture_response_info:
                await approve_sandbox_page(page, settings.paypal_sandbox_buyer_email, settings.paypal_sandbox_buyer_password)
            capture_response = await capture_response_info.value
            if capture_response.ok:
                capture_data = await capture_response.json()
            await page.wait_for_url(re.compile(r"/portal/[^?]+\?checkout=complete"), timeout=90000)
            if not capture_data or capture_data.get("status") != "COMPLETED":
                raise RuntimeError("PayPal did not confirm a completed capture.")
            result.update({"capture_id": capture_data.get("capture_id"), "captured_amount": capture_data.get("amount"), "currency": capture_data.get("currency")})
            stage_finish()

            stage_start("04_price_check", "Three-day scenario · check the live price", "Channel3 returns current in-stock offers for the exact model.")
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            async with page.expect_response(
                lambda response: response.url.endswith("/api/v1/claims/check-price") and response.request.method == "POST",
                timeout=45000,
            ) as price_response_info:
                await page.locator('[data-testid="price-check-btn"]').click()
            price_response = await price_response_info.value
            if not price_response.ok:
                raise RuntimeError(f"Live Channel3 price check failed ({price_response.status}).")
            price_result = await price_response.json()
            if price_result.get("evidence_source") != "channel3_live" or not price_result.get("price_drop_detected"):
                raise RuntimeError("The live Channel3 check did not confirm a lower in-stock offer. The case was not submitted.")
            result["live_price_check"] = {
                "evidence_source": price_result.get("evidence_source"),
                "paid_price": price_result.get("paid_price"),
                "offer_price": price_result.get("competitor_price"),
                "retailer": price_result.get("competitor_name"),
                "difference": price_result.get("drop_amount"),
                "offer_url": (price_result.get("best_offer") or {}).get("url"),
            }

            stage_start("05_buyer_claim", "The buyer requests the difference", "A real PayPal order, live Channel3 evidence, and the buyer’s note create the case.")
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            async with page.expect_response(
                lambda response: response.url.endswith("/api/v1/claims/submit") and response.request.method == "POST",
                timeout=45000,
            ) as claim_response_info:
                await page.locator('[data-testid="submit-claim-btn"]').click()
            claim_response = await claim_response_info.value
            if not claim_response.ok:
                raise RuntimeError(f"The buyer claim could not be submitted ({claim_response.status}).")
            claim_data = await claim_response.json()
            if claim_data.get("status") != "PENDING_REVIEW" or claim_data.get("evidence_source") != "channel3_live":
                raise RuntimeError("The claim did not enter review with live Channel3 evidence.")
            result["claim_id"] = claim_data.get("id")
            result["recommended_refund"] = claim_data.get("refund_amount")

            stage_start("06_case_report", "Merchant reviews the case", "AG Grid brings the buyer note, Channel3 price, risk, and return costs together.")
            await page.goto(f"{FRONTEND}/login?next=%2Fclaims", wait_until="domcontentloaded")
            await page.locator('input[type="email"]').fill(settings.merchant_email or "demo@dropback.local")
            await page.locator('input[type="password"]').fill(settings.merchant_password or "dropback-demo")
            await page.get_by_role("button", name=re.compile("sign in", re.I)).click()
            await page.wait_for_url(re.compile(r"/claims$"), timeout=30000)
            await page.locator('[data-testid="claims-grid"]').wait_for(state="visible", timeout=30000)
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            await page.locator('[data-testid="settle-btn"]').first.click()
            await page.locator('[data-testid="claim-modal"]').wait_for(state="visible", timeout=15000)
            await page.locator('[data-testid="key-drivers"]').wait_for(state="visible", timeout=10000)

            stage_start("07_refund_result", "Merchant approval sends the PayPal refund", "PayPal Payments v2 refunds the captured difference with an idempotency key.")
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            async with page.expect_response(
                lambda response: re.search(r"/claims/[^/]+/resolve$", response.url) and response.request.method == "POST",
                timeout=60000,
            ) as refund_response_info:
                await page.locator('[data-testid="approve-refund-btn"]').click()
            refund_response = await refund_response_info.value
            if not refund_response.ok:
                raise RuntimeError(f"PayPal refund failed ({refund_response.status}); inspect the claim status before retrying.")
            refund_result = await refund_response.json()
            if refund_result.get("settlement_mode") != "paypal_sandbox" or refund_result.get("refund_status") not in {"COMPLETED", "PENDING"}:
                raise RuntimeError("The merchant action did not confirm a PayPal Sandbox refund.")
            result.update({
                "decision_status": refund_result.get("status"),
                "refund_status": refund_result.get("refund_status"),
                "paypal_refund_id": refund_result.get("paypal_refund_id"),
                "refund_amount": refund_result.get("refund_amount"),
                "settlement_mode": refund_result.get("settlement_mode"),
            })
            await page.wait_for_timeout(1200)
            await page.goto(f"{FRONTEND}/portal/{created_order['internal_order_id']}?scenario_day=3", wait_until="domcontentloaded")
            await page.get_by_text(re.compile("refund credited to PayPal|merchant approved your request", re.I)).wait_for(timeout=30000)
            await page.wait_for_timeout(1800)

            stage_start("08_apimatic", "APIMatic PayPal API contracts", "Orders v2, capture, and idempotent Payments v2 refunds are documented in the context manifest.")
            await page.goto(f"{FRONTEND}/login?next=%2Fapimatic", wait_until="domcontentloaded")
            # The merchant cookie survives this navigation, so the login route sends the user straight back.
            if await page.locator('input[type="email"]').count():
                await page.locator('input[type="email"]').fill(settings.merchant_email or "demo@dropback.local")
                await page.locator('input[type="password"]').fill(settings.merchant_password or "dropback-demo")
                await page.get_by_role("button", name=re.compile("sign in", re.I)).click()
            await page.wait_for_url(re.compile(r"/apimatic$"), timeout=30000)
            await page.locator('[data-testid="apimatic-page"]').wait_for(state="visible", timeout=20000)
            await show_caption(page, STAGES[-1]["title"], STAGES[-1]["detail"])
            await page.wait_for_timeout(2400)
            stage_finish()

        except Exception as exc:
            run_error = exc
            result["run_error"] = _redact(str(exc), settings)
        finally:
            await browser.close()
            try:
                main_video = Path(await page.video.path()) if page.video else None
            except Exception:
                pass
            try:
                if popup_pages:
                    popup_video = Path(await popup_pages[0].video.path()) if popup_pages[0].video else None
            except Exception:
                pass

    if main_video and main_video.exists():
        shutil.copy2(main_video, OUT / "screen.webm")
    if popup_video and popup_video.exists():
        # The PayPal page recorder masks all input values before credentials are filled.
        shutil.copy2(popup_video, OUT / "paypal_approval.webm")
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(popup_video)],
                capture_output=True, text=True, check=True,
            )
            clip_duration = max(0.1, min(15.0, float(probe.stdout.strip())))
            clip_start = max(0.0, float(probe.stdout.strip()) - clip_duration)
            clip_path = ROOT / "demo-video" / "clips" / "paypal_approval.mp4"
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{clip_start:.3f}", "-i", str(popup_video), "-t", f"{clip_duration:.3f}",
                "-an", "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-movflags", "+faststart", str(clip_path),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Recorded the PayPal approval clip with buyer identifiers masked.", flush=True)
    elif main_video and main_video.exists() and shutil.which("ffmpeg") and shutil.which("ffprobe"):
        # In modal presentation mode PayPal renders in an iframe over the buyer
        # page. Extract that time range from the main screen recording so the
        # submission still shows the real approval in the same window.
        approval_stage = next((row for row in STAGES if row["id"] == "03_paypal_approval"), None)
        if approval_stage and approval_stage.get("end") is not None:
            clip_start = float(approval_stage["start"])
            clip_duration = max(0.1, min(15.0, float(approval_stage["end"]) - clip_start))
            clip_path = ROOT / "demo-video" / "clips" / "paypal_approval.mp4"
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{clip_start:.3f}", "-i", str(main_video), "-t", f"{clip_duration:.3f}",
                "-an", "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-movflags", "+faststart", str(clip_path),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Recorded the same-window PayPal modal approval clip.", flush=True)
    stage_finish()
    if not main_video or not main_video.exists():
        result.setdefault("run_error", "The browser did not produce its main screen recording.")
    report = {
        **result,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stages": STAGES,
        "recording": "demo-video/out/screen.webm",
        "approval_recording": "demo-video/clips/paypal_approval.mp4" if (ROOT / "demo-video" / "clips" / "paypal_approval.mp4").exists() else None,
    }
    (OUT / "latest_run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "timing.json").write_text(json.dumps({"scenes": [{"id": row["id"], "start": row["start"], "end": row["end"]} for row in STAGES]}, indent=2), encoding="utf-8")
    if run_error:
        print("Partial run details and any available recording were saved to demo-video/out/latest_run.json.", flush=True)
        raise RuntimeError(_redact(str(run_error), settings)) from run_error
    if not result.get("captured_amount") or not result.get("live_price_check") or not result.get("refund_status"):
        raise RuntimeError("The walkthrough ended without verifying each payment, live evidence, and refund step.")
    print(f"Run complete: captured ${float(result['captured_amount']):.2f}, live Channel3 difference ${float(result['live_price_check']['difference']):.2f}, PayPal refund {result['refund_status']}.", flush=True)
    print("Video input: demo-video/out/screen.webm. Run `make demo-video` to build the submission MP4.", flush=True)
    return report


async def main(args: argparse.Namespace) -> int:
    settings = Settings(_env_file=ROOT / ".env")
    preflight(settings)
    services = ensure_services()
    try:
        signal = await live_channel3_preflight(settings)
        await run_browser(settings, signal, headless=args.headless, slow_mo_ms=args.slow_mo)
    except Exception as exc:
        print(f"Sandbox demo stopped: {_redact(str(exc), settings)}", file=sys.stderr, flush=True)
        return 1
    finally:
        # Leave local dev servers running for inspection and for the next run.
        for child in services:
            if child.poll() is not None:
                continue
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description="Buy, protect, review, and refund a real PayPal Sandbox order.")
    parser.add_argument("--headless", action="store_true", help="Run the buyer flow in a hidden browser window.")
    parser.add_argument("--slow-mo", type=int, default=80, help="Milliseconds between browser actions for the live presentation.")
    args = parser.parse_args()
    try:
        return asyncio.run(main(args))
    except KeyboardInterrupt:
        print("Sandbox demo interrupted. Review the latest order in the merchant console before running it again.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(cli())
