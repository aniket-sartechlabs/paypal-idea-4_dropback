"""Check demo-video/scenes.json without making a video (`make demo-video-check`).

- schema, unique ids, durations, the under-3-minutes cap (clips included), narration at 125 wpm per scene
- every action target is a data-testid the UI has (React components & HTML in frontend/src)
- clip scenes: the file is in demo-video/clips/ and at most max_clip_seconds; a MISSING clip is only a warning
  (the mock build skips it) unless --require-clips
- writes demo-video/VIDEO_SCRIPT.md
Exit code 1 on any error.

Usage: python demo-video/check_scenes.py [--base-url http://127.0.0.1:5173] [--require-clips]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import ROOT, load_scenes, missing_targets, total_seconds, validate, video_script_md  # noqa: E402

PAGES = ("/store", "/portal", "/portal/sample-order-maya-sony", "/claims", "/apimatic")


def ui_source(base_url: str | None) -> str:
    src_dir = ROOT / "frontend" / "src"
    files = list(src_dir.glob("*.tsx")) + list(src_dir.glob("*.ts")) + [ROOT / "frontend" / "index.html"]
    parts = [f.read_text(encoding="utf-8") for f in files if f.exists()]
    if base_url:
        for page in PAGES:
            try:
                parts.append(httpx.get(base_url.rstrip("/") + page, timeout=5).text)
            except Exception:
                pass
    return "\n".join(parts)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="also check the running app's pages")
    ap.add_argument("--require-clips", action="store_true", help="a missing clip is an error, not a warning")
    args = ap.parse_args()
    d = load_scenes()
    errors, warnings = validate(d)
    errors += missing_targets(d, ui_source(args.base_url))
    if args.require_clips:
        errors += [w for w in warnings if "missing" in w]
        warnings = [w for w in warnings if "missing" not in w]
    out = ROOT / "demo-video" / "VIDEO_SCRIPT.md"
    out.write_text(video_script_md(d), encoding="utf-8")
    print(f"{len(d['scenes'])} scenes, {total_seconds(d)} s with clips / {total_seconds(d, with_clips=False)} s "
          f"without (cap {d['max_total_seconds']} s). Wrote {out.relative_to(ROOT)}.")
    for w in warnings:
        print(f"WARNING {w}")
    for e in errors:
        print(f"ERROR   {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
