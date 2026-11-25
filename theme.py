"""Colors used across the app (coffee / golden theme, matching the icon and
loading screen). Change them here and every screen follows.

The names TEAL* are kept from the first version so the rest of the code did
not need renaming - they now mean the main coffee-brown colors."""
import os

from kivy.utils import get_color_from_hex

HERE = os.path.dirname(os.path.abspath(__file__))
APP_BG = os.path.join(HERE, "assets", "app_bg.png")   # cream -> latte gradient

TEAL = "#8A4B1A"          # main buttons: coffee brown
TEAL_DARK = "#4A210E"     # dark espresso
TEAL_SOFT = "#F3DDB0"     # cream / foam
ORANGE_SOFT = "#F7C99B"
ORANGE_DARK = "#7A3A0A"
VIOLET_SOFT = "#E4D3EA"
VIOLET_DARK = "#4B2A63"
ROSE_SOFT = "#F5D2CC"
ROSE_DARK = "#7F1D1D"
GREEN_SOFT = "#D9E6B8"
GREEN_DARK = "#2F5A12"
BLUE_SOFT = "#D8E3EC"
BLUE_DARK = "#24506E"

PAPER = "#F7E6BF"         # fallback when the gradient picture is missing
CARD = "#FFF9EA"
INK = "#3B1D0C"
MUTED = "#7A5A3A"
LINE = "#D9BE8A"
DANGER = "#B42318"
ALERT = "#E60000"         # bright red: more cups used than the contract
ALERT_SOFT = "#FFE1E1"

# (soft background, dark letter) pairs used for profile circles
TINTS = [
    (TEAL_SOFT, TEAL_DARK),
    (ORANGE_SOFT, ORANGE_DARK),
    (GREEN_SOFT, GREEN_DARK),
    (ROSE_SOFT, ROSE_DARK),
    (VIOLET_SOFT, VIOLET_DARK),
    (BLUE_SOFT, BLUE_DARK),
]


def rgba(hex_color):
    """'#0F766E' -> [r, g, b, a] floats, the form Kivy wants."""
    return get_color_from_hex(hex_color)
