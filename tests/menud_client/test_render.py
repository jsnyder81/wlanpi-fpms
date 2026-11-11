"""Headless render assertions: each block type on the 128x128 panel.

Text is asserted through Frame.lines (the screen as text); colour and
geometry through pixels of Frame.image.
"""

from PIL import ImageColor

from fpms.modules.menud_client import qr, render
from fpms.modules.themes import THEME

SELECTED_BG = ImageColor.getrgb(THEME.page_selected_item_background.value)
BACKGROUND = ImageColor.getrgb(THEME.display_background.value)
TITLE_BG = ImageColor.getrgb(THEME.page_title_background.value)


def view(*blocks, **extra):
    return {
        "screen": "result",
        "title": "Test",
        "blocks": list(blocks),
        "hints": {},
        **extra,
    }


def body_colours(frame, y0=render.BODY_TOP, y1=render.BODY_TOP + render.BODY_H):
    px = frame.image.load()
    return {px[x, y] for y in range(y0, y1) for x in range(render.PAGE_WIDTH)}


def row_y(row):
    """Top pixel of body row ``row`` on an unscrolled screen."""
    return render.BODY_TOP + row * render.ROW_H


def test_screen_geometry_matches_what_hello_reports():
    assert (render.PAGE_WIDTH, render.PAGE_HEIGHT) == (128, 128)
    assert render.COLS == 21
    assert render.ROWS == 8
    frame = render.render(view())
    assert frame.image.size == (128, 128)
    assert frame.image.getpixel((1, 1)) == TITLE_BG


def test_text_block_wraps_and_styles():
    frame = render.render(
        view(
            {"type": "text", "text": "Heading", "style": "heading"},
            {"type": "text", "text": "one two three four five six seven eight"},
            {"type": "text", "text": "first\nsecond", "style": "muted"},
        )
    )
    assert frame.lines == [
        "Heading",
        "one two three four",
        "five six seven eight",
        "first",
        "second",
    ]
    assert all(len(line) <= render.COLS for line in frame.lines)
    assert ImageColor.getrgb(THEME.text_highlighted_color.value) in body_colours(
        frame, row_y(0), row_y(1)
    )
    assert ImageColor.getrgb(THEME.text_secondary_color.value) in body_colours(
        frame, row_y(3), row_y(5)
    )


def test_kv_block_one_row_per_short_pair_and_wraps_long_values():
    frame = render.render(
        view(
            {
                "type": "kv",
                "text": "",
                "items": [
                    {"key": "IP", "value": "192.0.2.10"},
                    {"key": "Up", "value": True},
                    {"key": "Model", "value": "WLAN Pi R4 with a long name"},
                    {"key": "Gone", "value": None},
                ],
            }
        )
    )
    assert frame.lines == [
        "IP: 192.0.2.10",
        "Up: yes",
        "Model: WLAN Pi R4 with a long name",
        "Gone: ",
    ]
    # IP and Up take a row each; Model takes a key row and two value rows.
    assert body_colours(frame, row_y(6), row_y(7)) == {BACKGROUND}
    assert body_colours(frame, row_y(5), row_y(6)) != {BACKGROUND}


def test_table_block_drops_low_priority_columns_and_aligns():
    block = {
        "type": "table",
        "text": "",
        "columns": [
            {"key": "ssid", "label": "SSID", "priority": 0},
            {"key": "bssid", "label": "BSSID", "priority": 3},
            {"key": "ch", "label": "Ch", "align": "right", "priority": 1},
            {"key": "rssi", "label": "RSSI", "align": "right", "priority": 2},
        ],
        "rows": [
            ["lab", "aa:bb:cc:dd:ee:01", 6, -41],
            ["guest-wifi", "aa:bb:cc:dd:ee:02", 149, -70.5],
        ],
    }
    frame = render.render(view(block))
    # BSSID (priority 3) does not fit 21 columns: its values follow each row.
    assert frame.lines == [
        "SSID        Ch  RSSI",
        "lab          6   -41",
        "  BSSID:",
        "  aa:bb:cc:dd:ee:01",
        "guest-wifi 149 -70.5",
        "  BSSID:",
        "  aa:bb:cc:dd:ee:02",
    ]
    assert ImageColor.getrgb(THEME.page_table_title_background.value) in body_colours(
        frame, row_y(0), row_y(1)
    )


def test_table_block_narrows_a_single_wide_column():
    block = {
        "type": "table",
        "text": "",
        "columns": [{"key": "msg", "label": "Message"}],
        "rows": [["x" * 40]],
    }
    frame = render.render(view(block))
    assert frame.lines[1] == "x" * 20 + render.ELLIPSIS


def test_list_block_highlights_the_selection_and_marks_branches():
    block = {
        "type": "list",
        "text": "",
        "selected": 1,
        "items": [
            {"label": "Network", "node": "network", "branch": True},
            {"label": "Bluetooth", "node": "bluetooth", "branch": True},
            {"label": "wlan0", "detail": "phy0"},
            {"label": "An option with a long label", "detail": "and a long detail too"},
        ],
    }
    frame = render.render(view(block, screen="menu"))
    assert frame.lines == [
        "  Network >",
        "> Bluetooth >",
        "  wlan0 (phy0)",
        "  An option with a long label (and a long detail too)",
    ]
    assert SELECTED_BG in body_colours(frame, row_y(1), row_y(2))
    assert SELECTED_BG not in body_colours(frame, row_y(0), row_y(1))
    assert SELECTED_BG not in body_colours(frame, row_y(2), row_y(8))


def test_long_list_scrolls_to_keep_the_selection_visible():
    items = [{"label": f"Item {i}"} for i in range(30)]
    top = render.render(
        view({"type": "list", "text": "", "selected": 0, "items": items})
    )
    deep = render.render(
        view({"type": "list", "text": "", "selected": 25, "items": items})
    )
    last = render.render(
        view({"type": "list", "text": "", "selected": 29, "items": items})
    )
    assert top.scroll == 0
    assert top.max_scroll == (30 - render.ROWS) * render.ROW_H
    assert deep.scroll % render.ROW_H == 0
    assert deep.scroll <= 25 * render.ROW_H < deep.scroll + render.BODY_H
    assert last.scroll == last.max_scroll
    for frame in (top, deep, last):
        assert SELECTED_BG in body_colours(frame)


def test_status_block_uses_the_level_colour():
    for level, colour in render.LEVEL_COLOURS.items():
        frame = render.render(
            view(
                {"type": "status", "level": level, "text": "All good", "label": "Core"}
            )
        )
        assert frame.lines == [f"[{level}] Core: All good"]
        assert ImageColor.getrgb(colour) in body_colours(frame, row_y(0), row_y(1))
    plain = render.render(
        view({"type": "status", "level": "warn", "text": "Low battery"})
    )
    assert plain.lines == ["[warn] Low battery"]


def test_progress_block_fills_the_bar_by_percentage():
    def filled(pct):
        frame = render.render(
            view({"type": "progress", "text": "x", "pct": pct, "label": "Scanning"})
        )
        fill = ImageColor.getrgb(THEME.text_highlighted_color.value)
        y = row_y(1) + 5
        return sum(
            frame.image.getpixel((x, y)) == fill for x in range(render.PAGE_WIDTH)
        ), frame

    none, frame0 = filled(0)
    half, frame50 = filled(50)
    full, _ = filled(100)
    assert none == 0
    assert 0 < half < full
    assert abs(half * 2 - full) <= 3
    assert frame0.lines == ["[progress 0%] Scanning"]
    assert frame50.lines == ["[progress 50%] Scanning"]


def test_indeterminate_progress_moves_with_the_tick():
    block = {"type": "progress", "text": "Working…", "pct": None}
    a = render.render(view(block), tick=0)
    b = render.render(view(block), tick=1)
    assert a.lines == ["[progress …] Working…"]
    assert a.image.tobytes() != b.image.tobytes()


def test_confirm_block_highlights_the_selected_button():
    def frame_for(selected):
        return render.render(
            view(
                {
                    "type": "confirm",
                    "text": "",
                    "prompt_id": "pabcd",
                    "message": "Reboot the WLAN Pi now?",
                    "confirm_label": "Reboot",
                    "selected": selected,
                },
                screen="prompt",
            )
        )

    def highlight_side(frame):
        px = frame.image.load()
        xs = [
            x
            for y in range(render.BODY_TOP, render.BODY_TOP + render.BODY_H)
            for x in range(render.PAGE_WIDTH)
            if px[x, y] == SELECTED_BG
        ]
        return "left" if max(xs) < render.PAGE_WIDTH // 2 else "right"

    cancel, confirm = frame_for("cancel"), frame_for("confirm")
    assert cancel.lines == ["Reboot the WLAN Pi", "now?", "[Cancel]  Reboot "]
    assert confirm.lines[-1] == " Cancel  [Reboot]"
    assert highlight_side(cancel) == "left"
    assert highlight_side(confirm) == "right"


def test_confirm_block_stacks_long_labels():
    frame = render.render(
        view(
            {
                "type": "confirm",
                "text": "",
                "prompt_id": "pabcd",
                "message": "Sure?",
                "confirm_label": "Yes, switch mode",
                "cancel_label": "No, stay here",
                "selected": "confirm",
            }
        )
    )
    assert frame.lines[-1] == " No, stay here  [Yes, switch mode]"
    px = frame.image.load()
    ys = [y for y in range(128) for x in range(128) if px[x, y] == SELECTED_BG]
    assert min(ys) > row_y(2)  # the second, lower button


def test_qr_block_draws_the_real_code():
    data = "WIFI:S:WLAN Pi A1B2;T:WPA;P:wifipros123;;"
    frame = render.render(
        view(
            {"type": "qr", "text": "fallback", "data": data, "caption": "WLAN Pi A1B2"}
        )
    )
    modules = qr.matrix(data)
    size = len(modules)
    scale = (render.BODY_H - render.ROW_H) // size
    assert scale >= 2
    assert frame.lines == [f"[qr {size * scale}x{size * scale}] WLAN Pi A1B2"]
    # Sample the centre of every module: the panel shows exactly the code.
    x0 = (render.PAGE_WIDTH - size * scale) // 2
    for row in range(size):
        for col in range(size):
            pixel = frame.image.getpixel(
                (
                    x0 + col * scale + scale // 2,
                    render.BODY_TOP + row * scale + scale // 2,
                )
            )
            assert pixel == ((0, 0, 0) if modules[row][col] else (255, 255, 255)), (
                row,
                col,
            )
    # Quiet zone, finder pattern corner.
    assert modules[0][0] is False and modules[qr.BORDER][qr.BORDER] is True


def test_qr_block_too_dense_for_the_panel_falls_back_to_text():
    frame = render.render(
        view({"type": "qr", "text": "Open the WebUI", "data": "x" * 1500})
    )
    assert frame.lines == ["Open the WebUI"]


def test_unknown_block_type_uses_its_text_fallback():
    frame = render.render(view({"type": "sparkline", "text": "cpu 3 4 5"}))
    assert frame.lines == ["cpu 3 4 5"]


def test_tall_result_scrolls_by_offset():
    rows = [{"type": "text", "text": f"line {i}"} for i in range(20)]
    top = render.render(view(*rows))
    assert top.max_scroll == (20 - render.ROWS) * render.ROW_H
    scrolled = render.render(view(*rows), scroll=render.ROW_H * 3)
    assert scrolled.scroll == render.ROW_H * 3
    assert scrolled.image.tobytes() != top.image.tobytes()
    clamped = render.render(view(*rows), scroll=10_000)
    assert clamped.scroll == clamped.max_scroll
    # A scrollbar appears only when there is something to scroll.
    bar = ImageColor.getrgb(THEME.page_table_scrollbar.value)
    assert top.image.getpixel((127, render.BODY_TOP + 1)) == bar
    short = render.render(view(rows[0]))
    assert short.max_scroll == 0
    assert short.image.getpixel((127, render.BODY_TOP + 1)) == BACKGROUND


def test_title_page_position_and_badge():
    paged = render.render(view(page={"index": 1, "count": 3, "more": True}))
    plain = render.render(view(page={"index": 0, "count": 1, "more": False}))
    badge = render.render(view(), badge="2 jobs")
    assert paged.title == "Test"
    assert paged.image.tobytes() != plain.image.tobytes()
    assert badge.image.tobytes() != plain.image.tobytes()


def test_hints_and_driven_by_indicator():
    mine = render.render(
        view(
            hints={"left": "Back", "center": "Select"},
            driven_by={
                "principal": {"kind": "local", "name": "root"},
                "surface": "wlanpi-fpms",
                "self": True,
            },
        )
    )
    theirs = render.render(
        view(
            hints={"left": "Back", "center": "Select"},
            driven_by={
                "principal": {"kind": "webui", "name": "admin"},
                "surface": "wlanpi-webui",
                "self": False,
            },
        )
    )
    assert mine.lines == ["(◀Back ●Select)"]
    assert theirs.lines == ["(◀Back ●Select)", "(driven by webui)"]
    assert mine.image.tobytes() != theirs.image.tobytes()
    assert (
        render.driver_label(
            {"principal": {"kind": "local", "name": "wlanpi"}, "self": False}
        )
        == "wlanpi"
    )
    assert (
        render.driver_label(
            {
                "principal": {"kind": "local", "name": "x"},
                "surface": "wlanpi-menu-tui",
                "self": False,
            }
        )
        == "tui"
    )
    assert render.driver_label(None) is None


def test_notice_overlay():
    frame = render.render(
        view({"type": "text", "text": "body"}), notice="FORBIDDEN: not yours"
    )
    assert frame.lines == ["body", "! FORBIDDEN: not yours"]
    assert ImageColor.getrgb(THEME.alert_popup_background.value) in body_colours(frame)


def test_unavailable_view_shows_addresses():
    starting = render.render(
        render.unavailable_view(
            [("eth0", "192.0.2.7")], "wlanpi-x", failures=0, reason=None
        )
    )
    assert starting.lines == [
        "[info] Starting menu: Connecting…",
        "eth0: 192.0.2.7",
        "wlanpi-x",
    ]
    down = render.render(
        render.unavailable_view(
            [("eth0", "192.0.2.7"), ("wlan0", "198.51.100.3")],
            "wlanpi-x",
            failures=3,
            reason="refused",
        )
    )
    assert down.lines == [
        "[error] Menu unavailable: Retrying…",
        "eth0: 192.0.2.7",
        "wlan0: 198.51.100.3",
        "wlanpi-x",
        "refused",
    ]
    assert ImageColor.getrgb(render.LEVEL_COLOURS["error"]) in body_colours(down)
    no_ip = render.render(render.unavailable_view([], "", failures=1, reason=None))
    assert no_ip.lines == [
        "[error] Menu unavailable: Retrying…",
        "[warn] No IP address",
    ]
