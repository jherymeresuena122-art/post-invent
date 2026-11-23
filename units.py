"""Items, units and the before/after math. No Kivy in here, so it is easy to test."""

# How an item can be counted. Every item is "before the event" minus
# "after the event" = what was consumed, in the unit you choose.
UNIT_CHOICES = ["cups", "items", "bags", "grams", "milligrams", "litres"]

# (name, unit) pairs every NEW event day starts with.
DEFAULT_ITEMS = [
    ("Hot cups", "cups"),
    ("Cold cups", "cups"),
    ("Matcha", "bags"),
    ("Beans", "bags"),
    ("Instant coffee", "grams"),
    ("Milk", "litres"),
]


def parse_number(text):
    """'12.5' -> 12.5.  Empty or not a number -> None."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def consumed(before, after):
    """How much was used up. None if either number is missing."""
    if before is None or after is None:
        return None
    return round(before - after, 3)


def fmt(value):
    """150.0 -> '150', 2.5 -> '2.5', 0.333333 -> '0.333'."""
    if value is None:
        return "-"
    return f"{round(value, 3):g}"


def cup_totals(items):
    """Combine every item counted in 'cups' (hot + cold + any custom cups).

    items: list of dicts with "unit", "before", "after" (numbers or None).
    Returns (before_total, after_total, consumed_total). A value is None until
    there is something to add up; consumed needs before AND after for every
    cups row.
    """
    rows = [i for i in items if i["unit"] == "cups"]
    befores = [i["before"] for i in rows if i["before"] is not None]
    afters = [i["after"] for i in rows if i["after"] is not None]
    before_total = round(sum(befores), 3) if befores else None
    after_total = round(sum(afters), 3) if afters else None
    complete = bool(rows) and len(befores) == len(rows) and len(afters) == len(rows)
    consumed_total = round(before_total - after_total, 3) if complete else None
    return before_total, after_total, consumed_total
