"""Cross-platform task runner mirroring Makefile (works on Windows, Linux, and macOS).

Usage: python scripts/tasks.py <task> [args]
Tasks: setup dev api frontend watch test sandbox-check sandbox-buyer sandbox-demo demo-video-check demo-video submission-check
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
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
        run(py(), "-m", "pip", "install", "-r", "backend/requirements-dev.txt")
        or run("npm", "install", cwd=ROOT / "frontend")
    )


def dev() -> int:
    """Run the backend and Vite together; both watch their source files."""
    commands = [
        ([py(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"], ROOT / "backend"),
        (["npm", "run", "dev", "--", "--host", "127.0.0.1"], ROOT / "frontend"),
    ]
    processes = []
    try:
        for command, cwd in commands:
            print("+", " ".join(command), flush=True)
            processes.append(subprocess.Popen(command, cwd=cwd))
        while all(process.poll() is None for process in processes):
            time.sleep(0.4)
        return next((process.returncode for process in processes if process.returncode not in (None, 0)), 0)
    except KeyboardInterrupt:
        return 130
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def api() -> int:
    return run(py(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload", cwd=ROOT / "backend")


def frontend() -> int:
    """Run Vite development server."""
    return run("npm", "run", "dev", cwd=ROOT / "frontend")


TASKS = {
    "setup": setup,
    "dev": dev,
    "api": api,
    "frontend": frontend,
    "watch": dev,
    "sandbox-check": lambda: run(py(), "scripts/sandbox_check.py", *sys.argv[2:]),
    "sandbox-buyer": lambda: run(py(), "scripts/sandbox_buyer.py", *sys.argv[2:]),
    "sandbox-demo": lambda: run(py(), "scripts/sandbox_demo.py", *sys.argv[2:]),
    "test": lambda: run(py(), "-m", "pytest", "backend/tests", "-q", *sys.argv[2:]),
    "demo-video-check": lambda: run(py(), "demo-video/check_scenes.py", *sys.argv[2:]),
    "demo-video": lambda: run(py(), "demo-video/build_video.py", *sys.argv[2:]),
    "submission-check": lambda: (
        run(py(), "demo-video/check_scenes.py")
        or run("npm", "run", "build", cwd=ROOT / "frontend")
        or run(py(), "scripts/sandbox_check.py")
    ),
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        sys.exit(2)
    sys.exit(TASKS[sys.argv[1]]())
