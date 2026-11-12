"""Use one recorded narration take (e.g. an ElevenLabs MP3, one scene per line) as the video's voice.

Whisper times every word of the take; the words are matched to each scene's script, and the take is
cut between scenes in the pause between them. Each scene becomes video-out/build/audio/<id>.wav with
its word timings (<id>.json), which build.py --skip-voice then uses.

Usage:  python demo-video/explainer/import_take.py take.mp3 --storyboard storyboard.json [--tempo 1.0]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import openai
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
AUDIO = ROOT / "video-out" / "build" / "audio"
FF = imageio_ffmpeg.get_ffmpeg_exe()


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def transcribe(client: openai.OpenAI, path: Path, prompt: str | None = None) -> list[dict]:
    with open(path, "rb") as fh:
        kw = {"prompt": prompt[-900:]} if prompt else {}
        tr = client.audio.transcriptions.create(model="whisper-1", file=fh, response_format="verbose_json",
                                                timestamp_granularities=["word"], **kw)
    return [{"w": w.word, "start": round(w.start, 3), "end": round(w.end, 3)} for w in (tr.words or [])]


def merge_split_words(words: list[dict]) -> list[dict]:
    """Whisper writes 'Channel3' as 'Channel 3'; join a word and a following bare number back together."""
    out: list[dict] = []
    for w in words:
        if out and re.fullmatch(r"\d+[.,!?]?", w["w"].strip()) and re.search(r"[A-Za-z]$", out[-1]["w"].strip()):
            out[-1] = {"w": out[-1]["w"].strip() + w["w"].strip(), "start": out[-1]["start"], "end": w["end"]}
        else:
            out.append(w)
    return out


def main() -> None:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--storyboard", default="storyboard.json")
    ap.add_argument("--tempo", type=float, default=1.0)
    ap.add_argument("--scenes", default="", help="comma-separated scene ids the take covers (default: all)")
    args = ap.parse_args()
    sb = json.loads((HERE / args.storyboard).read_text(encoding="utf-8"))
    only = [s for s in args.scenes.split(",") if s]
    scenes = [sc for sc in sb["scenes"] if not only or sc["id"] in only]
    client = openai.OpenAI()

    backup = AUDIO.parent / "audio_openai"
    if AUDIO.exists() and not backup.exists():
        shutil.copytree(AUDIO, backup)
    AUDIO.mkdir(parents=True, exist_ok=True)

    full = AUDIO.parent / "take_full.wav"
    subprocess.run([FF, "-y", "-v", "error", "-i", args.take, "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", str(full)], check=True)
    total = duration(full)
    glossary = sb.get("glossary") or "DropBack, Channel3, PayPal, APIMatic, AG Grid, MCP, Sartech Labs, Holloway, Beach Camera."
    heard = merge_split_words(transcribe(client, full, glossary))
    print(f"take {total:.1f}s, Whisper heard {len(heard)} words")

    # Script words, each tagged with its scene; matched to the heard words.
    script, owner = [], []
    for i, sc in enumerate(scenes):
        for w in sc["vo"].split():
            if norm(w):
                script.append(norm(w))
                owner.append(i)
    sm = difflib.SequenceMatcher(a=script, b=[norm(h["w"]) for h in heard], autojunk=False)
    first: dict[int, float] = {}
    last: dict[int, float] = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            s = owner[a + k]
            h = heard[b + k]
            first.setdefault(s, h["start"])
            first[s] = min(first[s], h["start"])
            last[s] = max(last.get(s, 0.0), h["end"])
    if len(scenes) - 1 not in first and len(scenes) - 2 in last:
        # The closing line often goes unmatched (names); it is whatever follows the previous scene.
        first[len(scenes) - 1], last[len(scenes) - 1] = last[len(scenes) - 2] + 0.05, total
    missing = [scenes[i]["id"] for i in range(len(scenes)) if i not in first]
    if missing:
        raise SystemExit(f"no words matched for {missing}; check the take")

    # Cut halfway through the pause between one scene's last word and the next scene's first word.
    cuts = [0.0]
    for i in range(len(scenes) - 1):
        a, b = last[i], first[i + 1]
        if b <= a:
            print(f"  ! {scenes[i + 1]['id']} overlaps the scene before it ({a:.2f} > {b:.2f})")
        cuts.append((a + b) / 2)
    cuts.append(total)

    trim = "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse"
    tempo = f",atempo={args.tempo}" if args.tempo != 1.0 else ""
    for i, sc in enumerate(scenes):
        wav = AUDIO / f"{sc['id']}.wav"
        subprocess.run([FF, "-y", "-v", "error", "-i", str(full), "-ss", f"{cuts[i]:.3f}", "-to", f"{cuts[i + 1]:.3f}",
                        "-af", trim + tempo, "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", str(wav)], check=True)
        words = transcribe(client, wav, sc["vo"])
        expected = len(sc["vo"].split())
        if len(words) < 0.8 * expected:
            plain = transcribe(client, wav)
            if len(plain) > len(words):
                words = plain
        d = duration(wav)
        flag = "" if len(words) >= 0.8 * expected else "  ! words missing"
        print(f"  {sc['id']}  {d:5.2f}s  {len(words)}/{expected} words{flag}")
        (AUDIO / f"{sc['id']}.json").write_text(json.dumps({"key": "take", "duration": d, "words": words}, indent=1))
    print("scene clips in", AUDIO)


if __name__ == "__main__":
    main()
