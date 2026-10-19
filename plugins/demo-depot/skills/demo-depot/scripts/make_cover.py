#!/usr/bin/env python3
"""
Make a 1600×900 cover image for a demo when no good screenshot exists.

    python3 make_cover.py --name "Targeting Visualization" --summary "One sentence." [--image shot.png] media/cover.png

Draws a dark title card with the demo name, the summary, and an optional image (a screenshot or logo)
fitted on the right without stretching. Needs Pillow. If Pillow isn't installed locally, run it in a
container from the repo root:

    docker run --rm -v "$PWD":/w -w /w python:3.12-slim sh -c \\
      "pip install -q pillow && python3 .claude/skills/demo-depot/scripts/make_cover.py --name '…' --summary '…' media/cover.png"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

W, H = 1600, 900
BG = (18, 20, 28)
ACCENT = (64, 91, 255)
FG = (245, 246, 250)
MUTED = (170, 176, 196)


def font(size: int):
    from PIL import ImageFont

    for name in ("Inter-SemiBold.ttf", "Helvetica.ttc", "/System/Library/Fonts/Helvetica.ttc", "DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow ≥ 10.1
    except TypeError:
        return ImageFont.load_default()


def wrap(draw, text: str, f, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--name", required=True)
    ap.add_argument("--summary", default="")
    ap.add_argument("--image", help="screenshot or logo to place on the right (kept in proportion)")
    ap.add_argument("--kicker", default="LaunchDarkly demo")
    a = ap.parse_args()
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow is not installed. Either `pip install pillow` or run this script in a container (see the docstring).",
              file=sys.stderr)
        return 2

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # accent bar and subtle grid
    d.rectangle([0, 0, 18, H], fill=ACCENT)
    for x in range(80, W, 80):
        d.line([(x, 0), (x, H)], fill=(24, 27, 37), width=1)
    for y in range(80, H, 80):
        d.line([(0, y), (W, y)], fill=(24, 27, 37), width=1)

    text_w = W - 160
    if a.image and Path(a.image).exists():
        shot = Image.open(a.image).convert("RGBA")
        box_w, box_h = 700, 620
        shot.thumbnail((box_w, box_h))
        panel = Image.new("RGBA", (shot.width + 24, shot.height + 24), (32, 36, 50, 255))
        panel.paste(shot, (12, 12), shot)
        img.paste(panel, (W - panel.width - 80, (H - panel.height) // 2), panel)
        text_w = W - panel.width - 240

    y = 170
    d.text((80, y), a.kicker.upper(), font=font(28), fill=ACCENT)
    y += 70
    title_f = font(84 if len(a.name) < 24 else 64)
    for line in wrap(d, a.name, title_f, text_w):
        d.text((80, y), line, font=title_f, fill=FG)
        y += int(title_f.size * 1.15)
    if a.summary:
        y += 24
        sum_f = font(34)
        for line in wrap(d, a.summary, sum_f, text_w)[:4]:
            d.text((80, y), line, font=sum_f, fill=MUTED)
            y += int(sum_f.size * 1.4)
    d.text((80, H - 90), "Demo Depot", font=font(26), fill=MUTED)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    print(f"wrote {out} ({W}x{H}, {out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
