"""Tests for complications resolution, formatting, and display (§2.6, §4, §5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from fpms.modules.menud_client import complications, render
from fpms.modules.themes import BlackAndWhiteTheme, DarkTheme

VECTORS_PATH = Path(__file__).parent / "fixtures" / "resolve-vectors.json"


def test_resolve_vectors():
    """Verify resolution algorithm matches resolve-vectors.json cases."""
    assert VECTORS_PATH.exists(), f"Missing fixtures: {VECTORS_PATH}"
    data = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    for case in data["cases"]:
        result = complications.resolve(case["show"], case["live"])
        if "capacity" in case:
            result = result[: case["capacity"]]
        assert result == case["expect"], f"Failed case: {case.get('name')}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ok", "ok"),
        ("info", "info"),
        ("warn", "warn"),
        ("error", "error"),
        ("off", "off"),
        ("unknown", "unknown"),
        ("warning", "warn"),  # legacy alias
        ("CRITICAL", "unknown"),
        ("degraded", "unknown"),
        (None, "unknown"),
        ("", "unknown"),
    ],
)
def test_normalize_status(raw: Any, expected: str):
    assert complications.normalize_status(raw) == expected


def test_slot_text_formatting():
    # Unknown status always returns "--"
    assert complications.slot_text({"status": "unknown", "value": "100%"}) == "--"

    # Short takes precedence
    assert complications.slot_text({"short": "85%", "value": "85% charging"}) == "85%"

    # Value truncated to 4 chars
    assert complications.slot_text({"value": "123456"}) == "1234"

    # Label fallback truncated to 4 chars
    assert complications.slot_text({"label": "BATTERY"}) == "BATT"

    # Non-ASCII or unprintable replaced with '?'
    assert complications.slot_text({"short": "42°C"}) == "42?C"
    assert complications.slot_text({"value": "wi\x00i"}) == "wi?i"


def test_show_for_and_fallbacks():
    config = {
        "surfaces": {
            "panel.strip": {"show": ["wlanpi.battery", "wlanpi.wifi"]},
            "default": {"show": ["wlanpi.mode", "wlanpi.ip"]},
        }
    }
    assert complications.show_for(config, complications.PROFILE_STRIP) == [
        "wlanpi.battery",
        "wlanpi.wifi",
    ]
    # Surface not explicitly defined falls back to default profile
    assert complications.show_for(config, "other") == ["wlanpi.mode", "wlanpi.ip"]

    # When config is empty or invalid, falls back to shipped defaults
    assert complications.show_for({}, complications.PROFILE_STRIP) == list(
        complications.SHIPPED_STRIP_SHOW
    )
    assert complications.show_for({}, complications.PROFILE_PANEL) == list(
        complications.SHIPPED_PANEL_SHOW
    )


def test_resolved_tiles():
    live = [
        {"app_id": "wlanpi.battery", "value": "80%", "status": "ok"},
        {"app_id": "wlanpi.wifi", "value": "-52", "status": "ok"},
        {"app_id": "wlanpi.cpu", "value": "12%", "status": "info"},
    ]
    config = {"surfaces": {"panel.strip": {"show": ["wlanpi.wifi", "wlanpi.battery"]}}}
    tiles = complications.resolved_tiles(live, config, complications.PROFILE_STRIP)
    assert [t["app_id"] for t in tiles] == ["wlanpi.wifi", "wlanpi.battery"]


def test_home_tiles_list_capacity_rule_and_idle_hidden_tags():
    """Verify that _list renders capacity delimiters centered and idle/hidden tags with parens."""
    items = [
        {"label": "1 Mode", "detail": None},
        {"label": "2 Clients", "detail": "idle"},
        {"label": "- - fits above - -"},
        {"label": "  CPU", "detail": "hidden"},
    ]
    view = {
        "v": 1,
        "type": "view",
        "id": "s:test",
        "screen": "menu",
        "title": "Rows",
        "blocks": [{"type": "list", "text": "", "items": items, "selected": 0}],
    }
    frame = render.render(view, mode="classic")
    # Verify lines
    assert frame.lines[0] == "> 1 Mode"
    assert frame.lines[1] == "  2 Clients (idle)"
    assert frame.lines[2] == "  - - fits above - -"
    assert frame.lines[3] == "    CPU (hidden)"


def test_complications_row_mono_contrast():
    """Verify that on mono display (BlackAndWhiteTheme), error is rendered with an inverted background box."""
    img_warn = Image.new("1", (128, 12), 0)
    draw_warn = ImageDraw.Draw(img_warn)
    img_err = Image.new("1", (128, 12), 0)
    draw_err = ImageDraw.Draw(img_err)

    render.THEME = BlackAndWhiteTheme
    try:
        body_warn = render._Body()
        render._complications_row(
            body_warn,
            [{"app_id": "t1", "short": "WARN", "status": "warn"}],
            clock="12:00",
        )
        _, op_warn = body_warn.ops[0]
        op_warn(draw_warn, img_warn, 0)

        body_err = render._Body()
        render._complications_row(
            body_err,
            [{"app_id": "t1", "short": "ERR", "status": "error"}],
            clock="12:00",
        )
        _, op_err = body_err.ops[0]
        op_err(draw_err, img_err, 0)

        # Inverted box in error produces significantly more white pixels (fill box)
        white_warn = sum(1 for p in img_warn.getdata() if p == 255 or p == 1)
        white_err = sum(1 for p in img_err.getdata() if p == 255 or p == 1)
        assert white_err > white_warn + 50, (
            "Error status must draw an inverted box for mono contrast"
        )
    finally:
        render.THEME = DarkTheme
