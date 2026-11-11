"""Cut the demo video (`make demo-video`): recorded screen scenes + manually recorded clips, in scenes.json order.

Inputs:
- demo-video/out/screen.webm + demo-video/out/timing.json, written by the recorder (record_demo.py).
  timing.json: {"scenes": [{"id": "01_hook", "start": 0.0, "end": 12.1}, ...]} (seconds into screen.webm)
- demo-video/clips/*.mp4 for "type": "clip" scenes (gitignored; see demo-video/README.md)

Each screen scene is trimmed to its scenes.json duration (never extended); each clip is inserted at its scene's
position and trimmed to its duration (max 15 s). The cut must stay at or under max_total_seconds (175 s, under
3 minutes) or nothing is written. A missing clip is skipped with a warning (mock builds), unless --require-clips.
Output: demo-video/out/demo_silent.mp4 (1920x1080, 30 fps, no audio; the voice-over is mixed in a later step).

Usage: python demo-video/build_video.py [--require-clips] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import ROOT, Segment, load_scenes, plan  # noqa: E402

OUT = ROOT / "demo-video" / "out"
W, H, FPS = 1920, 1080, 30


def ffmpeg_args(segments: list[Segment], output: Path) -> list[str]:
    """One ffmpeg call: trim each segment, scale/pad to 1920x1080 at 30 fps, concat in order. Audio dropped."""
    inputs: list[str] = []
    filters: list[str] = []
    for i, seg in enumerate(segments):
        inputs += ["-ss", f"{seg.start:.3f}", "-t", f"{seg.duration:.3f}", "-i", str(ROOT / seg.source)]
        filters.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                       f"setsar=1,fps={FPS},format=yuv420p[v{i}]")
    concat = "".join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[out]"
    return ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join([*filters, concat]), "-map", "[out]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", str(output)]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--require-clips", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the cut and the ffmpeg command only")
    args = ap.parse_args()
    timing_path, screen = OUT / "timing.json", OUT / "screen.webm"
    if not (timing_path.exists() and screen.exists()):
        print("No screen recording yet (demo-video/out/screen.webm + timing.json). Record it first with the "
              "recorder (record_demo.py), then run this again.")
        return 1
    d = load_scenes()
    try:
        segments, warnings = plan(d, json.loads(timing_path.read_text(encoding="utf-8")),
                                  require_clips=args.require_clips)
    except ValueError as exc:
        print(f"ERROR {exc}")
        return 1
    for w in warnings:
        print(f"WARNING {w}")
    t = 0.0
    for seg in segments:
        print(f"  {t:6.1f}s  {seg.scene_id:<22} {seg.kind:<6} {seg.duration:5.1f}s  {seg.source}")
        t += seg.duration
    print(f"total {t:.1f} s (cap {d['max_total_seconds']} s)")
    output = OUT / "demo_silent.mp4"
    cmd = ffmpeg_args(segments, output)
    if args.dry_run:
        print(" ".join(cmd))
        return 0
    if shutil.which("ffmpeg") is None:
        print("ffmpeg isn't installed or not on PATH (https://ffmpeg.org/download.html).")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    print(f"wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
