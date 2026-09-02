from pathlib import Path
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
OUT = Path(__file__).parent
NAVY = (5, 18, 31)
NAVY_2 = (10, 39, 58)
WHITE = (245, 249, 252)
BODY = (188, 208, 222)
CYAN = (42, 203, 255)
MINT = (48, 224, 174)
YELLOW = (255, 201, 71)
RED = (255, 100, 110)


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    paths = [
        f"/usr/share/fonts/truetype/dejavu/{name}",
        f"/usr/share/fonts/{name}",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


F_BRAND = font(22, True)
F_KICKER = font(20, True)
F_TITLE = font(60, True)
F_BODY = font(28)
F_SMALL = font(18)
F_STAT = font(46, True)


def background():
    top = Image.new("RGB", (1, 1), NAVY)
    bottom = Image.new("RGB", (1, 1), NAVY_2)
    img = Image.new("RGB", (W, H))
    for y in range(H):
        t = y / (H - 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(NAVY, NAVY_2))
        ImageDraw.Draw(img).line((0, y, W, y), fill=color)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((760, -290, 1450, 400), fill=(*CYAN, 22))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def wrap(draw, text, fnt, max_width):
    words, lines, current = text.split(), [], ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textlength(test, font=fnt) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def chrome(img, index, accent=CYAN):
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((52, 36, 190, 74), radius=19, outline=accent, width=2)
    d.text((77, 44), "SOXL PRO", font=F_BRAND, fill=WHITE)
    d.text((52, 670), "SOXLPRO.XYZ", font=F_BRAND, fill=BODY)
    d.text((1050, 672), f"{index:02d}  /  08", font=F_SMALL, fill=(130, 160, 178))
    d.line((52, 650, 1228, 650), fill=(255, 255, 255, 35), width=1)


def heading(d, kicker, title, body=None, accent=CYAN, width=690):
    d.rectangle((54, 124, 60, 166), fill=accent)
    d.text((78, 124), kicker.upper(), font=F_KICKER, fill=accent)
    y = 176
    for line in wrap(d, title, F_TITLE, width):
        d.text((52, y), line, font=F_TITLE, fill=WHITE)
        y += 70
    if body:
        y += 14
        for line in wrap(d, body, F_BODY, width):
            d.text((54, y), line, font=F_BODY, fill=BODY)
            y += 39
    return y


def draw_line_chart(d, box, color=CYAN, seed=3, mean_revert=False):
    x0, y0, x1, y1 = box
    for i in range(5):
        y = y0 + i * (y1 - y0) / 4
        d.line((x0, y, x1, y), fill=(255, 255, 255, 25), width=1)
    random.seed(seed)
    value = 0.48
    points = []
    for i in range(70):
        drift = (0.5 - value) * (0.12 if mean_revert else 0.02)
        value = min(0.94, max(0.07, value + drift + random.uniform(-0.09, 0.09)))
        points.append((x0 + i * (x1 - x0) / 69, y1 - value * (y1 - y0)))
    d.line(points, fill=color, width=4, joint="curve")
    for x, y in points[::10]:
        d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)


def screenshot_card(img, path, box):
    shot = Image.open(path).convert("RGB")
    x0, y0, x1, y1 = box
    shot.thumbnail((x1 - x0, y1 - y0))
    card = Image.new("RGBA", (shot.width + 20, shot.height + 20), (244, 248, 252, 255))
    card.paste(shot, (10, 10))
    card = card.filter(ImageFilter.GaussianBlur(0.2))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x0 - 10, y0 + 10, x0 + card.width + 10, y0 + card.height + 30),
                         radius=18, fill=(0, 0, 0, 100))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(shadow)
    img.alpha_composite(card, (x0, y0))


def save(img, index):
    chrome(img, index, [CYAN, RED, MINT, CYAN, YELLOW, CYAN, MINT, CYAN][index - 1])
    img.convert("RGB").save(OUT / f"frame_{index:02d}.jpg", quality=94)


# 1 — the conventional approach
img = background(); d = ImageDraw.Draw(img, "RGBA")
heading(d, "THE OLD QUESTION", "Which stock will win?", "Most investors begin by trying to pick tomorrow's best stock.", RED)
for i, (ticker, pct, color) in enumerate([("A", "+18%", MINT), ("B", "-12%", RED), ("C", "+3%", YELLOW)]):
    x = 790 + i * 140
    d.rounded_rectangle((x, 245, x + 112, 410), radius=18, fill=(255, 255, 255, 14), outline=(*color, 150), width=2)
    d.text((x + 41, 278), ticker, font=F_STAT, fill=WHITE)
    d.text((x + 23, 354), pct, font=font(27, True), fill=color)
d.text((814, 444), "KNOWN ONLY AFTERWARD", font=F_SMALL, fill=BODY)
save(img, 1)

# 2 — hard to automate
img = background(); d = ImageDraw.Draw(img, "RGBA")
heading(d, "THE REALITY", "Prediction is very, very hard.", "No automated system can dependably identify tomorrow's winners in advance.", RED, 760)
for i in range(180):
    x = 800 + (i % 18) * 22
    y = 160 + (i // 18) * 28
    c = MINT if (i * 17) % 11 < 5 else RED
    d.rectangle((x, y, x + 13, y + 13), fill=(*c, 100))
d.text((825, 478), "SIGNAL", font=F_SMALL, fill=BODY)
d.text((1030, 478), "NOISE", font=F_SMALL, fill=BODY)
save(img, 2)

# 3 — measurable behavior
img = background(); d = ImageDraw.Draw(img, "RGBA")
heading(d, "A BETTER QUESTION", "What behavior repeats?", "SOXL Pro studies recurring, mean-reverting price action alongside broad market trends.", MINT, 700)
draw_line_chart(d, (790, 180, 1190, 510), MINT, 8, True)
d.line((790, 345, 1190, 345), fill=(*WHITE, 100), width=2)
d.text((927, 526), "MEAN REVERSION", font=F_SMALL, fill=MINT)
save(img, 3)

# 4 — probability engine
img = background(); d = ImageDraw.Draw(img, "RGBA")
heading(d, "MEASURE THE OUTCOME", "Move. Time. Probability.", "Estimate how often SOXL reached a chosen return within a chosen horizon.", CYAN, 680)
for i, (label, value, color) in enumerate([("MOVE", "+10%", CYAN), ("TIME", "30 DAYS", YELLOW), ("PROBABILITY", "64%", MINT)]):
    y = 172 + i * 128
    d.rounded_rectangle((805, y, 1194, y + 100), radius=20, fill=(255, 255, 255, 12), outline=(*color, 150), width=2)
    d.text((830, y + 18), label, font=F_SMALL, fill=BODY)
    tw = d.textlength(value, font=F_STAT)
    d.text((1168 - tw, y + 31), value, font=F_STAT, fill=color)
d.text((812, 570), "HISTORICAL SCENARIO ESTIMATE", font=F_SMALL, fill=BODY)
save(img, 4)

# 5 — app and timeframes
img = background(); d = ImageDraw.Draw(img, "RGBA")
heading(d, "CONTROL THE ANALYSIS", "Any move. Any timeframe.", "Use comparable history—not a hunch—to study what happened next.", YELLOW, 600)
screenshot_card(img, OUT.parent / "promo_assets" / "soxlpro-home.jpg", (650, 155, 1210, 570))
save(img, 5)

# 6 — options chain
img = background(); d = ImageDraw.Draw(img, "RGBA")
heading(d, "OPTIONS CLARITY", "Know the call trade-off.", "Compare strikes, expirations, premium at risk, and scenario-based outcomes.", CYAN, 590)
screenshot_card(img, OUT.parent / "promo_assets" / "soxlpro-call-risk.jpg", (632, 158, 1210, 574))
save(img, 6)

# 7 — strategy and backtest
img = background(); d = ImageDraw.Draw(img, "RGBA")
heading(d, "BUILD. TEST. COMPARE.", "Strategies before capital.", "Choose an existing strategy or design and backtest your own rules.", MINT, 690)
for i, (label, value, color) in enumerate([("RULES", "YOUR DESIGN", CYAN), ("HISTORY", "BACKTESTED", MINT), ("TRADE-OFF", "COMPARED", YELLOW)]):
    y = 185 + i * 118
    d.rounded_rectangle((805, y, 1192, y + 86), radius=18, fill=(255, 255, 255, 13))
    d.text((831, y + 18), label, font=F_SMALL, fill=BODY)
    d.text((831, y + 43), value, font=font(27, True), fill=color)
save(img, 7)

# 8 — close
img = background(); d = ImageDraw.Draw(img, "RGBA")
d.text((52, 132), "STOP GUESSING.", font=font(74, True), fill=WHITE)
d.text((52, 222), "START QUANTIFYING.", font=font(74, True), fill=CYAN)
for i, (word, color) in enumerate([("PROBABILITY", CYAN), ("TIMING", MINT), ("RISK", RED), ("REWARD", YELLOW)]):
    x = 54 + i * 292
    d.rounded_rectangle((x, 355, x + 250, 425), radius=22, outline=(*color, 190), width=2)
    tw = d.textlength(word, font=F_KICKER)
    d.text((x + (250 - tw) / 2, 378), word, font=F_KICKER, fill=color)
d.rounded_rectangle((52, 500, 1228, 610), radius=25, fill=(0, 9, 19, 190), outline=CYAN, width=2)
url = "SOXLPRO.XYZ"
tw = d.textlength(url, font=font(52, True))
d.text(((W - tw) / 2, 516), url, font=font(52, True), fill=WHITE)
save(img, 8)
