"""Colors used across the app. Change them here and every screen follows."""
from kivy.utils import get_color_from_hex

TEAL = "#0F766E"
TEAL_DARK = "#0B4F49"
TEAL_SOFT = "#D7EDE9"
ORANGE_SOFT = "#FBE4CF"
ORANGE_DARK = "#7A3A0A"
VIOLET_SOFT = "#E3E1F6"
VIOLET_DARK = "#3B3585"
ROSE_SOFT = "#F8DADA"
ROSE_DARK = "#7F1D1D"
GREEN_SOFT = "#DDEBD0"
GREEN_DARK = "#2F5A12"
BLUE_SOFT = "#DCE8F5"
BLUE_DARK = "#1E4A7A"

PAPER = "#F6F3EE"
CARD = "#FFFFFF"
INK = "#1F2430"
MUTED = "#5B6270"
LINE = "#D5CFC4"
DANGER = "#B42318"

# (soft background, dark letter) pairs used for profile circles
TINTS = [
    (TEAL_SOFT, TEAL_DARK),
    (ORANGE_SOFT, ORANGE_DARK),
    (VIOLET_SOFT, VIOLET_DARK),
    (ROSE_SOFT, ROSE_DARK),
    (GREEN_SOFT, GREEN_DARK),
    (BLUE_SOFT, BLUE_DARK),
]


def rgba(hex_color):
    """'#0F766E' -> [r, g, b, a] floats, the form Kivy wants."""
    return get_color_from_hex(hex_color)
