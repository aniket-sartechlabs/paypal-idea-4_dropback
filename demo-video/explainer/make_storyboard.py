"""Fill storyboard.template.json with the real run's numbers and timings.

Inputs (from record_live.py): video-out/rec_live/facts.json, marks.json, rects.json.
Outputs:
  storyboard.json   scenes for build.py; recording scenes get from/to (seconds in live.webm) and
                    highlight boxes (x/y/w/h from rects.json); `vo` is the spoken text
  vo_sariga.txt     the ElevenLabs (v3) script for the Sariga voice: one scene per line, with tags.
                    Paste it into ElevenLabs, download the MP3, then run import_take.py.

Usage:
  python demo-video/explainer/make_storyboard.py              # after a recording
  python demo-video/explainer/make_storyboard.py --sample     # sample numbers, graphics scenes only (preview)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REC = ROOT / "video-out" / "rec_live"
KEEP_CAPS = {"AI", "SDK", "MCP", "AG", "API", "USD", "NRF", "US"}

SAMPLE = {"paid": 398.0, "offer": 348.0, "diff": 50.0, "retailer": "bestbuy.com", "return_cost": 141.36, "probability": 0.6,
          "refund": 50.0, "refund_status": "COMPLETED", "window_days": 14,
          "loss_if_returned": 260.76, "net_savings": 106.46, "retailer_name": "Best Buy", "offers_checked": 8,
          "c3_days": 52, "c3_low": 298.0, "c3_high": 398.0}


def money(x) -> str:
    v = float(x)
    return f"${v:,.0f}" if abs(v - round(v)) < 0.005 else f"${v:,.2f}"


def tokens(f: dict) -> dict[str, str]:
    return {
        "paid": money(f["paid"]), "offer": money(f["offer"]), "diff": money(f["diff"]),
        "retailer": str(f.get("retailer") or "another retailer"), "return_cost": f"${round(float(f['return_cost'])):,}",
        "probability": str(round(float(f["probability"]) * 100)), "refund": money(f["refund"]),
        "refund_status": str(f.get("refund_status") or "completed").lower(), "window": str(f.get("window_days") or 14),
        "loss": f"${round(float(f.get('loss_if_returned') or f['return_cost'])):,}", "saving": f"${round(float(f.get('net_savings') or 0)):,}",
        "retailer_name": str(f.get("retailer_name") or f.get("retailer") or "another retailer"),
        "offers_checked": str(f.get("offers_checked") or "all"),
        "c3_range": (f"held steady at {money(f['c3_high'])}" if f.get("c3_low") and abs(float(f["c3_low"]) - float(f["c3_high"])) < 0.01
                     else f"ranged from {money(f.get('c3_low') or f['offer'])} to {money(f.get('c3_high') or f['paid'])}"),
        "c3_days": str(f.get("c3_days") or 90), "c3_low": money(f.get("c3_low") or f["offer"]), "c3_high": money(f.get("c3_high") or f["paid"]),
    }


def fill(obj, tok: dict[str, str]):
    if isinstance(obj, str):
        return re.sub(r"\{(\w+)\}", lambda m: tok.get(m.group(1), m.group(0)), obj)
    if isinstance(obj, list):
        return [fill(x, tok) for x in obj]
    if isinstance(obj, dict):
        return {k: fill(v, tok) for k, v in obj.items()}
    return obj


def spoken(say: str) -> str:
    """ElevenLabs line -> plain words: drop [tags] and ellipses, un-shout emphasis."""
    text = re.sub(r"\[[^\]]+\]", " ", say).replace("…", " ").replace("...", " ")
    words = []
    for w in text.split():
        core = re.sub(r"[^A-Za-z]", "", w)
        if len(core) >= 3 and core.isupper() and core not in KEEP_CAPS:
            w = w.replace(core, core.lower())
        words.append(w)
    return " ".join(words)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="use sample numbers and drop recording scenes (for previews)")
    args = ap.parse_args()
    sb = json.loads((HERE / "storyboard.template.json").read_text(encoding="utf-8"))
    if args.sample:
        facts, marks, rects = SAMPLE, {}, {}
        sb["output"] = "dropback-preview-graphics.mp4"
    else:
        facts = json.loads((REC / "facts.json").read_text(encoding="utf-8"))
        marks = json.loads((REC / "marks.json").read_text(encoding="utf-8"))
        rects = json.loads((REC / "rects.json").read_text(encoding="utf-8"))
        missing = [k for k in ("paid", "offer", "diff", "return_cost", "probability", "refund", "loss_if_returned", "net_savings") if facts.get(k) in (None, "")]
        if missing:
            raise SystemExit(f"facts.json is missing {missing}; re-run record_live.py")
    tok = tokens(facts)
    scenes = []
    for sc in sb["scenes"]:
        sc = fill(sc, tok)
        v = sc["visual"]
        if v.get("type") == "rec":
            if args.sample:
                continue
            pad = v.pop("pad", [0, 0])
            v["from"] = round(max(0.0, marks[v.pop("mark")] + pad[0]), 2)
            v["to"] = round(marks[v.pop("until")] + pad[1], 2)
            boxes = []
            for b in v.get("boxes", []):
                r = rects.get(b.pop("rect"))
                if r:
                    boxes.append({**b, **{k: r[k] for k in ("x", "y", "w", "h")}})
            v["boxes"] = boxes
        sc["vo"] = spoken(sc["say"])
        scenes.append(sc)
    sb["scenes"] = scenes
    sb["facts"] = {k: facts.get(k) for k in ("paypal_order_id", "capture_id", "paypal_refund_id", "claim_id", "provider", "model") if facts.get(k)}
    (HERE / "storyboard.json").write_text(json.dumps(sb, indent=1, ensure_ascii=False), encoding="utf-8")
    (HERE / "vo_sariga.txt").write_text("\n".join(sc["say"] for sc in scenes) + "\n", encoding="utf-8")
    words = sum(len(sc["vo"].split()) for sc in scenes)
    print(f"{len(scenes)} scenes, {words} spoken words (~{words / 2.55:.0f}s at a brisk pace)")
    print("wrote", HERE / "storyboard.json", "and", HERE / "vo_sariga.txt")


if __name__ == "__main__":
    main()
