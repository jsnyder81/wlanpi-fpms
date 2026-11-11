"""
constants.py - shared constant vars
"""

import os
import pathlib

from PIL import ImageFont

from fpms.modules.env_utils import EnvUtils
from fpms.modules.platform import PLATFORM_PRO

WLANPI_MODEL_FILE = "/etc/wlanpi-model"

env_util = EnvUtils()
PLATFORM = env_util.get_platform(WLANPI_MODEL_FILE)
DISPLAY_TYPE = env_util.get_display_type(PLATFORM)
GPIO_CHIP = env_util.get_gpiochip()

DISPLAY_ORIENTATION_NORMAL = "normal"
DISPLAY_ORIENTATION_FLIPPED = "flipped"

SCRIPT_PATH = str(pathlib.Path(__file__).parent.parent.absolute())

IMAGE_DIR = os.path.join(SCRIPT_PATH, "images", "128x128")
FONT_DIR = os.path.join(SCRIPT_PATH, "fonts")
DISPLAY_MODE = "RGB"

# Seconds without a button press before the screen is put to sleep.
PAGE_SLEEP_SEC = 600
PAGE_WIDTH = 128
PAGE_HEIGHT = 128

# wlanpi-menud's socket for local surfaces (kernel peer credentials, no auth).
MENUD_SOCKET = "/run/wlanpi-menud/local.sock"


def _font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


FONT9 = _font("DejaVuSansMono.ttf", 9)
FONT10 = _font("DejaVuSansMono.ttf", 10)
FONTB10 = _font("DejaVuSansMono-Bold.ttf", 10)
FONTB11 = _font("DejaVuSansMono-Bold.ttf", 11)

BUTTONS_WLANPI_PRO = {
    "up": 22,
    "down": 5,
    "left": 17,
    "right": 27,
    "center": 6,
}

BUTTONS_WAVESHARE = {
    "up": 6,
    "down": 19,
    "left": 5,
    "right": 26,
    "center": 13,
    "key1": 21,
    "key2": 20,
    "key3": 16,
}

BUTTONS_PINS = {}

if PLATFORM == PLATFORM_PRO:
    BUTTONS_PINS = BUTTONS_WLANPI_PRO
else:
    BUTTONS_PINS = BUTTONS_WAVESHARE
