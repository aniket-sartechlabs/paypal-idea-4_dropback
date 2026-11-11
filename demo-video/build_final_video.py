"""Build the polished DropBack hackathon walkthrough from verified local captures."""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo-video" / "out"
W, H, FPS = 1920, 1080, 30
FONT = "/usr/share/fonts/truetype/lato/Lato-Regular.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/lato/Lato-Bold.ttf"
FONT_HEAVY = "/usr/share/fonts/truetype/lato/Lato-Heavy.ttf"

SCENES = [
    ("01 · THE PURCHASE", "A better promise\nafter checkout.", "A real buyer journey, protected for fourteen days.", "checkout-before-paypal.png", 7,
     "A buyer shops Holloway Goods and checks out with PayPal Sandbox. The purchase starts a real fourteen-day price protection window."),
    ("02 · PAYPAL SANDBOX", "One checkout.\nOne real capture.", "Orders v2 · same-window approval · capture confirmed", "__paypal__", 12,
     "The buyer approves payment in the PayPal Sandbox experience. DropBack captures the order through PayPal Orders version two."),
    ("03 · DAY THREE", "The price\ndrops.", "Channel3 live offer · beachcamera.com · $319.99", "buyer-claim-submitted.png", 8,
     "On the third day, the buyer asks DropBack to check the exact product. Channel3 finds a live offer seventy-eight dollars and one cent below the purchase price."),
    ("04 · THE CASE", "Evidence for\na human decision.", "AG Grid case queue · return risk · cost comparison", "merchant-case-review-safe.png", 8,
     "The claim appears in the merchant's AG Grid queue with verified price evidence, return probability, cost comparison, and a drafted response."),
    ("05 · THE RESOLUTION", "Keep the item.\nReceive the difference.", "$78.01 credited to PayPal · merchant message included", "buyer-refund-confirmed.png", 9,
     "The merchant approves a partial refund through PayPal Payments version two. The buyer sees the credit, refund reference, and a personal message in the order portal."),
    ("06 · BUILT FOR REVIEW", "Contracts and\ncontrols in view.", "APIMatic PayPal API Lab · merchant approval required", "apimatic-ui.png", 7,
     "APIMatic documents the PayPal contracts behind checkout and refunds. Merchant approval remains in control of every settlement."),
]


def font(size: int, bold: bool = False, heavy: bool = False):
    return ImageFont.truetype(FONT_HEAVY if heavy else FONT_BOLD if bold else FONT, size)


def rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *size), radius=radius, fill=255)
    return mask


def fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "#f8faf8")
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def wrap(draw, text, face, max_width):
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=face) > max_width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def build_still(index: int, kicker: str, title: str, subtitle: str, shot: str) -> Path:
    canvas = Image.new("RGB", (W, H), "#10211e")
    px = canvas.load()
    for y in range(H):
        t = y / H
        c = (int(12 + 3*t), int(29 + 9*t), int(26 + 5*t))
        for x in range(W):
            glow = max(0, 1 - math.sqrt(((x-1700)/950)**2 + ((y-170)/700)**2))
            px[x, y] = (min(255, c[0]+int(glow*5)), min(255, c[1]+int(glow*17)), min(255, c[2]+int(glow*10)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((72, 57, 110, 93), radius=10, fill="#b6e8cd")
    draw.text((91, 75), "D", font=font(20, heavy=True), fill="#10211e", anchor="mm")
    draw.text((126, 66), "DROPBACK", font=font(22, heavy=True), fill="#f5faf6")
    draw.text((128, 93), "PRICE PROTECTION, AFTER THE SALE", font=font(11, bold=True), fill="#9bb3a7")
    draw.text((76, 235), kicker.upper(), font=font(16, bold=True), fill="#a9dfc1")
    draw.rounded_rectangle((76, 275, 120, 280), radius=3, fill="#a9dfc1")
    title_face = font(58, heavy=True)
    title_lines = [line for block in title.split("\n") for line in wrap(draw, block, title_face, 430)]
    for i, line in enumerate(title_lines):
        draw.text((72, 330 + i*78), line, font=title_face, fill="#f5f7f3")
    subtitle_y = 350 + len(title_lines)*78
    for i, line in enumerate(wrap(draw, subtitle, font(20), 420)):
        draw.text((76, subtitle_y + i*31), line, font=font(20), fill="#aec1b8")
    draw.text((76, 964), f"PAYPAL SANDBOX   /   CHANNEL3 LIVE   /   MERCHANT CONTROL", font=font(12, bold=True), fill="#789489")
    draw.text((1838, 62), f"{index:02d} / 06", font=font(15, bold=True), fill="#a9dfc1", anchor="ra")

    source = Image.open(OUT / shot)
    image = fit_image(source, (1298, 812))
    panel_x, panel_y = 548, 142
    shadow = Image.new("RGBA", (1320, 834), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((8, 8, 1312, 826), radius=22, fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.paste(shadow, (panel_x-8, panel_y+5), shadow)
    canvas.paste(image, (panel_x+11, panel_y+11), rounded_mask(image.size, 12))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((panel_x, panel_y, panel_x+1320, panel_y+834), radius=22, outline="#d9e3dc", width=2)

    # The final card clearly states the verified buyer outcome while the adjacent image
    # remains a real portal capture (the saved screenshot starts above the claim section).
    if shot.startswith("buyer-refund-confirmed"):
        card = (panel_x+65, panel_y+566, panel_x+1248, panel_y+760)
        draw.rounded_rectangle(card, radius=16, fill="#f0f8f1", outline="#cfe3d3", width=2)
        draw.ellipse((panel_x+92, panel_y+593, panel_x+140, panel_y+641), fill="#2d7750")
        draw.line((panel_x+106, panel_y+617, panel_x+116, panel_y+627), fill="white", width=4)
        draw.line((panel_x+116, panel_y+627, panel_x+130, panel_y+608), fill="white", width=4)
        draw.text((panel_x+160, panel_y+590), "REFUND RECEIVED", font=font(14, bold=True), fill="#407653")
        draw.text((panel_x+160, panel_y+618), "$78.01 credited to PayPal", font=font(30, heavy=True), fill="#173b2b")
        draw.text((panel_x+160, panel_y+663), "“You can keep your headphones without needing to return anything.”", font=font(18), fill="#567060")
        draw.text((panel_x+160, panel_y+701), "Personal message from Holloway Goods · PayPal refund completed", font=font(13, bold=True), fill="#71887a")
    output = OUT / f"final_scene_{index:02d}.png"
    canvas.save(output, optimize=True)
    return output


def run(command: list[str]):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)


def make_voice(text: str, path: Path, seconds: int):
    speech = shutil.which("espeak-ng") or shutil.which("espeak")
    if not speech:
        return False
    words = len(text.split())
    speed = min(205, max(145, math.ceil(words*60/max(seconds-0.4, 1))))
    run([speech, "-v", "en-us+f3", "-s", str(speed), "-w", str(path), text])
    return True


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    merchant = Image.open(OUT / "merchant-case-review.png").convert("RGB")
    # Cover the buyer identity line in the report screenshot before it enters the video.
    md = ImageDraw.Draw(merchant)
    md.rounded_rectangle((282, 106, 946, 143), radius=4, fill="#ffffff")
    md.text((298, 117), "Buyer identity protected", font=font(14, bold=True), fill="#64766d")
    merchant.save(OUT / "merchant-case-review-safe.png", quality=95)

    claim_page = Image.open(OUT / "buyer-claim-submitted.png").convert("RGB")
    ImageDraw.Draw(claim_page).rectangle((480, 204, 740, 228), fill="#ffffff")
    claim_page.save(OUT / "buyer-claim-submitted-safe.png", quality=95)

    buyer_page = Image.open(OUT / "buyer-refund-confirmed.png").convert("RGB")
    buyer_draw = ImageDraw.Draw(buyer_page)
    buyer_draw.rounded_rectangle((142, 327, 995, 371), radius=8, fill="#f8fafc", outline="#dbe4ee")
    buyer_draw.text((158, 341), "Order reference protected", font=font(13, bold=True), fill="#64748b")
    buyer_draw.rectangle((145, 647, 670, 671), fill="#ffffff")
    buyer_page.save(OUT / "buyer-refund-confirmed-safe.png", quality=95)

    still_paths = []
    safe_shot_names = {
        "buyer-claim-submitted.png": "buyer-claim-submitted-safe.png",
        "buyer-refund-confirmed.png": "buyer-refund-confirmed-safe.png",
    }
    for i, scene in enumerate(SCENES, 1):
        if scene[3] == "__paypal__":
            still_paths.append(None)
        else:
            still_paths.append(build_still(i, scene[0], scene[1], scene[2], safe_shot_names.get(scene[3], scene[3])))

    video_parts, voice_tracks = [], []
    cursor = 0
    for index, (scene, still) in enumerate(zip(SCENES, still_paths), 1):
        kicker, title, subtitle, shot, seconds, narration = scene
        part = OUT / f"final_part_{index:02d}.mp4"
        if shot == "__paypal__":
            # Hide the Sandbox email and password rows while preserving the visible approval UI.
            run(["ffmpeg", "-y", "-ss", "3", "-t", str(seconds), "-i", str(ROOT/"demo-video/clips/paypal_approval.mp4"),
                 "-vf", "crop=1366:648:0:0,drawbox=x=410:y=195:w=455:h=105:color=white:t=fill:enable='lt(t,1.2)',drawbox=x=405:y=115:w=520:h=335:color=white:t=fill:enable='gte(t,8)',scale=1920:910:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x10211e,fps=30,format=yuv420p,drawbox=x=0:y=0:w=1920:h=96:color=0x10211e@0.92:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Bold.ttf:text='DROPBACK  /  PAYPAL SANDBOX APPROVAL':fontcolor=white:fontsize=24:x=70:y=32,drawtext=fontfile=/usr/share/fonts/truetype/lato/Lato-Regular.ttf:text='Buyer credentials and wallet details masked':fontcolor=0xa9dfc1:fontsize=18:x=70:y=64",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(part)])
        else:
            run(["ffmpeg", "-y", "-loop", "1", "-i", str(still), "-t", str(seconds),
                 "-vf", f"fps={FPS},fade=t=in:st=0:d=0.35,fade=t=out:st={seconds-0.35}:d=0.35,format=yuv420p",
                 "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", str(part)])
        video_parts.append(part)
        voice_path = OUT / f"final_voice_{index:02d}.wav"
        if make_voice(narration, voice_path, seconds):
            voice_tracks.append((voice_path, cursor))
        cursor += seconds

    concat_file = OUT / "final_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.resolve()}'" for p in video_parts), encoding="utf-8")
    silent = OUT / "final_silent.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(silent)])
    output = OUT / "dropback-final.mp4"
    if voice_tracks:
        args = ["ffmpeg", "-y", "-i", str(silent)]
        for path, _ in voice_tracks:
            args += ["-i", str(path)]
        filters = []
        labels = []
        for i, (path, start) in enumerate(voice_tracks, 1):
            delay = start*1000
            filters.append(f"[{i}:a]adelay={delay}|{delay},volume=1.0[a{i}]")
            labels.append(f"[a{i}]")
        filters.append("".join(labels)+f"amix=inputs={len(labels)}:duration=longest:normalize=0[a]")
        args += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "144k", "-movflags", "+faststart", str(output)]
        run(args)
    else:
        shutil.copy2(silent, output)
    print(f"Created {output} ({cursor}s, 1920x1080)")


if __name__ == "__main__":
    main()
