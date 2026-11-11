"""Cross-platform task runner mirroring Makefile (works on Windows, Linux, and macOS).

Usage: python scripts/tasks.py <task> [args]
Tasks: setup dev frontend test sandbox-check sandbox-buyer demo-video-check demo-video
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(*args: str, env: dict[str, str] | None = None, cwd: Path | None = None) -> int:
    print("+", " ".join(args), flush=True)
    return subprocess.call(list(args), cwd=cwd or ROOT, env={**os.environ, **(env or {})})


def py() -> str:
    return str(VPY) if VPY.exists() else sys.executable


def setup() -> int:
    print("+ Setting up Python and Node dependencies...")
    return (
        run(py(), "-m", "pip", "install", "-r", "backend/requirements.txt")
        or run("npm", "install", cwd=ROOT / "frontend")
    )


def dev() -> int:
    """Run backend with uvicorn."""
    return run(py(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload", cwd=ROOT / "backend")


def frontend() -> int:
    """Run Vite development server."""
    return run("npm", "run", "dev", cwd=ROOT / "frontend")


TASKS = {
    "setup": setup,
    "dev": dev,
    "frontend": frontend,
    "sandbox-check": lambda: run(py(), "scripts/sandbox_check.py", *sys.argv[2:]),
    "sandbox-buyer": lambda: run(py(), "scripts/sandbox_buyer.py", *sys.argv[2:]),
    "test": lambda: run(py(), "-m", "pytest", "backend/tests", "-q", *sys.argv[2:]),
    "demo-video-check": lambda: run(py(), "demo-video/check_scenes.py", *sys.argv[2:]),
    "demo-video": lambda: run(py(), "demo-video/build_video.py", *sys.argv[2:]),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(2)
    sys.exit(TASKS[sys.argv[1]]())
