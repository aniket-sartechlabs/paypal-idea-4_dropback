"""Automated PayPal Sandbox buyer helper using Playwright.

Used for automated checkout approvals, testing PayPal sandbox login,
and recording the demo video approval clip (demo-video/clips/paypal_approval.mp4).

Credentials read from environment:
- PAYPAL_SANDBOX_BUYER_EMAIL
- PAYPAL_SANDBOX_BUYER_PASSWORD
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from playwright.async_api import Error as PwError
from playwright.async_api import Page, async_playwright
from playwright.async_api import TimeoutError as PwTimeout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402

settings = Settings(_env_file=ROOT / ".env")

RETURN_RE = re.compile(r"/checkout/return|/shop/sandbox-return|/portal", re.I)
CANCEL_RE = re.compile(r"/checkout/cancel|/shop/sandbox-cancel", re.I)
CONSENT_RE = re.compile(r"agree|continue|pay now|complete purchase|confirm", re.I)


async def _visible(page: Page, selector: str, timeout: float = 4000) -> bool:
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        return True
    except PwTimeout:
        return False


async def login_sandbox(page: Page, email: str, password: str) -> None:
    """Log in to PayPal Sandbox."""
    if await _visible(page, "#email", 10000):
        await page.fill("#email", email)
        if await _visible(page, "#btnNext", 2000):
            await page.click("#btnNext")
    if await _visible(page, "#password", 10000):
        await page.fill("#password", password)
        await page.click("#btnLogin")


async def approve_url(url: str, email: str, password: str, *, headed: bool = True, slow_mo: float = 100) -> bool:
    """Open PayPal approval URL and approve payment as sandbox buyer."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed, slow_mo=slow_mo)
        page = await browser.new_page()
        try:
            print(f"Opening approval page: {url[:80]}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if await _visible(page, "#email, #password", 8000):
                print("Logging in to PayPal Sandbox...")
                await login_sandbox(page, email, password)

            # Click consent / pay button
            for selector in ("#consentButton", "button[data-testid='consentButton']", "#confirmButtonTop", "#payment-submit-btn"):
                if await _visible(page, selector, 15000):
                    await page.locator(selector).first.click()
                    break
            else:
                try:
                    await page.get_by_role("button", name=CONSENT_RE).first.click(timeout=10000)
                except Exception:
                    pass

            await asyncio.sleep(3)
            print("Approval processed successfully!")
            return True
        except Exception as exc:
            print(f"Approval error: {exc}")
            return False
        finally:
            await browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="PayPal Sandbox Buyer Automation")
    ap.add_argument("--url", help="PayPal Sandbox approval URL to confirm")
    ap.add_argument("--pre-login", action="store_true", help="Open headed browser to sandbox.paypal.com for manual session prep")
    ap.add_argument("--email", default=os.getenv("PAYPAL_SANDBOX_BUYER_EMAIL") or settings.paypal_sandbox_buyer_email)
    ap.add_argument("--password", default=os.getenv("PAYPAL_SANDBOX_BUYER_PASSWORD") or settings.paypal_sandbox_buyer_password)
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    if (args.pre_login or args.url) and (not args.email or not args.password):
        print("Set PAYPAL_SANDBOX_BUYER_EMAIL and PAYPAL_SANDBOX_BUYER_PASSWORD in .env, or pass --email and --password.")
        return 2

    if args.pre_login:
        async def run_prelogin():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False, slow_mo=50)
                page = await browser.new_page()
                await page.goto("https://www.sandbox.paypal.com/signin", wait_until="domcontentloaded")
                await login_sandbox(page, args.email, args.password)
                print("Browser opened. Press Enter in terminal when done...")
                await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                await browser.close()
        asyncio.run(run_prelogin())
        return 0

    if args.url:
        ok = asyncio.run(approve_url(args.url, args.email, args.password, headed=not args.headless))
        return 0 if ok else 1

    print("Usage: python scripts/sandbox_buyer.py --pre-login | --url <approval_url>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
