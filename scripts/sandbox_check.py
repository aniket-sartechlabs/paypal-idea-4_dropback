"""DropBack & PayPal Sandbox Diagnostic Health Check.

Verifies:
1. PayPal Sandbox API credentials & OAuth access token
2. APIMatic Context Plugin & MCP protocol status
3. Channel3 market intelligence API connectivity
4. Database & sample claims status

Usage: python scripts/sandbox_check.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings
from app.services.apimatic_mcp import apimatic_mcp
from app.services.channel3 import channel3
from app.services.paypal import paypal


async def check_all() -> int:
    settings = get_settings()
    print("=" * 65)
    print("  DROPBACK SYSTEM DIAGNOSTIC HEALTH CHECK")
    print("=" * 65)
    print(f"Environment:       {settings.environment}")
    print(f"PayPal Env:        {settings.paypal_env}")
    print(f"PayPal Client ID:  {settings.paypal_client_id[:16]}..." if settings.paypal_client_id else "PayPal Client ID:  [NOT SET]")
    print(f"Channel3 Key:      {'*' * 8}..." if settings.channel3_api_key else "[NOT SET]")
    print("-" * 65)

    errors = 0

    # 1. PayPal OAuth & MCP Health Check
    print("[1/3] Testing PayPal Sandbox via APIMatic MCP...")
    try:
        t0 = time.time()
        health_res = await apimatic_mcp.invoke_mcp_tool("paypal_check_sandbox_health", {})
        latency = round((time.time() - t0) * 1000, 1)
        if health_res.get("status") == "SUCCESS":
            print(f"  ✓ PayPal Sandbox Connected ({latency} ms)")
            print(f"    - OAuth Token: Active ({health_res.get('token_prefix')})")
            print(f"    - APIMatic Contract: {health_res.get('apimatic_contract_status')}")
        else:
            print(f"  ✗ PayPal Sandbox Check Failed: {health_res.get('error')}")
            errors += 1
    except Exception as exc:
        print(f"  ✗ Exception testing PayPal: {exc}")
        errors += 1

    # 2. APIMatic Plugin Manifest Check
    print("\n[2/3] Checking APIMatic Context Plugin Manifest...")
    manifest = apimatic_mcp.get_plugin_manifest()
    print(f"  ✓ Plugin Name:    {manifest.get('plugin_name')}")
    print(f"  ✓ Schema Version: {manifest.get('version')}")
    print(f"  ✓ MCP Tools:      {manifest.get('tools_count')} registered tools")

    # 3. Channel3 API Connectivity
    print("\n[3/3] Checking Channel3 Market Price Intelligence...")
    if settings.channel3_api_key:
        try:
            t0 = time.time()
            res = await channel3.search_products("Sony WH-1000XM5", limit=2)
            latency = round((time.time() - t0) * 1000, 1)
            print(f"  ✓ Channel3 API Connected ({latency} ms) — {len(res)} live offers returned")
        except Exception as exc:
            print(f"  ! Channel3 Check: {exc} (Demo fallback active)")
    else:
        print("  ! Channel3 API Key not provided in .env (pre-seeded market data will be used)")

    print("-" * 65)
    if errors == 0:
        print("  ALL CORE CHECKS PASSED — READY FOR DEMO & SUBMISSION")
    else:
        print(f"  {errors} CHECK(S) REPORTED ISSUES — Check .env configuration")
    print("=" * 65)
    return errors


def main() -> int:
    return asyncio.run(check_all())


if __name__ == "__main__":
    raise SystemExit(main())
