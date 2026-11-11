"""Check PayPal Sandbox OAuth, the APIMatic contract manifest, and live Channel3 access."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.services.apimatic_mcp import apimatic_mcp  # noqa: E402
from app.services.channel3 import channel3  # noqa: E402


async def check_all() -> int:
    settings = get_settings()
    print("DROPBACK SANDBOX READINESS")
    print(f"Application: {settings.environment}")
    print(f"PayPal environment: {settings.paypal_env}")
    errors = 0

    print("\n[1/3] PayPal Sandbox OAuth")
    try:
        started = time.monotonic()
        result = await apimatic_mcp.invoke_mcp_tool("paypal_check_sandbox_health", {})
        if result.get("status") == "SUCCESS":
            print(f"Ready · OAuth token obtained in {round((time.monotonic() - started) * 1000)} ms")
        else:
            print(f"Not ready · PayPal returned {result.get('status', 'an error')}")
            errors += 1
    except Exception as exc:
        print(f"Not ready · {type(exc).__name__}")
        errors += 1

    print("\n[2/3] APIMatic Context Plugin manifest")
    manifest = apimatic_mcp.get_plugin_manifest()
    if manifest.get("manifest_loaded") and manifest.get("tools_count"):
        print(f"Loaded {manifest['version']} · {manifest['tools_count']} tools · {manifest.get('contract_source')}")
    else:
        print("Manifest or tool schemas are unavailable.")
        errors += 1

    print("\n[3/3] Channel3 live product search")
    try:
        started = time.monotonic()
        signal = await channel3.search_and_compare("Sony WH-1000XM5 Wireless Noise Canceling Headphones", "SONY-WH1000XM5-BLK", 398.00, "USD")
        if signal.get("matched") and signal.get("product_id"):
            offer = signal["best_offer"]
            print(f"Exact listing · {offer['merchant']} · ${offer['price']:.2f} · {round((time.monotonic() - started) * 1000)} ms")
        else:
            print("Live API responded, but no exact listing and offer were verified.")
            errors += 1
    except Exception as exc:
        print(f"Not ready · {type(exc).__name__}")
        errors += 1

    print("\nREADY FOR THE SANDBOX WALKTHROUGH" if errors == 0 else f"\n{errors} readiness check(s) need attention.")
    print("No order or payment was created by this check.")
    return errors


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check_all()))
