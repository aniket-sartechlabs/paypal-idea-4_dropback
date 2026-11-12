"""Record the real DropBack Sandbox story for the explainer video.

One continuous browser recording (1600x900, no in-page captions):
new merchant signs up -> setup wizard (store, connect PayPal, policy, go live) -> store -> PayPal checkout (in-page modal) -> buyer portal, Channel3 price check, claim
-> merchant claims grid (AG Grid) -> AI case report -> approve (PayPal refund)
-> buyer sees the refund -> merchant overview -> PayPal API lab (SDK + MCP).

Writes to video-out/rec_live/:
  live.webm    the recording
  marks.json   {name: seconds} moments used by the storyboard
  rects.json   {name: {at, x, y, w, h}} element boxes (fractions of the frame) for highlight boxes
  facts.json   numbers and IDs from the run (prices, refund, PayPal references) for the narration

This creates a real PayPal Sandbox payment and refund. The buyer's Sandbox login comes from the
ignored .env file and is masked on screen, exactly as in scripts/sandbox_demo.py.

Optional --paypal-proof: afterwards, a second window opens www.sandbox.paypal.com; a person signs in
(the recorder never types there) and opens the refund in the account's activity, then closes the tab.

Usage:  python demo-video/explainer/record_live.py [--paypal-proof]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
import sandbox_demo as sd  # noqa: E402
from app.config import Settings  # noqa: E402

W, H = 1600, 900
OUT = ROOT / "video-out" / "rec_live"
PAYPAL_WEB = "https://www.sandbox.paypal.com"
WAIT_PERSON = 15 * 60 * 1000


class Recorder:
    def __init__(self, page: Page):
        self.page = page
        self.t0 = time.monotonic()
        self.marks: dict[str, float] = {}
        self.rects: dict[str, dict[str, float]] = {}

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def mark(self, name: str) -> None:
        self.marks[name] = self.now()
        print(f"{self.marks[name]:8.2f}s  {name}", flush=True)

    async def rect(self, name: str, selector: str) -> None:
        """Remember where an element is on screen right now (fractions of the frame)."""
        try:
            box = await self.page.locator(selector).first.bounding_box(timeout=2000)
        except Exception:
            box = None
        if not box:
            print(f"          (no box for {name}: {selector})", flush=True)
            return
        x, y = max(0.0, box["x"]), max(0.0, box["y"])
        w, h = min(W - x, box["width"]), min(H - y, box["height"])
        self.rects[name] = {"at": self.now(), "x": round(x / W, 4), "y": round(y / H, 4), "w": round(w / W, 4), "h": round(h / H, 4)}

    async def glide(self, selector: str, block: str = "center", wait: int = 1100) -> None:
        target = self.page.locator(selector).first  # Playwright selectors (text=..., css)
        if await target.count():
            await target.evaluate("(el, b) => el.scrollIntoView({block: b, behavior: 'smooth'})", block)
        await self.page.wait_for_timeout(wait)

    async def pause(self, ms: int) -> None:
        await self.page.wait_for_timeout(ms)


async def merchant_sign_in(page: Page, settings: Settings, next_path: str) -> None:
    await page.goto(f"{sd.FRONTEND}/login?next={next_path.replace('/', '%2F')}", wait_until="domcontentloaded")
    target = re.compile(re.escape(next_path) + "$")
    email_box = page.locator('input[type="email"]')
    for _ in range(100):  # wait for React: either the sign-in form or the redirect (already signed in)
        if await email_box.count() or target.search(page.url):
            break
        await page.wait_for_timeout(100)
    if await email_box.count():
        await page.locator('input[type="email"]').fill(settings.merchant_email or "demo@dropback.local")
        await page.locator('input[type="password"]').fill(settings.merchant_password or "dropback-demo")
        await page.get_by_role("button", name=re.compile("sign in", re.I)).click()
    await page.wait_for_url(re.compile(re.escape(next_path) + "$"), timeout=30000)


MATCHED_RETAILERS = ["bestbuy.com", "target.com", "walmart.com", "amazon.com", "beachcamera.com", "crutchfield.com"]


async def merchant_onboarding(page: Page, r: Recorder, settings: Settings, signal: dict[str, Any]) -> None:
    """Sign up a new merchant workspace and walk the setup wizard. Needs sign-up to be open (a fresh workspace)."""
    await page.goto(f"{sd.FRONTEND}/login", wait_until="domcontentloaded")
    start = page.locator('[data-testid="signup-start"]')
    try:
        await start.wait_for(state="visible", timeout=20000)
    except Exception as exc:
        raise RuntimeError("Sign-up is closed: this workspace already has an owner. Record against a fresh database.") from exc
    r.mark("signup")
    await r.pause(1500)
    await start.click()
    await page.locator('[data-testid="signup-store-name"]').wait_for(state="visible")
    await page.locator('[data-testid="signup-store-name"]').type("Holloway Goods", delay=45)
    await page.locator('input[type="email"]').fill("")
    await page.locator('input[type="email"]').type("owner@holloway.test", delay=30)
    await page.locator('input[type="password"]').fill(secrets.token_urlsafe(14))  # throwaway local test owner
    await r.rect("signup_form", ".login-form")
    await r.pause(800)
    await page.get_by_role("button", name=re.compile("create workspace", re.I)).click()
    await page.locator('[data-testid="setup-page"]').wait_for(state="visible", timeout=20000)
    r.mark("setup")
    await r.rect("setup_steps", ".setup-steps")
    await r.pause(2200)
    await page.locator('[data-testid="setup-store-url"]').type("https://holloway.example", delay=30)
    await r.pause(600)
    await page.get_by_role("button", name=re.compile("save and continue", re.I)).click()
    await page.locator('[data-testid="setup-paypal-client-id"]').wait_for(state="visible")
    r.mark("paypal_step")
    await r.pause(1800)
    # The merchant's own Sandbox REST app (here: the project's Sandbox app from .env). The secret field is masked.
    await page.locator('[data-testid="setup-paypal-client-id"]').fill(settings.paypal_client_id)
    await page.locator('[data-testid="setup-paypal-secret"]').fill(settings.paypal_client_secret)
    await r.pause(700)
    await page.locator('[data-testid="setup-paypal-connect"]').click()
    await page.locator('[data-testid="setup-paypal-status"]', has_text="Connected").wait_for(timeout=30000)
    r.mark("paypal_connected")
    await r.rect("paypal_status", '[data-testid="setup-paypal-status"]')
    await r.rect("webhook_note", ".setup-webhook")
    await r.pause(3200)
    await page.locator('[data-testid="setup-step-policy"]').click()
    retailers = [x for x in dict.fromkeys([str(signal.get("retailer") or "").lower(), *MATCHED_RETAILERS]) if x]
    field = page.locator('[data-testid="setup-retailers"]')
    await field.wait_for(state="visible")
    r.mark("policy")
    await field.type(", ".join(retailers[:5]), delay=18)
    await r.rect("policy_fields", ".setup-panel .settings-fields")
    await r.pause(1200)
    await page.get_by_role("button", name=re.compile("save policy", re.I)).click()
    await page.get_by_text(re.compile(r"products linked for price monitoring|not yet linked to Channel3")).wait_for(timeout=15000)
    r.mark("catalog_step")
    await r.pause(2000)
    await page.locator('[data-testid="setup-step-live"]').click()
    await page.locator('[data-testid="setup-email-snippet"]').wait_for(state="visible")
    r.mark("golive")
    await r.rect("email_snippet", '[data-testid="setup-email-snippet"]')
    await r.pause(3000)
    await page.locator('[data-testid="setup-finish"]').click()
    await page.wait_for_url(re.compile(r"127\.0\.0\.1:5173/$|localhost:5173/$"), timeout=20000)
    r.mark("live_done")
    await r.pause(2500)


async def record(settings: Settings, signal: dict[str, Any], headless: bool, paypal_proof: bool) -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "raw").mkdir(parents=True)
    facts: dict[str, Any] = {"channel3_preflight": signal, "environment": "PayPal Sandbox"}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless, args=[f"--window-size={W},{H + 120}"])
        ctx = await browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(OUT / "raw"),
                                        record_video_size={"width": W, "height": H}, locale="en-US")
        await ctx.add_init_script(sd.redaction_script(settings.paypal_sandbox_buyer_email))
        page = await ctx.new_page()
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(60000)
        r = Recorder(page)
        error: Exception | None = None
        try:
            # 0. A new merchant signs up and connects their PayPal app (fresh local workspace)
            await merchant_onboarding(page, r, settings, signal)

            # 1. Store
            await page.goto(f"{sd.FRONTEND}/store?demo=sandbox", wait_until="domcontentloaded")
            await page.locator(f'[data-testid="product-{sd.SONY_SKU}"]').wait_for(state="visible", timeout=45000)
            r.mark("store")
            await r.pause(3000)
            await r.glide("#catalog", "start", 1400)
            r.mark("catalog")
            await r.rect("product", f'[data-testid="product-{sd.SONY_SKU}"]')
            await r.pause(2200)
            await page.locator(f'[data-testid="add-to-cart-{sd.SONY_SKU}"]').click()
            r.mark("added")
            await r.pause(900)

            # 2. Checkout with PayPal
            await r.glide("#store-cart", "center", 1300)
            await page.wait_for_function("!document.querySelector('[data-testid=paypal-checkout-btn]')?.disabled", timeout=60000)
            r.mark("cart")
            await r.rect("cart", "#store-cart")
            await r.rect("paypal_button", '[data-testid="paypal-checkout-btn"]')
            await r.pause(2200)
            async with page.expect_response(lambda res: res.url.endswith("/api/v1/orders") and res.request.method == "POST", timeout=45000) as created_info:
                await page.locator('[data-testid="paypal-checkout-btn"]').click()
            created = await (await created_info.value).json()
            facts.update(paypal_order_id=created.get("order_id"), internal_order_id=created.get("internal_order_id"))
            r.mark("paypal_click")
            await sd.wait_for_paypal_frame(page)
            r.mark("paypal_open")
            async with page.expect_response(lambda res: res.url.endswith(f"/orders/{created.get('order_id')}/capture") and res.request.method == "POST", timeout=120000) as cap_info:
                await sd.approve_sandbox_page(page, settings.paypal_sandbox_buyer_email, settings.paypal_sandbox_buyer_password)
                r.mark("paypal_approved")
            capture = await (await cap_info.value).json()
            if capture.get("status") != "COMPLETED":
                raise RuntimeError("PayPal did not confirm a completed capture.")
            facts.update(capture_id=capture.get("capture_id"), paid=capture.get("amount"), currency=capture.get("currency"))
            await page.wait_for_url(re.compile(r"/portal/[^?]+\?checkout=complete"), timeout=90000)
            await page.locator('[data-testid="buyer-order-card"]').wait_for(state="visible", timeout=30000)
            r.mark("portal")
            await r.rect("order_card", '[data-testid="buyer-order-card"]')
            await r.pause(3200)

            # 3. Buyer checks the live price (Channel3) and asks for the difference
            await r.glide('[data-testid="price-check-btn"]', "center", 1200)
            r.mark("price_check")
            await r.rect("price_check_btn", '[data-testid="price-check-btn"]')
            await r.pause(1200)
            async with page.expect_response(lambda res: res.url.endswith("/api/v1/claims/check-price") and res.request.method == "POST", timeout=45000) as price_info:
                await page.locator('[data-testid="price-check-btn"]').click()
            price = await (await price_info.value).json()
            if not price.get("price_drop_detected"):
                raise RuntimeError("Channel3 did not find a lower in-stock offer; no claim was submitted.")
            facts.update(offer=price.get("competitor_price"), retailer=price.get("competitor_name"), diff=price.get("drop_amount"),
                         diff_pct=price.get("drop_percentage"), offer_url=(price.get("best_offer") or {}).get("url"),
                         window_days=price.get("protection_window_days"))
            await page.locator(".claim-submission-card").wait_for(state="visible", timeout=15000)
            r.mark("price_found")
            await r.glide(".claim-submission-card", "center", 1200)
            await r.rect("offer_card", ".claim-submission-card")
            await r.rect("offer_badge", ".price-drop-delta-badge")
            await r.pause(3800)
            await r.glide('[data-testid="submit-claim-btn"]', "center", 900)
            r.mark("claim_ready")
            await r.rect("submit_claim", '[data-testid="submit-claim-btn"]')
            await r.pause(1500)
            async with page.expect_response(lambda res: res.url.endswith("/api/v1/claims/submit") and res.request.method == "POST", timeout=60000) as claim_info:
                await page.locator('[data-testid="submit-claim-btn"]').click()
            claim = await (await claim_info.value).json()
            report = claim.get("analysis_report") or {}
            fin = report.get("financial_breakdown") or {}
            facts.update(claim_id=claim.get("id"), recommended_refund=claim.get("refund_amount"),
                         probability=claim.get("return_probability"), return_cost=fin.get("estimated_return_cost"),
                         lost_margin=fin.get("lost_margin"), loss_if_returned=fin.get("loss_if_returned"),
                         expected_loss=fin.get("expected_loss"), net_savings=fin.get("net_savings"),
                         provider=report.get("provider"), model=report.get("model"))
            await page.locator(".claim-status-banner").wait_for(state="visible", timeout=15000)
            r.mark("claim_sent")
            await r.glide(".claim-status-banner", "center", 900)
            await r.rect("claim_banner", ".claim-status-banner")
            await r.pause(3500)

            # 4. Merchant: claims queue in AG Grid, AI case report, approve -> PayPal refund
            await merchant_sign_in(page, settings, "/claims")
            await page.locator('[data-testid="claims-grid"]').wait_for(state="visible", timeout=30000)
            r.mark("grid")
            await r.pause(1200)
            await r.rect("grid", '[data-testid="claims-grid"]')
            await r.rect("grid_row", '[data-testid="claims-grid"] .ag-center-cols-container .ag-row')
            await r.pause(4200)
            await page.locator('[data-testid="settle-btn"]').first.click()
            await page.locator('[data-testid="claim-modal"]').wait_for(state="visible", timeout=15000)
            await page.locator('[data-testid="key-drivers"]').wait_for(state="visible", timeout=10000)
            r.mark("report")
            await r.pause(900)
            await r.rect("report_metrics", '[data-testid="claim-modal"] .modal-metrics-grid')
            await r.pause(3600)
            await r.glide('[data-testid="claim-modal"] .financial-comparison-grid', "center", 1300)
            r.mark("costs")
            await r.rect("costs", '[data-testid="claim-modal"] .financial-comparison-grid')
            await r.pause(3200)
            await r.glide('[data-testid="approve-refund-btn"]', "center", 1300)
            r.mark("approve_ready")
            await r.rect("approve_btn", '[data-testid="approve-refund-btn"]')
            await r.pause(2200)
            async with page.expect_response(lambda res: re.search(r"/claims/[^/]+/resolve$", res.url) and res.request.method == "POST", timeout=60000) as res_info:
                await page.locator('[data-testid="approve-refund-btn"]').click()
            resolved = await (await res_info.value).json()
            if resolved.get("refund_status") not in {"COMPLETED", "PENDING"}:
                raise RuntimeError("The merchant action did not confirm a PayPal Sandbox refund.")
            facts.update(refund=resolved.get("refund_amount"), refund_status=resolved.get("refund_status"),
                         paypal_refund_id=resolved.get("paypal_refund_id"))
            r.mark("refunded")
            await r.pause(3800)

            # 5. Buyer sees the refund
            await page.goto(f"{sd.FRONTEND}/portal/{facts['internal_order_id']}?scenario_day=3", wait_until="domcontentloaded")
            await page.get_by_text(re.compile("refund credited to PayPal|merchant approved your request", re.I)).wait_for(timeout=30000)
            r.mark("buyer_refund")
            await r.glide(".claim-status-banner", "center", 1000)
            await r.rect("refund_banner", ".claim-status-banner")
            await r.pause(4500)

            # 6. Merchant overview, then the PayPal API lab (SDK + MCP)
            await page.goto(f"{sd.FRONTEND}/", wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)
            r.mark("overview")
            await r.pause(3500)
            await page.mouse.wheel(0, 500)
            r.mark("overview_scroll")
            await r.pause(3000)
            await page.goto(f"{sd.FRONTEND}/apimatic", wait_until="domcontentloaded")
            await page.locator('[data-testid="apimatic-page"]').wait_for(state="visible", timeout=20000)
            await page.wait_for_timeout(1500)
            r.mark("apilab")
            await r.rect("sdk_ops", ".api-contract-panel")
            await r.rect("sdk_strip", ".api-connection-strip")
            await r.pause(4000)
            await r.glide("text=Connect an AI agent", "center", 1300)
            r.mark("mcp")
            await r.rect("mcp", "text=DropBack MCP server")
            await r.pause(3500)
            r.mark("end")
        except Exception as exc:
            error = exc
        finally:
            video = page.video
            await ctx.close()
            raw = Path(await video.path()) if video else None
            if raw and raw.exists():
                shutil.move(str(raw), OUT / "live.webm")

        if error is None and paypal_proof:
            facts["paypal_proof"] = await record_paypal_activity(browser, r)
        await browser.close()

    (OUT / "marks.json").write_text(json.dumps(r.marks, indent=1), encoding="utf-8")
    (OUT / "rects.json").write_text(json.dumps(r.rects, indent=1), encoding="utf-8")
    (OUT / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
    shutil.rmtree(OUT / "raw", ignore_errors=True)
    if error:
        raise RuntimeError(sd._redact(str(error), settings)) from error
    print(f"Recorded {OUT / 'live.webm'}: paid ${facts.get('paid')}, offer ${facts.get('offer')} at {facts.get('retailer')}, "
          f"refund ${facts.get('refund')} ({facts.get('refund_status')}).", flush=True)


async def record_paypal_activity(browser, r: Recorder) -> str | None:
    """A person signs in to www.sandbox.paypal.com and opens the refund in Activity; the recorder never types there."""
    ctx = await browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(OUT / "raw_proof"),
                                    record_video_size={"width": W, "height": H}, locale="en-US")
    page = await ctx.new_page()
    t0 = time.monotonic()
    marks: dict[str, float] = {}
    await page.goto(f"{PAYPAL_WEB}/signin", wait_until="domcontentloaded")
    print(">>> In the new window, sign in to PayPal Sandbox as the buyer, open the DropBack refund in Activity, then close the tab.", flush=True)
    await page.wait_for_url(lambda url: "/signin" not in url and "/authflow" not in url and "/auth/" not in url, timeout=WAIT_PERSON)
    await page.goto(f"{PAYPAL_WEB}/myaccount/activities/", wait_until="domcontentloaded")
    marks["activity"] = round(time.monotonic() - t0, 2)
    await page.wait_for_event("close", timeout=WAIT_PERSON)
    marks["closed"] = round(time.monotonic() - t0, 2)
    video = page.video
    await ctx.close()
    raw = Path(await video.path()) if video else None
    if raw and raw.exists():
        shutil.move(str(raw), OUT / "paypal_proof.webm")
        shutil.rmtree(OUT / "raw_proof", ignore_errors=True)
        (OUT / "proof_marks.json").write_text(json.dumps(marks, indent=1), encoding="utf-8")
        return "rec_live/paypal_proof.webm"
    return None


async def main(args: argparse.Namespace) -> int:
    settings = Settings(_env_file=ROOT / ".env")
    sd.preflight(settings)
    sd.ensure_services()
    signal = await sd.live_channel3_preflight(settings)
    await record(settings, signal, args.headless, args.paypal_proof)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--paypal-proof", action="store_true", help="also record the buyer's PayPal Sandbox activity (a person signs in)")
    raise SystemExit(asyncio.run(main(ap.parse_args())))
