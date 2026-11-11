"""Shared demo-video logic: validate scenes.json, plan the final cut, write VIDEO_SCRIPT.md.

Used by check_scenes.py, build_video.py and tests. A scene with "type": "clip" is a manually
recorded clip (demo-video/clips/, gitignored): it has no actions, is at most `max_clip_seconds` long, and the
build inserts it at its position, trimmed to its duration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
SCENES_PATH = ROOT / "demo-video" / "scenes.json"
HARD_LIMIT_SECONDS = 180  # hackathon's "under 3 minutes"; scenes.json keeps a 5 s margin below it
ACTIONS = {"goto", "click", "hover", "type", "press", "wait_for", "wait", "scroll_to", "highlight"}
ID_RE = re.compile(r"\d\d[a-z]?_[a-z0-9_]+")


def load_scenes(path: Path = SCENES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_clip(scene: dict[str, Any]) -> bool:
    return scene.get("type") == "clip"


def total_seconds(d: dict[str, Any], *, with_clips: bool = True) -> int:
    return sum(s["duration"] for s in d["scenes"] if with_clips or not is_clip(s))


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def validate(d: dict[str, Any], root: Path = ROOT) -> tuple[list[str], list[str]]:
    """(errors, warnings). A missing clip file is only a warning: the mock build skips that scene."""
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("title", "viewport", "voice", "words_per_minute", "max_total_seconds", "scenes"):
        if key not in d:
            errors.append(f"scenes.json: missing '{key}'")
    if errors:
        return errors, warnings
    cap = d["max_total_seconds"]
    if cap >= HARD_LIMIT_SECONDS:
        errors.append(f"max_total_seconds {cap} must stay under {HARD_LIMIT_SECONDS} (3 minutes)")
    total = total_seconds(d)
    if total > cap:
        errors.append(f"total {total} s is over max_total_seconds {cap} (clips included)")
    wpm, max_clip = d["words_per_minute"], d.get("max_clip_seconds", 15)
    seen: set[str] = set()
    for s in d["scenes"]:
        sid = s.get("id", "?")
        if not ID_RE.fullmatch(sid):
            errors.append(f"{sid}: id must look like 01_name or 03b_name")
        if sid in seen:
            errors.append(f"{sid}: duplicate id")
        seen.add(sid)
        for key in ("duration", "on_screen", "narration", "actions"):
            if key not in s:
                errors.append(f"{sid}: missing '{key}'")
        if not isinstance(s.get("duration"), int) or s.get("duration", 0) <= 0:
            errors.append(f"{sid}: duration must be a positive whole number of seconds")
            continue
        if words(s.get("narration", "")) > s["duration"] * wpm / 60:
            errors.append(f"{sid}: {words(s['narration'])} words don't fit {s['duration']} s at {wpm} wpm")
        if is_clip(s):
            clip = s.get("clip", "")
            if not clip.startswith("demo-video/clips/"):
                errors.append(f"{sid}: clip must live in demo-video/clips/ (gitignored), got {clip!r}")
            if s["duration"] > max_clip:
                errors.append(f"{sid}: clip scene is {s['duration']} s; the limit is {max_clip} s")
            if s.get("actions"):
                errors.append(f"{sid}: a clip scene has no actions")
            if clip and not (root / clip).exists():
                warnings.append(f"{sid}: {clip} is missing; record it (demo-video/README.md). A mock build skips this scene.")
        else:
            if not s.get("actions"):
                errors.append(f"{sid}: needs at least one action")
            for a in s.get("actions", []):
                if a.get("action") not in ACTIONS:
                    errors.append(f"{sid}: unknown action {a.get('action')!r}")
    return errors, warnings


def missing_targets(d: dict[str, Any], ui_source: str) -> list[str]:
    """Action targets with no data-testid in the UI source."""
    out = []
    for s in d["scenes"]:
        for a in s.get("actions", []):
            t = a.get("target")
            if not t:
                continue
            if not re.search(rf"""data-testid="{re.escape(t)}"|["'`]{re.escape(t)}["'`]""", ui_source):
                out.append(f"{s['id']}: target {t!r} not found in the UI")
    return out


class Segment(BaseModel):
    scene_id: str
    kind: str  # screen | clip
    source: str  # path of the screen recording or the clip
    start: float = 0.0  # where the scene starts in `source`
    duration: float  # trimmed to the scene's duration, never extended


def plan(d: dict[str, Any], timing: dict[str, Any], *, root: Path = ROOT, screen: str = "demo-video/out/screen.webm",
         require_clips: bool = False) -> tuple[list[Segment], list[str]]:
    """The final cut, in scene order: recorded screen segments (from timing.json) with each clip inserted at its
    scene's position and trimmed to its duration. Returns (segments, warnings); raises ValueError on a problem."""
    recorded = {t["id"]: t for t in timing.get("scenes", [])}
    segments: list[Segment] = []
    warnings: list[str] = []
    for s in d["scenes"]:
        if is_clip(s):
            if not (root / s["clip"]).exists():
                if require_clips:
                    raise ValueError(f"{s['id']}: {s['clip']} is missing (--require-clips)")
                warnings.append(f"{s['id']}: {s['clip']} missing; scene skipped")
                continue
            segments.append(Segment(scene_id=s["id"], kind="clip", source=s["clip"], duration=s["duration"]))
            continue
        t = recorded.get(s["id"])
        if t is None:
            raise ValueError(f"{s['id']}: not in timing.json; record the demo again")
        length = min(float(t["end"]) - float(t["start"]), float(s["duration"]))
        segments.append(Segment(scene_id=s["id"], kind="screen", source=screen, start=float(t["start"]),
                                duration=round(length, 3)))
    total = sum(x.duration for x in segments)
    if total > d["max_total_seconds"] or total >= HARD_LIMIT_SECONDS:
        raise ValueError(f"the cut is {total:.1f} s; it must be at most {d['max_total_seconds']} s (under 3 minutes)")
    return segments, warnings


def video_script_md(d: dict[str, Any]) -> str:
    rows = ["# DropBack Demo Video Script", "", f"Generated from `demo-video/scenes.json` by `check_scenes.py`. "
            f"Total {total_seconds(d)} s (cap {d['max_total_seconds']} s; clips included), "
            f"{d['words_per_minute']} wpm voice-over.", "",
            "| Time | Scene | Caption | Actions | Voice-over |", "|---|---|---|---|---|"]
    t = 0
    for s in d["scenes"]:
        start, t = t, t + s["duration"]
        acts = (f"**clip** `{s['clip']}` (recorded by hand)" if is_clip(s) else
                "; ".join(a["action"] + (f" `{a.get('target') or a.get('url')}`" if a.get("target") or a.get("url")
                                         else "") for a in s["actions"]))
        rows.append(f"| {start // 60}:{start % 60:02d}-{t // 60}:{t % 60:02d} | {s['id']} | {s['on_screen']} | "
                    f"{acts} | {s['narration']} |")
    return "\n".join(rows) + "\n"
