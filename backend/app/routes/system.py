"""Health check and the local-only automated Sandbox walkthrough launcher."""

import json
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.security import require_local_request

router = APIRouter(prefix="/api/v1")
settings = get_settings()
ROOT = Path(__file__).resolve().parents[3]
_demo_process: subprocess.Popen | None = None


@router.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment, "paypal_configured": settings.paypal_ready,
            "paypal_environment": settings.paypal_env, "channel3_configured": bool(settings.channel3_api_key),
            "channel3_webhook_configured": bool(settings.channel3_webhook_secret),
            "llm_configured": bool(settings.openai_api_key or settings.gemini_api_key),
            "mcp_enabled": bool(settings.mcp_api_token)}


@router.post("/demo/run")
def start_sandbox_demo(request: Request):
    """Launch the real buyer-to-refund walkthrough from its dedicated local URL."""
    global _demo_process
    require_local_request(request)
    if settings.is_production or settings.paypal_env.lower() != "sandbox":
        raise HTTPException(503, "The automated purchase walkthrough is restricted to PayPal Sandbox development.")
    if not settings.paypal_ready or not settings.paypal_sandbox_buyer_email or not settings.paypal_sandbox_buyer_password or not settings.channel3_api_key:
        raise HTTPException(503, "Complete the PayPal Sandbox buyer, PayPal API, and Channel3 setup before launching the demo.")
    if _demo_process and _demo_process.poll() is None:
        return {"started": False, "running": True, "message": "The full Sandbox walkthrough is already running."}
    log_path = ROOT / "logs" / "sandbox-demo-runner.log"
    log_path.parent.mkdir(exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    _demo_process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "sandbox_demo.py"), "--slow-mo", "20"],
        cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True,
    )
    return {"started": True, "running": True, "message": "The full Sandbox walkthrough is starting in a new browser window.", "log": "logs/sandbox-demo-runner.log"}


@router.get("/demo/run")
def sandbox_demo_status(request: Request):
    require_local_request(request)
    process = _demo_process
    running = bool(process and process.poll() is None)
    report_path = ROOT / "demo-video" / "out" / "latest_run.json"
    report = None
    if report_path.exists() and not running:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            report = {key: payload.get(key) for key in ("environment", "timeline", "captured_amount", "live_price_check", "claim_id", "recommended_refund", "refund_status", "run_error", "created_at")}
        except (OSError, json.JSONDecodeError):
            pass
    return {"running": running, "exit_code": process.poll() if process else None, "report": report, "log": "logs/sandbox-demo-runner.log"}
