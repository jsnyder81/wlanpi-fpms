"""Unit tests for the glyph/icon module."""

import pytest
from PIL import Image, ImageDraw

from fpms.modules.menud_client import glyphs

REQUIRED_NAMES = [
    "wifi",
    "bluetooth",
    "battery",
    "plug",
    "alert",
    "check",
    "x",
    "arrow",
    "dot_filled",
    "dot_hollow",
]


@pytest.mark.parametrize("name", REQUIRED_NAMES)
def test_glyphs_8x8_dimensions_and_values(name: str):
    matrix = glyphs.get_glyph(name, size=8)
    assert len(matrix) == 8
    for row in matrix:
        assert len(row) == 8
        assert all(val in (0, 1) for val in row)
    # Ensure glyph is not completely empty
    assert any(any(val == 1 for val in row) for row in matrix)


@pytest.mark.parametrize("name", REQUIRED_NAMES)
def test_glyphs_12x12_dimensions_and_values(name: str):
    matrix = glyphs.get_glyph(name, size=12)
    assert len(matrix) == 12
    for row in matrix:
        assert len(row) == 12
        assert all(val in (0, 1) for val in row)
    # Ensure glyph is not completely empty
    assert any(any(val == 1 for val in row) for row in matrix)


def test_unknown_glyph_raises_key_error():
    with pytest.raises(KeyError):
        glyphs.get_glyph("nonexistent_glyph", size=8)


def test_draw_glyph_on_imagedraw():
    img = Image.new("RGB", (16, 16), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    glyphs.draw_glyph(draw, 4, 4, "arrow", fill=(255, 255, 255), size=8)

    matrix = glyphs.get_glyph("arrow", size=8)
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            expected = (255, 255, 255) if val else (0, 0, 0)
            assert img.getpixel((4 + c, 4 + r)) == expected


def test_glyph_to_ascii():
    ascii_art = glyphs.glyph_to_ascii("x", size=8)
    lines = ascii_art.splitlines()
    assert len(lines) == 8
    assert all(len(line) == 8 for line in lines)
    assert lines[0] == "##....##"
    assert lines[3] == "...##..."


def test_glyph_image_returns_valid_image():
    img = glyphs.glyph_image("check", fill=(255, 255, 255), bg=(0, 0, 0), size=12)
    assert img.size == (12, 12)
    assert img.mode == "RGB"
