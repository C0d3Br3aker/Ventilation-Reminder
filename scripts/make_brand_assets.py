"""Generate Home Assistant brand assets for the Ventilation Reminder integration.

Motif: an open window with wind blowing in, plus a notification bubble that
says "you are being told to air the room".
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = (
    Path(__file__).resolve().parent.parent
    / "custom_components/ventilation_reminder/brand"
)
S = 1024  # supersampled canvas, downscaled at the end

BG_TOP = (46, 146, 208)
BG_BOTTOM = (21, 86, 145)
WHITE = (255, 255, 255, 255)
PANE = (206, 234, 250, 255)
GLASS = (138, 194, 232, 255)  # opaque: ImageDraw overwrites instead of blending
INK = (20, 82, 140, 255)

STROKE = int(S * 0.046)


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    return m


def gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    px_ = g.load()
    for y in range(size):
        t = y / (size - 1)
        px_[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return g.resize((size, size))


def px(*vals):
    return [int(S * v) for v in vals]


def bubble(d, cx, cy, w, h, fill, ink=None):
    """Notification bubble, tail pointing down-left towards the window.

    Called once oversized in the background colour to cut a gap out of whatever
    sits behind it, then again at full size with the exclamation mark.
    """
    x0, y0, x1, y1 = cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2
    d.polygon(
        [
            (x0 + int(w * 0.12), y1 - int(h * 0.12)),
            (x0 + int(w * 0.44), y1 - int(h * 0.02)),
            (x0 - int(w * 0.14), y1 + int(h * 0.30)),
        ],
        fill=fill,
    )
    d.rounded_rectangle([x0, y0, x1, y1], int(h * 0.34), fill=fill)

    if ink is None:
        return
    bar = int(w * 0.115)
    d.rounded_rectangle(
        [cx - bar // 2, cy - int(h * 0.26), cx + bar // 2, cy + int(h * 0.05)],
        bar // 2,
        fill=ink,
    )
    dot = int(bar * 0.62)
    dy = cy + int(h * 0.24)
    d.ellipse([cx - dot, dy - dot, cx + dot, dy + dot], fill=ink)


def build():
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    base.paste(
        gradient(S, BG_TOP, BG_BOTTOM).convert("RGBA"),
        (0, 0),
        rounded_mask(S, int(S * 0.22)),
    )
    d = ImageDraw.Draw(base)

    # Wall opening / closed half of the window.
    fx0, fy0, fx1, fy1 = px(0.10, 0.38, 0.43, 0.89)
    d.rounded_rectangle([fx0, fy0, fx1, fy1], int(S * 0.035), fill=GLASS)
    d.rounded_rectangle(
        [fx0, fy0, fx1, fy1], int(S * 0.035), outline=WHITE, width=STROKE
    )

    # Muntin cross, so the shape reads as a window rather than a panel.
    mun = int(S * 0.030)
    mx, my = (fx0 + fx1) // 2, (fy0 + fy1) // 2
    d.rectangle([mx - mun // 2, fy0, mx + mun // 2, fy1], fill=WHITE)
    d.rectangle([fx0, my - mun // 2, fx1, my + mun // 2], fill=WHITE)

    # Sash swung open on the right, drawn in perspective.
    ox = int(S * 0.63)
    sash = [
        (fx1, fy0),
        (ox, int(S * 0.45)),
        (ox, int(S * 0.82)),
        (fx1, fy1),
    ]
    d.polygon(sash, fill=PANE)
    d.line(sash + [sash[0]], fill=WHITE, width=STROKE, joint="curve")

    # Notification bubble above the open sash.
    bx, by, bw, bh = px(0.695, 0.255, 0.330, 0.275)
    halo = base.getpixel((bx, by - bh // 2 - STROKE))  # match the gradient behind it
    bubble(d, bx, by, bw + 2 * STROKE, bh + 2 * STROKE, halo)
    bubble(d, bx, by, bw, bh, WHITE, INK)

    return base.resize((256, 256), Image.LANCZOS), base.resize((512, 512), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon, icon2x = build()
    icon.save(OUT / "icon.png")
    icon2x.save(OUT / "icon@2x.png")
    icon.save(OUT / "logo.png")
    icon2x.save(OUT / "logo@2x.png")
    print("wrote", *(p.name for p in sorted(OUT.iterdir())))
