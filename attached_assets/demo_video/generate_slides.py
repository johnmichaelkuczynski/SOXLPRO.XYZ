"""Generate branded slides for the SOXL Analysis Platform demo video."""
import math
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
OUT = "attached_assets/demo_video"

# Theme
BG_TOP = (10, 26, 47)       # deep navy
BG_BOT = (20, 58, 94)       # lighter navy
ACCENT = (74, 144, 217)     # primary blue
ACCENT_SOFT = (127, 179, 232)
BODY = (199, 214, 230)
MUTE = (120, 146, 173)
WHITE = (240, 246, 252)

FONT = "/nix/store"  # placeholder, resolve below

def load_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    # fall back to PIL bundled DejaVu
    import PIL
    import os
    pil_dir = os.path.join(os.path.dirname(PIL.__file__), "fonts")
    candidates.append(os.path.join(pil_dir, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"))
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def gradient_bg():
    img = Image.new("RGB", (W, H), BG_TOP)
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    return img


def draw_chart_motif(d, x0, y0, w, h, color, glow=True):
    """A stylized rising candlestick / line motif."""
    import random
    random.seed(7)
    pts = []
    n = 26
    val = 0.15
    for i in range(n):
        val += random.uniform(-0.05, 0.11)
        val = max(0.05, min(0.95, val))
        pts.append((x0 + w * i / (n - 1), y0 + h * (1 - val)))
    # area fill
    poly = pts + [(x0 + w, y0 + h), (x0, y0 + h)]
    fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fill_layer)
    fd.polygon(poly, fill=(color[0], color[1], color[2], 40))
    return fill_layer, pts


def wrap(d, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w_ in words:
        test = (cur + " " + w_).strip()
        if d.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def letter_space(d, pos, text, font, fill, spacing):
    x, y = pos
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing


SLIDES = [
    dict(kicker="INTRODUCING", title="SOXL Analysis Platform",
         body="Fifteen years of price history, probability math, and AI-built strategies — in one workspace.",
         title_slide=True),
    dict(kicker="SECURE BY DESIGN", title="Google Sign-In Gate",
         body="The entire application is authenticated before a single chart or number is loaded."),
    dict(kicker="EXPLORE", title="Chart & Probabilities",
         body="Interactive log-scale chart from 2010, benchmark overlays, and a historical probability engine for any move over any horizon."),
    dict(kicker="BUILD", title="AI Strategy Builder",
         body="Claude turns your portfolio, cash, and risk profile into a personalized, tranched, rules-based entry ladder."),
    dict(kicker="VALIDATE", title="Backtest & Allocation Engine",
         body="A 20% call-sleeve strategy with Black-Scholes pricing and full risk metrics versus buy-and-hold."),
    dict(kicker="TRUST", title="Three Live Diagnostics",
         body="System health, a synthetic-user simulator, and an OpenAI + GPTZero quality-control audit of every AI answer."),
    dict(kicker="PERSIST", title="Neon Postgres Audit Trail",
         body="Every diagnostic run is saved for a permanent record. Data, AI, and accountability — all in one place."),
]

N = len(SLIDES)
f_kicker = load_font(34, bold=True)
f_title = load_font(96, bold=True)
f_title_big = load_font(120, bold=True)
f_body = load_font(46)
f_brand = load_font(28, bold=True)
f_idx = load_font(28, bold=True)
f_num = load_font(220, bold=True)

for i, s in enumerate(SLIDES, 1):
    img = gradient_bg()
    d = ImageDraw.Draw(img, "RGBA")

    # faint background number
    num_txt = f"{i:02d}"
    d.text((W - 360, H - 360), num_txt, font=f_num, fill=(255, 255, 255, 12))

    # chart motif bottom
    fill_layer, pts = draw_chart_motif(d, 0, H * 0.55, W, H * 0.45, ACCENT)
    img = Image.alpha_composite(img.convert("RGBA"), fill_layer).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    d.line(pts, fill=(ACCENT_SOFT[0], ACCENT_SOFT[1], ACCENT_SOFT[2], 150), width=4, joint="curve")
    for p in pts[::3]:
        d.ellipse([p[0]-5, p[1]-5, p[0]+5, p[1]+5], fill=ACCENT)

    if s.get("title_slide"):
        # centered
        # accent dot
        d.ellipse([W/2-9, 300-9, W/2+9, 300+9], fill=ACCENT)
        kx = W/2
        kw = sum(d.textlength(c, font=f_kicker) + 8 for c in s["kicker"]) - 8
        letter_space(d, (kx - kw/2, 340), s["kicker"], f_kicker, ACCENT_SOFT, 8)
        tlines = wrap(d, s["title"], f_title_big, W - 320)
        ty = 430
        for ln in tlines:
            tw = d.textlength(ln, font=f_title_big)
            d.text((W/2 - tw/2, ty), ln, font=f_title_big, fill=WHITE)
            ty += 140
        blines = wrap(d, s["body"], f_body, W - 700)
        by = ty + 30
        for ln in blines:
            bw = d.textlength(ln, font=f_body)
            d.text((W/2 - bw/2, by), ln, font=f_body, fill=BODY)
            by += 62
    else:
        left = 150
        # accent bar
        d.rectangle([left, 300, left + 90, 312], fill=ACCENT)
        letter_space(d, (left, 340), s["kicker"], f_kicker, ACCENT_SOFT, 8)
        tlines = wrap(d, s["title"], f_title, W - 700)
        ty = 410
        for ln in tlines:
            d.text((left, ty), ln, font=f_title, fill=WHITE)
            ty += 118
        blines = wrap(d, s["body"], f_body, 1150)
        by = ty + 24
        for ln in blines:
            d.text((left, by), ln, font=f_body, fill=BODY)
            by += 62

    # footer brand + index
    d.text((150, H - 70), "SOXL ANALYSIS PLATFORM", font=f_brand, fill=MUTE)
    idx = f"{i:02d} / {N:02d}"
    iw = d.textlength(idx, font=f_idx)
    d.text((W - 150 - iw, H - 70), idx, font=f_idx, fill=MUTE)

    path = f"{OUT}/slide_{i:02d}.png"
    img.save(path)
    print("saved", path)

print("done", N, "slides")
