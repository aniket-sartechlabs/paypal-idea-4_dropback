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
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from videolib import ROOT, Segment, load_scenes, plan  # noqa: E402

OUT = ROOT / "demo-video" / "out"
W, H, FPS = 1920, 1080, 30


def _subtitle_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


def write_subtitles(segments: list[Segment], scene_data: dict) -> Path:
    scenes = {scene["id"]: scene for scene in scene_data["scenes"]}
    cues: list[str] = []
    cursor = 0.0
    for index, segment in enumerate(segments, 1):
        caption = scenes[segment.scene_id]["on_screen"].replace("\n", " ").strip()
        end = cursor + segment.duration
        cues.append(f"{index}\n{_subtitle_time(cursor)} --> {_subtitle_time(end)}\n{caption}\n")
        cursor = end
    path = OUT / "captions.srt"
    path.write_text("\n".join(cues), encoding="utf-8")
    return path


def make_voiceover(segments: list[Segment], scene_data: dict) -> list[tuple[Path, float]]:
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    if not binary:
        print("WARNING: espeak is unavailable; the video will include captions without narration audio.")
        return []
    scenes = {scene["id"]: scene for scene in scene_data["scenes"]}
    tracks: list[tuple[Path, float]] = []
    cursor = 0.0
    for segment in segments:
        scene = scenes[segment.scene_id]
        words = len(scene["narration"].split())
        target_rate = math.ceil(words * 60 / max(segment.duration - 0.5, 1))
        speed = min(220, max(145, target_rate))
        voice_path = OUT / f"voice_{segment.scene_id}.wav"
        command = [binary, "-v", "en-us+f3", "-s", str(speed), "-w", str(voice_path), scene["narration"]]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, FileNotFoundError):
            command[2] = "en-us"
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tracks.append((voice_path, cursor))
        cursor += segment.duration
    return tracks


def ffmpeg_args(segments: list[Segment], output: Path, *, audio_tracks: list[tuple[Path, float]], subtitles: Path) -> list[str]:
    """One ffmpeg call trims and concatenates the scenes, captions them, and mixes synthesized narration."""
    inputs: list[str] = []
    filters: list[str] = []
    for i, seg in enumerate(segments):
        inputs += ["-ss", f"{seg.start:.3f}", "-t", f"{seg.duration:.3f}", "-i", str(ROOT / seg.source)]
        filters.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                       f"setsar=1,fps={FPS},format=yuv420p[v{i}]")
    caption_path = str(subtitles.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    concat = "".join(f"[v{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[joined]"
    filters.append(f"[joined]subtitles=filename='{caption_path}':force_style='FontName=Arial,FontSize=21,Outline=2,Shadow=1,MarginV=64'[outv]")
    duration = sum(segment.duration for segment in segments)
    for index, (audio_path, start) in enumerate(audio_tracks):
        input_index = len(segments) + index
        inputs.extend(["-i", str(audio_path)])
        delay = round(start * 1000)
        filters.append(f"[{input_index}:a]adelay={delay}|{delay},apad=whole_dur={duration:.3f},volume=0.92[a{index}]")
    if audio_tracks:
        mix = "".join(f"[a{i}]" for i in range(len(audio_tracks)))
        filters.append(f"{mix}amix=inputs={len(audio_tracks)}:duration=longest:normalize=0[outa]")
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join([*filters, concat]), "-map", "[outv]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-movflags", "+faststart", "-t", f"{duration:.3f}"]
    if audio_tracks:
        cmd.extend(["-map", "[outa]", "-c:a", "aac", "-b:a", "160k"])
    return [*cmd, str(output)]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-missing-clips", action="store_true", help="Build a preview even when the PayPal approval clip is missing.")
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
                                  require_clips=not args.allow_missing_clips)
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
    output = OUT / "dropback-sandbox-demo.mp4"
    subtitle_file = write_subtitles(segments, d)
    audio_tracks = [] if args.dry_run else make_voiceover(segments, d)
    cmd = ffmpeg_args(segments, output, audio_tracks=audio_tracks, subtitles=subtitle_file)
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
