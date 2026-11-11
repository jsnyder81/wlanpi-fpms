"""Physical button input: GPIO edges and the -e keyboard emulation.

Buttons carry no menu logic. Each press becomes one of the protocol's key
names (up, down, left, right, center, key1 to key3) and is handed to a
callback; wlanpi-menud owns the cursor.

FPMS conventions kept here: a button acts on press (falling edge), there is
no long-press, left is back, and a flipped display swaps the directions and
key1 with key3 so the buttons still match what is on screen.
"""

import sys
import termios
import tty
from datetime import timedelta

from fpms.modules.constants import DISPLAY_ORIENTATION_FLIPPED

FLIPPED_KEYS = {
    "up": "down",
    "down": "up",
    "left": "right",
    "right": "left",
    "key1": "key3",
    "key3": "key1",
}

# Keyboard emulation (-e): numeric keypad or letters.
EMULATED_KEYS = {
    "8": "up",
    "w": "up",
    "2": "down",
    "x": "down",
    "4": "left",
    "a": "left",
    "6": "right",
    "d": "right",
    "5": "center",
    "s": "center",
    "*": "key1",
    "i": "key1",
    "-": "key2",
    "o": "key2",
    "+": "key3",
    "p": "key3",
}
EMULATED_QUIT = "k"
EMULATED_SCREENSHOT = "g"


def oriented_key(key, orientation):
    """The key a press means with the display in ``orientation``."""
    if orientation == DISPLAY_ORIENTATION_FLIPPED:
        return FLIPPED_KEYS.get(key, key)
    return key


def request_buttons(gpio_chip, pins):
    """Claim the button lines. Raises OSError when another process holds them."""
    import gpiod
    from gpiod.line import Bias, Edge

    line_setting = gpiod.LineSettings(
        bias=Bias.PULL_UP,
        edge_detection=Edge.FALLING,
        debounce_period=timedelta(microseconds=10),
    )
    return gpiod.request_lines(gpio_chip, dict.fromkeys(pins.values(), line_setting))


def monitor_buttons(request, pins, get_orientation, on_key):
    """Block reading edge events; call ``on_key(name)`` for every press."""
    names = {offset: name for name, offset in pins.items()}
    with request:
        while True:
            request.wait_edge_events(1)
            for event in request.read_edge_events():
                name = names.get(event.line_offset)
                if name is not None:
                    on_key(oriented_key(name, get_orientation()))


def emulated_key(char, pins):
    """Protocol key for a typed character, or None. Keys the device lacks are ignored."""
    key = EMULATED_KEYS.get(char.lower())
    return key if key in pins else None


def emulation_hints(pins):
    hints = ["w/x/a/d/s: up/down/left/right/center", "g: screenshot   k: quit"]
    if all(k in pins for k in ("key1", "key2", "key3")):
        hints.append("i/o/p: key1/key2/key3")
    return hints


def getch(stream=None):
    """One character from the terminal, unbuffered. Empty string at end of input."""
    stream = stream or sys.stdin
    fd = stream.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except termios.error:
        return stream.read(1)  # not a terminal (a pipe in tests)
    try:
        tty.setraw(fd)
        return stream.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def emulate_buttons(pins, on_key, on_screenshot, on_quit, read=getch):
    """Read the keyboard until quit (k) or end of input, emulating the buttons."""
    while True:
        char = read()
        if not char:
            return  # end of input: nothing left to emulate, keep the panel up
        if char.lower() == EMULATED_QUIT:
            on_quit()
            return
        if char.lower() == EMULATED_SCREENSHOT:
            on_screenshot()
            continue
        key = emulated_key(char, pins)
        if key is not None:
            on_key(key)
