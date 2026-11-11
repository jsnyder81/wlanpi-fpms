"""QR codes for ``qr`` view blocks, from the pure-Python ``qrcode`` library."""

from __future__ import annotations

import qrcode
from PIL import Image
from qrcode.exceptions import DataOverflowError

BORDER = 2  # modules of quiet zone; small, but the panel is 128 pixels wide


def matrix(data: str) -> list[list[bool]] | None:
    """Module matrix including the quiet zone, or None when the data cannot be encoded."""
    code = qrcode.QRCode(
        border=BORDER, error_correction=qrcode.constants.ERROR_CORRECT_M
    )
    try:
        code.add_data(data)
        code.make(fit=True)
    except (DataOverflowError, ValueError):
        return None
    return code.get_matrix()


def image(data: str, max_px: int) -> Image.Image | None:
    """The largest whole-pixel-per-module QR image that fits ``max_px``, or None.

    None when even one pixel per module does not fit: a blurred code does not
    scan, so the caller shows the block's text instead.
    """
    modules = matrix(data)
    if not modules:
        return None
    size = len(modules)
    scale = max_px // size
    if scale < 1:
        return None
    img = Image.new("RGB", (size, size), "white")
    for y, row in enumerate(modules):
        for x, dark in enumerate(row):
            if dark:
                img.putpixel((x, y), (0, 0, 0))
    return img.resize((size * scale, size * scale), Image.Resampling.NEAREST)
