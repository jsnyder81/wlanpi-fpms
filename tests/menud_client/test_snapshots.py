"""Snapshot tests for deterministic ASCII-art renders of all block types at 128x128 and 64px."""

import json
from pathlib import Path

import jsonschema
import pytest
from PIL import ImageDraw

from fpms.modules.constants import PAGE_WIDTH
from fpms.modules.menud_client import render
from fpms.modules.screen.virtual import Virtual

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "goldens"
SCHEMA_PATH = Path(__file__).parent / "fixtures" / "frames.schema.json"

SAMPLE_COMPLICATIONS = [
    {"app_id": "wlanpi.battery", "label": "BAT", "value": "85%", "status": "ok"},
    {"app_id": "wlanpi.wifi", "label": "WIFI", "value": "ch36", "status": "ok"},
]

SAMPLE_VIEWS = {
    "text": {
        "v": 1,
        "type": "view",
        "id": "s:text",
        "screen": "result",
        "title": "System Info",
        "breadcrumb": ["System", "Info"],
        "blocks": [
            {"type": "text", "text": "WLAN Pi OS", "style": "heading"},
            {"type": "text", "text": "Operating normally on all interfaces."},
            {"type": "text", "text": "Uptime: 3 days, 4 hours", "style": "muted"},
        ],
        "hints": {"left": "Back"},
    },
    "kv": {
        "v": 1,
        "type": "view",
        "id": "s:kv",
        "screen": "result",
        "title": "Network",
        "breadcrumb": ["Network", "IPv4"],
        "blocks": [
            {
                "type": "kv",
                "text": "",
                "items": [
                    {"key": "IP", "value": "192.168.1.150"},
                    {"key": "Subnet", "value": "255.255.255.0"},
                    {"key": "Gateway", "value": "192.168.1.1"},
                    {"key": "DNS", "value": "1.1.1.1"},
                ],
            }
        ],
        "hints": {"left": "Back"},
    },
    "table": {
        "v": 1,
        "type": "view",
        "id": "s:table",
        "screen": "result",
        "title": "Wi-Fi Scan",
        "blocks": [
            {
                "type": "table",
                "text": "",
                "columns": [
                    {"key": "ssid", "label": "SSID", "priority": 0},
                    {"key": "ch", "label": "Ch", "align": "right", "priority": 1},
                    {"key": "rssi", "label": "RSSI", "align": "right", "priority": 2},
                ],
                "rows": [
                    ["Office-5G", 36, -45],
                    ["Guest-Net", 6, -68],
                    ["Lab-IoT", 149, -72],
                ],
            }
        ],
        "hints": {"left": "Back"},
    },
    "list": {
        "v": 1,
        "type": "view",
        "id": "s:list",
        "screen": "menu",
        "title": "Main Menu",
        "blocks": [
            {
                "type": "list",
                "text": "",
                "selected": 1,
                "items": [
                    {"label": "Network", "branch": True},
                    {"label": "Wi-Fi Tools", "branch": True},
                    {"label": "Bluetooth", "detail": "active"},
                    {"label": "System", "branch": True},
                ],
            }
        ],
        "hints": {"down": "Next", "up": "Prev", "center": "Select"},
    },
    "status": {
        "v": 1,
        "type": "view",
        "id": "s:status",
        "screen": "result",
        "title": "Health Check",
        "blocks": [
            {
                "type": "status",
                "level": "ok",
                "label": "Core",
                "text": "Service healthy",
            },
            {
                "type": "status",
                "level": "warn",
                "label": "Memory",
                "text": "Usage at 82%",
            },
            {
                "type": "status",
                "level": "error",
                "label": "Cloud",
                "text": "Unreachable",
            },
        ],
        "hints": {"left": "Back"},
    },
    "progress": {
        "v": 1,
        "type": "view",
        "id": "s:progress",
        "screen": "busy",
        "title": "Scanning",
        "blocks": [
            {
                "type": "progress",
                "label": "Channel Survey",
                "pct": 65,
                "text": "65%",
            }
        ],
        "hints": {"left": "Cancel"},
    },
    "confirm": {
        "v": 1,
        "type": "view",
        "id": "s:confirm",
        "screen": "prompt",
        "title": "Reboot",
        "blocks": [
            {
                "type": "confirm",
                "prompt_id": "p_reboot",
                "message": "Restart WLAN Pi system?",
                "text": "Restart WLAN Pi system? [Cancel] [Reboot]",
                "confirm_label": "Reboot",
                "cancel_label": "Cancel",
                "selected": "confirm",
            }
        ],
        "hints": {"left": "Cancel", "center": "OK"},
    },
    "qr": {
        "v": 1,
        "type": "view",
        "id": "s:qr",
        "screen": "result",
        "title": "Hotspot",
        "blocks": [
            {
                "type": "qr",
                "data": "WIFI:S:WLANPi-AP;T:WPA;P:wlanpi123;;",
                "caption": "SSID: WLANPi-AP",
                "text": "SSID: WLANPi-AP",
            }
        ],
        "hints": {"left": "Back"},
    },
    "home": {
        "v": 1,
        "type": "view",
        "id": "s:home",
        "screen": "home",
        "title": "WLAN Pi",
        "blocks": [
            {
                "type": "kv",
                "text": "",
                "items": [
                    {"key": "Host", "value": "wlanpi-r4"},
                    {"key": "IP", "value": "192.168.1.150"},
                ],
            }
        ],
        "hints": {"down": "Menu"},
    },
    "unavailable": render.unavailable_view(
        [("eth0", "192.168.1.150")],
        "wlanpi-r4",
        failures=1,
        reason="connection refused",
    ),
    "overlong": {
        "v": 1,
        "type": "view",
        "id": "s:overlong",
        "screen": "menu",
        "title": "A Very Long Screen Title That Exceeds Header",
        "breadcrumb": ["Level1", "Level2", "Level3", "Level4", "Level5"],
        "blocks": [
            {
                "type": "text",
                "text": "This is an extremely long paragraph of text that definitely wraps across multiple rows without clipping at the right display boundary.",
            },
            {
                "type": "list",
                "text": "",
                "selected": 0,
                "items": [
                    {
                        "label": "Supercalifragilisticexpialidocious menu item label",
                        "branch": True,
                    },
                    {
                        "label": "Another extraordinarily long unselected menu label",
                        "detail": "verylongdetailstring",
                    },
                    {
                        "label": "Unselected plain label that is way too long to fit on one line",
                    },
                ],
            },
        ],
        "hints": {"down": "Next", "up": "Prev", "center": "Select", "left": "Back"},
    },
}


def test_all_sample_views_valid_schema():
    """Verify that every sample view fixture conforms to the protocol frames schema."""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    for view in SAMPLE_VIEWS.values():
        jsonschema.validate(instance=view, schema=schema)
    topic_schema = schema.get("$defs", {}).get("topic_complications")
    if topic_schema:
        jsonschema.validate(instance=SAMPLE_COMPLICATIONS, schema=topic_schema)


@pytest.mark.parametrize("name", list(SAMPLE_VIEWS.keys()))
@pytest.mark.parametrize("height", [128, 64])
def test_block_snapshot_matches_golden(name: str, height: int):
    view = SAMPLE_VIEWS[name]
    comps = SAMPLE_COMPLICATIONS if name == "home" else None
    frame = render.render(
        view, clock="12:34", height=height, mode="classic", complications=comps
    )
    ascii_art = render.image_to_ascii(frame.image)
    golden_file = GOLDEN_DIR / f"{name}_128x{height}.txt"
    assert golden_file.exists(), f"Golden file missing: {golden_file}"
    expected = golden_file.read_text(encoding="utf-8")
    assert ascii_art == expected


def test_no_right_edge_clipping():
    """Verify that ImageDraw.text never renders past the right edge (x > PAGE_WIDTH)."""
    clipped = []
    orig_text = ImageDraw.ImageDraw.text

    def hooked_text(self, xy, text, *args, **kwargs):
        font = kwargs.get("font")
        if font and text:
            width = font.getlength(str(text))
            x = xy[0]
            if x + width > PAGE_WIDTH:
                clipped.append((xy, str(text), x + width))
        return orig_text(self, xy, text, *args, **kwargs)

    ImageDraw.ImageDraw.text = hooked_text
    try:
        for name, view in SAMPLE_VIEWS.items():
            for h in (128, 64):
                comps = SAMPLE_COMPLICATIONS if name == "home" else None
                render.render(
                    view, clock="12:34", height=h, mode="classic", complications=comps
                )
    finally:
        ImageDraw.ImageDraw.text = orig_text

    assert not clipped, f"Text clipped past right edge: {clipped}"


def test_virtual_screen_to_ascii_method():
    screen = Virtual()
    frame = render.render(
        SAMPLE_VIEWS["confirm"], clock="12:34", height=128, mode="classic"
    )
    screen.drawImage(frame.image)
    ascii_art = screen.to_ascii()
    assert ascii_art.startswith("+---")
    assert ascii_art.endswith("---+")
    golden = (GOLDEN_DIR / "confirm_128x128.txt").read_text(encoding="utf-8")
    assert ascii_art == golden
