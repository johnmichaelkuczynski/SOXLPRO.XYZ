from pathlib import Path
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
OUT = Path(__file__).parent

BLACK = (6, 9, 12)
PANEL = (13, 19, 24)
WHITE = (245, 248, 244)
MUTED = (155, 169, 162)
GREEN = (117, 255, 99)
CYAN = (59, 218, 255)
ORANGE = (255, 156, 53)
RED = (255, 77, 88)


def font(size, bold=False):
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in (
        f"/usr/share/fonts/truetype/dejavu/{filename}",
        f"/usr/share/fonts/{filename}",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


F_LOGO = font(19, True)
F_KICKER = font(17, True)
F_TITLE = font(57, True)
F_BODY = font(25)
F_STAT = font(42, True)
F_SMALL = font(16)


def background(accent=GREEN):
    img = Image.new("RGBA", (W, H), (*BLACK, 255))
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 64):
        d.line((x, 0, x, H), fill=(255, 255, 255, 7), width=1)
    for y in range(0, H, 64):
        d.line((0, y, W, y), fill=(255, 255, 255, 7), width=1)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((760, -370, 1510, 370), fill=(*accent, 25))
    gd.ellipse((-380, 510, 340, 1180), fill=(*CYAN, 13))
    return Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(100)))


def wrap(draw, text, text_font, max_width):
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=text_font) <= max_width:
            line = test
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def chrome(img, scene, accent):
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((44, 28, 203, 65), radius=18, outline=accent, width=2)
    d.text((64, 37), "SOXLPRO.XYZ", font=F_LOGO, fill=WHITE)
    d.line((44, 661, 1236, 661), fill=(255, 255, 255, 22), width=1)
    d.text((44, 679), "TRADE-VESTING", font=F_SMALL, fill=accent)
    d.text((1150, 679), f"{scene:02d}/07", font=F_SMALL, fill=MUTED)


def headline(d, kicker, title, body, accent, width=700):
    d.rectangle((44, 119, 51, 157), fill=accent)
    d.text((68, 120), kicker.upper(), font=F_KICKER, fill=accent)
    y = 173
    for line in wrap(d, title, F_TITLE, width):
        d.text((44, y), line, font=F_TITLE, fill=WHITE)
        y += 66
    if body:
        y += 18
        for line in wrap(d, body, F_BODY, width):
            d.text((46, y), line, font=F_BODY, fill=MUTED)
            y += 36
    return y


def mini_chart(d, box, color, seed, volatility=1.0, trend=0.0):
    x0, y0, x1, y1 = box
    for i in range(5):
        y = y0 + i * (y1 - y0) / 4
        d.line((x0, y, x1, y), fill=(255, 255, 255, 18), width=1)
    random.seed(seed)
    value = 0.48
    points = []
    for i in range(92):
        value += (0.5 - value) * 0.055 + random.uniform(-0.065, 0.065) * volatility + trend
        value = min(0.93, max(0.08, value))
        points.append((x0 + i * (x1 - x0) / 91, y1 - value * (y1 - y0)))
    d.line(points, fill=color, width=4, joint="curve")
    return points


def card(d, box, label, value, color):
    d.rounded_rectangle(box, radius=16, fill=(*PANEL, 235), outline=(*color, 150), width=2)
    x0, y0, x1, _ = box
    d.text((x0 + 21, y0 + 17), label, font=F_SMALL, fill=MUTED)
    w = d.textlength(value, font=F_STAT)
    d.text((x1 - w - 21, y0 + 41), value, font=F_STAT, fill=color)


def save(img, scene, accent):
    chrome(img, scene, accent)
    img.convert("RGB").save(OUT / f"frame_{scene:02d}.jpg", quality=95)


# 1 — provocative opening
img = background(RED)
d = ImageDraw.Draw(img, "RGBA")
headline(
    d,
    "THE TRADING PROBLEM",
    "Information is the edge.",
    "And the information advantage is rarely yours.",
    RED,
    680,
)
d.rounded_rectangle((808, 142, 1196, 518), radius=24, fill=(*PANEL, 230), outline=(*RED, 130), width=2)
d.text((853, 184), "INSIDE", font=font(44, True), fill=RED)
d.text((853, 242), "INFORMATION", font=font(35, True), fill=WHITE)
for i in range(5):
    width = [249, 214, 276, 183, 235][i]
    d.rounded_rectangle((853, 326 + i * 34, 853 + width, 343 + i * 34), radius=8, fill=(255, 255, 255, 22))
d.line((812, 542, 1192, 542), fill=(*RED, 110), width=3)
d.text((895, 563), "ACCESS DENIED", font=F_KICKER, fill=RED)
save(img, 1, RED)

# 2 — investing problem
img = background(ORANGE)
d = ImageDraw.Draw(img, "RGBA")
headline(
    d,
    "THE INVESTING PROBLEM",
    "Capital makes capital.",
    "Small positions can make even correct ideas feel insignificant.",
    ORANGE,
    690,
)
for i, (label, amount, height) in enumerate(
    [("START", "$1K", 85), ("MORE", "$10K", 175), ("SCALE", "$100K", 315)]
):
    x = 805 + i * 135
    d.rounded_rectangle((x, 560 - height, x + 102, 560), radius=13, fill=(*ORANGE, 35 + i * 28), outline=(*ORANGE, 145), width=2)
    d.text((x + 18, 579), label, font=F_SMALL, fill=MUTED)
    d.text((x + 14, 528 - height), amount, font=font(23, True), fill=WHITE)
save(img, 2, ORANGE)

# 3 — introduce trade-vesting
img = background(GREEN)
d = ImageDraw.Draw(img, "RGBA")
headline(
    d,
    "THE THIRD PATH",
    "Trade-Vesting.",
    "A disciplined way to combine a durable thesis with tactical entries.",
    GREEN,
    680,
)
for i, (word, color) in enumerate([("TRADE", CYAN), ("+", WHITE), ("INVEST", GREEN)]):
    x = [790, 949, 1007][i]
    d.text((x, 255), word, font=font(35 if word != "+" else 44, True), fill=color)
d.line((797, 337, 1188, 337), fill=(*WHITE, 45), width=2)
d.text((824, 376), "TACTICAL ENTRY", font=F_KICKER, fill=CYAN)
d.text((824, 425), "DURABLE INDUSTRY", font=F_KICKER, fill=GREEN)
d.text((824, 474), "DEFINED RISK", font=F_KICKER, fill=ORANGE)
save(img, 3, GREEN)

# 4 — instrument requirements
img = background(CYAN)
d = ImageDraw.Draw(img, "RGBA")
headline(
    d,
    "THE INSTRUMENT",
    "Volatile. Mean-reverting. Rooted.",
    "Use movement for opportunity—and industry strength for the foundation.",
    CYAN,
    740,
)
mini_chart(d, (792, 174, 1196, 490), CYAN, 14, 1.2)
d.line((792, 332, 1196, 332), fill=(*WHITE, 80), width=2)
for i, (label, color) in enumerate([("HIGH VOLATILITY", CYAN), ("MEAN REVERSION", GREEN), ("GROWING INDUSTRY", ORANGE)]):
    x = 790 + (i % 2) * 207
    y = 527 + (i // 2) * 47
    d.rounded_rectangle((x, y, x + 190, y + 34), radius=17, outline=(*color, 145), width=2)
    tw = d.textlength(label, font=font(13, True))
    d.text((x + (190 - tw) / 2, y + 9), label, font=font(13, True), fill=color)
save(img, 4, CYAN)

# 5 — options amplification
img = background(GREEN)
d = ImageDraw.Draw(img, "RGBA")
headline(
    d,
    "THE AMPLIFIER",
    "Calls magnify the move.",
    "Directional accuracy still decides whether leverage helps—or hurts.",
    GREEN,
    690,
)
card(d, (800, 165, 1198, 275), "UNDERLYING MOVE", "+8%", CYAN)
card(d, (800, 301, 1198, 411), "CALL SCENARIO", "+31%", GREEN)
card(d, (800, 437, 1198, 547), "PREMIUM AT RISK", "DEFINED", ORANGE)
d.text((868, 577), "ILLUSTRATIVE SCENARIO", font=F_SMALL, fill=MUTED)
save(img, 5, GREEN)

# 6 — signal problem solved
img = background(ORANGE)
d = ImageDraw.Draw(img, "RGBA")
headline(
    d,
    "THE ENTRY",
    "Direction comes first.",
    "Buy only when the signal supports the direction.",
    ORANGE,
    690,
)
mini_chart(d, (790, 170, 1196, 455), GREEN, 31, 1.05)
d.line((790, 398, 1196, 398), fill=(*ORANGE, 150), width=2)
d.rounded_rectangle((846, 493, 1143, 570), radius=18, fill=(*GREEN, 20), outline=GREEN, width=3)
label = "UNAMBIGUOUS BUY SIGNAL"
tw = d.textlength(label, font=font(18, True))
d.text(((1986 - tw) / 2, 521), label, font=font(18, True), fill=BLACK)
save(img, 6, ORANGE)

# 7 — close
img = background(GREEN)
d = ImageDraw.Draw(img, "RGBA")
d.text((44, 116), "ONE SECURITY.", font=font(66, True), fill=WHITE)
d.text((44, 196), "ONE SOLVED SYSTEM.", font=font(66, True), fill=GREEN)
d.text((46, 308), "Let us show you how.", font=font(32), fill=MUTED)
d.rounded_rectangle((44, 408, 1236, 576), radius=28, fill=(0, 0, 0, 175), outline=GREEN, width=3)
url = "SOXLPRO.XYZ"
tw = d.textlength(url, font=font(83, True))
d.text(((W - tw) / 2, 442), url, font=font(83, True), fill=WHITE)
d.text((486, 548), "ESS  OH  EX  ELL", font=F_SMALL, fill=GREEN)
save(img, 7, GREEN)