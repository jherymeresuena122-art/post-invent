"""Draws an inventory day as a picture, then saves it as PNG or PDF.

Uses only Pillow, so it works the same on a computer and on the phone.
"""
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from units import cup_status, fmt

WIDTH = 1240          # about A4 width at 150 dpi
MARGIN = 80
MIN_HEIGHT = 1754     # about A4 height at 150 dpi

TEAL = (138, 75, 26)
TEAL_SOFT = (243, 221, 176)
INK = (59, 29, 12)
MUTED = (122, 90, 58)
LINE = (217, 190, 138)
ROW_ALT = (252, 244, 224)
DANGER = (180, 35, 24)
ALERT = (230, 0, 0)
ALERT_SOFT = (255, 225, 225)
WHITE = (255, 255, 255)


def load_font(path, size):
    """A font file if we have one, otherwise whatever Pillow can find."""
    for candidate in (path, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if candidate:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def _draw(draw, data, fonts):
    """Draw everything and return the y position where the content ends."""
    title, h2, body, bold, small = (
        fonts["title"], fonts["h2"], fonts["body"], fonts["bold"], fonts["small"],
    )

    # header band
    draw.rectangle([0, 0, WIDTH, 170], fill=TEAL)
    draw.text((MARGIN, 38), "THE POD", font=small, fill=(243, 221, 176))
    draw.text((MARGIN, 76), data["title"], font=title, fill=WHITE)

    y = 215
    label_w = 190
    value_x = MARGIN + label_w
    value_w = WIDTH - MARGIN - value_x
    for label, value in (
        ("Date", data["date_text"]),
        ("Location", data["location"]),
        ("Crew", data["crew_text"]),
        ("Status", data["status_text"]),
    ):
        draw.text((MARGIN, y + 3), label, font=small, fill=MUTED)
        for line in _wrap(draw, value, body, value_w):
            draw.text((value_x, y), line, font=body, fill=INK)
            y += 38
        y += 10

    # inventory table
    y += 20
    draw.text((MARGIN, y), "Inventory", font=h2, fill=TEAL)
    y += 56
    name_x = MARGIN + 18
    before_r, after_r, used_r = 700, 870, WIDTH - MARGIN - 18

    draw.rectangle([MARGIN, y, WIDTH - MARGIN, y + 54], fill=TEAL_SOFT)
    draw.text((name_x, y + 13), "Item", font=bold, fill=TEAL)
    for right, text in ((before_r, "Before"), (after_r, "After"), (used_r, "Consumed")):
        draw.text((right - draw.textlength(text, font=bold), y + 13), text, font=bold, fill=TEAL)
    y += 54

    for index, item in enumerate(data["items"]):
        if index % 2 == 1:
            draw.rectangle([MARGIN, y, WIDTH - MARGIN, y + 72], fill=ROW_ALT)
        used = item["used"]
        draw.text((name_x, y + 8), item["name"], font=bold, fill=INK)
        draw.text((name_x, y + 42), item["unit"], font=small, fill=MUTED)
        for right, value in ((before_r, item["before"]), (after_r, item["after"])):
            text = fmt(value)
            draw.text((right - draw.textlength(text, font=body), y + 20), text, font=body, fill=INK)
        if used is None:
            text, color = "-", MUTED
        elif used < 0:
            text, color = f"{fmt(used)} (check)", DANGER
        else:
            text, color = fmt(used), INK
        draw.text((used_r - draw.textlength(text, font=bold), y + 20), text, font=bold, fill=color)
        y += 72
    draw.line([MARGIN, y, WIDTH - MARGIN, y], fill=LINE, width=2)

    # cups total
    if data.get("cups"):
        before, after, used = data["cups"]
        target = data.get("cups_target")
        left, over = cup_status(target, used)
        box_h = 215 if target is not None else 160
        y += 34
        draw.rectangle([MARGIN, y, WIDTH - MARGIN, y + box_h], fill=ALERT_SOFT if over else TEAL_SOFT)
        draw.text((MARGIN + 24, y + 16), "Cups total (hot + cold)", font=bold, fill=ALERT if over else TEAL)
        columns = [("Before", before), ("After", after), ("Consumed", used)]
        if target is not None:
            columns.insert(0, ("Contracted", target))
        step = (WIDTH - 2 * MARGIN) // len(columns)
        for index, (label, value) in enumerate(columns):
            x = MARGIN + 24 + index * step
            draw.text((x, y + 60), label, font=small, fill=MUTED)
            draw.text((x, y + 88), fmt(value), font=title, fill=ALERT if (over and label == "Consumed") else INK)
        if target is not None and left is not None:
            if over:
                text, color = f"OVER the contract by {fmt(-left)} cups", ALERT
            else:
                text, color = f"Left to serve: {fmt(left)} cups", TEAL
            draw.text((MARGIN + 24, y + 160), text, font=bold, fill=color)
        y += box_h

    # history
    if data["history"]:
        y += 44
        draw.text((MARGIN, y), "History", font=h2, fill=TEAL)
        y += 54
        for entry in data["history"]:
            for line in _wrap(draw, entry, small, WIDTH - 2 * MARGIN):
                draw.text((MARGIN, y), line, font=small, fill=INK)
                y += 32
            y += 6

    y += 40
    draw.text((MARGIN, y), data["generated_text"], font=small, fill=MUTED)
    return y + 32


def build_report(data, regular_font=None, bold_font=None):
    """data -> a Pillow image of the report.

    data keys: title, date_text, location, crew_text, status_text,
               items [{name, unit, before, after, used}], cups (before, after,
               consumed) or None, cups_target (number or None), history [str],
               generated_text
    """
    fonts = {
        "title": load_font(bold_font, 46),
        "h2": load_font(bold_font, 34),
        "body": load_font(regular_font, 28),
        "bold": load_font(bold_font, 28),
        "small": load_font(regular_font, 23),
    }
    measuring = Image.new("RGB", (WIDTH, 10), WHITE)
    end = _draw(ImageDraw.Draw(measuring), data, fonts)
    image = Image.new("RGB", (WIDTH, max(MIN_HEIGHT, end + MARGIN)), WHITE)
    _draw(ImageDraw.Draw(image), data, fonts)
    return image


def save_report(image, folder, base_name, fmt_name):
    """Save as PNG or PDF into folder. Returns the full path written."""
    extension = "pdf" if fmt_name.lower() == "pdf" else "png"
    path = os.path.join(folder, f"{base_name}.{extension}")
    counter = 1
    while os.path.exists(path):  # never overwrite an earlier export
        path = os.path.join(folder, f"{base_name}_{counter}.{extension}")
        counter += 1
    if extension == "pdf":
        image.convert("RGB").save(path, "PDF", resolution=150.0)
    else:
        image.save(path, "PNG")
    return path


def timestamp_text():
    return "Exported " + datetime.now().strftime("%Y-%m-%d %H:%M")
