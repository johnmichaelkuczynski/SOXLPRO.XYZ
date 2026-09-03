from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
OUT = Path(__file__).parent
ROOT = OUT.parent

NAVY = (4, 16, 29)
NAVY_2 = (9, 41, 61)
WHITE = (247, 250, 252)
BODY = (185, 207, 221)
CYAN = (49, 202, 255)
MINT = (52, 224, 175)
AMBER = (255, 194, 69)
RED = (255, 103, 115)


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


BRAND = font(38, True)
EYEBROW = font(30, True)
TITLE = font(88, True)
BODY_FONT = font(43)
CARD_LABEL = font(27, True)
CARD_VALUE = font(55, True)
FOOT = font(29, True)


def base():
    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        t = y / (H - 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(NAVY, NAVY_2))
        draw.line((0, y, W, y), fill=color)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((500, -250, 1350, 650), fill=(*CYAN, 22))
    gd.ellipse((-500, 1250, 450, 2200), fill=(*MINT, 14))
    return Image.alpha_composite(
        image.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(130))
    )


def wrap(draw, text, text_font, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=text_font) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def chrome(image, number, accent):
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (64, 58, 350, 126), radius=34, outline=accent, width=3
    )
    draw.text((103, 72), "SOXL PRO", font=BRAND, fill=WHITE)
    draw.line((64, 1780, 1016, 1780), fill=(255, 255, 255, 35), width=2)
    draw.text((64, 1815), "SOXLPRO.XYZ", font=FOOT, fill=WHITE)
    draw.text((895, 1815), f"{number}/6", font=FOOT, fill=BODY)


def heading(draw, eyebrow, title, body, accent, top=235):
    draw.rectangle((64, top, 74, top + 56), fill=accent)
    draw.text((98, top + 4), eyebrow.upper(), font=EYEBROW, fill=accent)
    y = top + 95
    for line in wrap(draw, title, TITLE, 950):
        draw.text((64, y), line, font=TITLE, fill=WHITE)
        y += 102
    y += 30
    for line in wrap(draw, body, BODY_FONT, 930):
        draw.text((66, y), line, font=BODY_FONT, fill=BODY)
        y += 61
    return y


def screenshot(image, source, box):
    shot = Image.open(source).convert("RGB")
    x0, y0, x1, y1 = box
    target_w, target_h = x1 - x0, y1 - y0
    scale = max(target_w / shot.width, target_h / shot.height)
    shot = shot.resize((int(shot.width * scale), int(shot.height * scale)))
    left = max(0, (shot.width - target_w) // 2)
    top = max(0, (shot.height - target_h) // 2)
    shot = shot.crop((left, top, left + target_w, top + target_h))
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (x0 - 14, y0 + 16, x1 + 14, y1 + 42),
        radius=34,
        fill=(0, 0, 0, 115),
    )
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(24)))
    mask = Image.new("L", (target_w, target_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, target_w, target_h), radius=28, fill=255
    )
    image.paste(shot, (x0, y0), mask)
    ImageDraw.Draw(image).rounded_rectangle(box, radius=28, outline=CYAN, width=3)


def metric(draw, box, label, value, color):
    draw.rounded_rectangle(
        box, radius=28, fill=(255, 255, 255, 13), outline=(*color, 170), width=3
    )
    x0, y0, x1, _ = box
    draw.text((x0 + 30, y0 + 25), label, font=CARD_LABEL, fill=BODY)
    value_width = draw.textlength(value, font=CARD_VALUE)
    draw.text((x1 - value_width - 30, y0 + 72), value, font=CARD_VALUE, fill=color)


def save(image, number, accent):
    chrome(image, number, accent)
    image.convert("RGB").save(OUT / f"frame_{number:02d}.jpg", quality=95)


# 1 — Immediate hook
img = base()
d = ImageDraw.Draw(img, "RGBA")
heading(
    d,
    "SOXL MOVES FAST",
    "Know the odds before the trade.",
    "Turn historical SOXL behavior into a clear probability, timeframe, and risk picture.",
    CYAN,
)
metric(d, (64, 970, 1016, 1160), "TARGET MOVE", "+10%", CYAN)
metric(d, (64, 1195, 1016, 1385), "TIME HORIZON", "30 DAYS", AMBER)
metric(d, (64, 1420, 1016, 1610), "HISTORICAL RESULT", "64%", MINT)
save(img, 1, CYAN)

# 2 — Historical position
img = base()
d = ImageDraw.Draw(img, "RGBA")
heading(
    d,
    "START WITH CONTEXT",
    "See where SOXL stands now.",
    "The dashboard weighs its position across short and long historical ranges.",
    MINT,
)
screenshot(img, ROOT / "promo_assets" / "soxlpro-home.jpg", (64, 870, 1016, 1640))
save(img, 2, MINT)

# 3 — Probability controls
img = base()
d = ImageDraw.Draw(img, "RGBA")
heading(
    d,
    "SET THE QUESTION",
    "Your move. Your timeframe.",
    "Choose the return you care about and how long the market has to reach it.",
    AMBER,
)
for i, (label, value, color) in enumerate(
    [("MOVE", "+15%", CYAN), ("WINDOW", "60 DAYS", AMBER), ("OUTCOME", "MEASURED", MINT)]
):
    metric(d, (64, 930 + i * 220, 1016, 1115 + i * 220), label, value, color)
save(img, 3, AMBER)

# 4 — Real application
img = base()
d = ImageDraw.Draw(img, "RGBA")
heading(
    d,
    "COMPARE THE MARKET",
    "SOXL against what matters.",
    "Use built-in benchmarks—or enter another EODHD-supported security.",
    CYAN,
)
screenshot(img, ROOT / "promo_assets" / "soxlpro-home.jpg", (64, 900, 1016, 1640))
save(img, 4, CYAN)

# 5 — Options risk
img = base()
d = ImageDraw.Draw(img, "RGBA")
heading(
    d,
    "OPTIONS NEED CONTEXT",
    "Measure risk before reward.",
    "Compare strikes, expirations, premium at risk, and scenario outcomes.",
    RED,
)
screenshot(img, ROOT / "promo_assets" / "soxlpro-call-risk.jpg", (64, 900, 1016, 1640))
save(img, 5, RED)

# 6 — Close
img = base()
d = ImageDraw.Draw(img, "RGBA")
d.text((64, 300), "DON'T JUST", font=font(95, True), fill=WHITE)
d.text((64, 420), "CHASE THE MOVE.", font=font(95, True), fill=RED)
d.text((64, 650), "MEASURE IT.", font=font(112, True), fill=CYAN)
for i, (word, color) in enumerate(
    [("PROBABILITY", CYAN), ("TIMING", MINT), ("RISK", RED)]
):
    y = 930 + i * 155
    d.rounded_rectangle(
        (64, y, 1016, y + 112), radius=32, outline=(*color, 190), width=3
    )
    width = d.textlength(word, font=font(39, True))
    d.text(((W - width) / 2, y + 30), word, font=font(39, True), fill=color)
d.rounded_rectangle(
    (64, 1460, 1016, 1650), radius=38, fill=(0, 8, 17, 210), outline=CYAN, width=4
)
url = "SOXLPRO.XYZ"
url_width = d.textlength(url, font=font(66, True))
d.text(((W - url_width) / 2, 1515), url, font=font(66, True), fill=WHITE)
save(img, 6, CYAN)