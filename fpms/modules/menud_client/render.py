"""Draw a ``view`` frame on the 128x128 panel (with 64px degradation floor).

Layout: an inverted title bar (with mode indicator and optional breadcrumb), a
body and a key-legend footer. The body is laid out at its full height on an
off-screen canvas and the visible window is cropped from it, so anything taller
than the screen scrolls. A list with a selection (a menu, a select prompt) or
a confirm block scrolls itself to keep the selection in sight.

All eight block types are drawn natively; an unknown type falls back to the
block's ``text``, as the protocol requires.

``Frame.lines`` is the same screen as plain text. The virtual screen prints
it on a terminal and tests assert on it.
"""

from __future__ import annotations

import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw

from fpms.modules.constants import (
    DISPLAY_MODE,
    FONT9,
    FONT10,
    FONTB10,
    FONTB11,
    PAGE_HEIGHT,
    PAGE_WIDTH,
)
from fpms.modules.themes import THEME

from . import glyphs, qr

TITLE_H = 15
FOOTER_H = 12
ROW_H = 12
ROWS = (PAGE_HEIGHT - TITLE_H - FOOTER_H) // ROW_H
BODY_H = ROWS * ROW_H  # whole rows only, so a scrolled screen never shows half a row
BODY_TOP = TITLE_H + 1
CHAR_W = FONT10.getlength("M")
COLS = int(PAGE_WIDTH // CHAR_W)
FOOTER_COLS = int(PAGE_WIDTH // FONT9.getlength("M"))

LEVEL_COLOURS = {
    "ok": "#2e8540",
    "info": "#4773aa",
    "warn": "#fdb81e",
    "error": "#cd2026",
}
LEVEL_GLYPHS = {
    "ok": "dot_filled",
    "info": "dot_hollow",
    "warn": "dot_hollow",
    "error": "alert",
}
KEY_GLYPHS = {
    "left": "◀",
    "right": "▶",
    "up": "▲",
    "down": "▼",
    "center": "●",
    "key1": "1:",
    "key2": "2:",
    "key3": "3:",
}
HINT_ORDER = ("left", "center", "right", "up", "down", "key1", "key2", "key3")
DRIVEN_GLYPH = "⇄"
ELLIPSIS = "…"


def _c(name: str) -> Any:
    return getattr(THEME, name).value


@dataclass
class Frame:
    image: Image.Image
    title: str
    lines: list[str]
    max_scroll: int = 0
    scroll: int = 0


@dataclass
class _Body:
    """Draw operations for the body, each with its height in pixels."""

    ops: list[tuple[int, Callable[[ImageDraw.ImageDraw, Image.Image, int], None]]] = (
        field(default_factory=list)
    )
    lines: list[str] = field(default_factory=list)
    height: int = 0
    focus: tuple[int, int] | None = None  # pixel range that must stay visible

    def add(
        self, height: int, fn: Callable[[ImageDraw.ImageDraw, Image.Image, int], None]
    ) -> None:
        self.ops.append((height, fn))
        self.height += height

    def row(
        self,
        text: str,
        *,
        font: Any = FONT10,
        fill: Any = None,
        bg: Any = None,
        x: int = 0,
        right: str | None = None,
        right_fill: Any = None,
    ) -> None:
        fill = fill if fill is not None else _c("text_color")

        def draw(d: ImageDraw.ImageDraw, _img: Image.Image, y: int) -> None:
            if bg is not None:
                d.rectangle((0, y, PAGE_WIDTH, y + ROW_H - 1), fill=bg)
            d.text((x + 1, y), text, font=font, fill=fill)
            if right:
                rx = PAGE_WIDTH - 2 - font.getlength(right)
                d.text((rx, y), right, font=font, fill=right_fill or fill)

        self.add(ROW_H, draw)


def clip(text: str, width: int) -> str:
    text = str(text)
    if len(text) <= width:
        return text
    return text[: max(width - 1, 0)] + ELLIPSIS if width > 0 else ""


def wrap(text: str, width: int = COLS) -> list[str]:
    out: list[str] = []
    for para in str(text).splitlines() or [""]:
        out.extend(
            textwrap.wrap(para, width, break_long_words=True, break_on_hyphens=False)
            or [""]
        )
    return out


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def is_numeric_str(val: str) -> bool:
    """Check whether a string represents a number (int, float, negative)."""
    s = val.strip()
    if not s:
        return False
    if s.startswith(("-", "+")):
        s = s[1:]
    parts = s.split(".", 1)
    if len(parts) == 1:
        return parts[0].isdigit()
    return parts[0].isdigit() and parts[1].isdigit()


# ---------------------------------------------------------------------- blocks


def _text(body: _Body, b: dict[str, Any]) -> None:
    style = b.get("style", "body")
    font = FONTB10 if style == "heading" else FONT10
    fill = _c("text_secondary_color") if style == "muted" else _c("text_color")
    if style == "heading":
        fill = _c("text_highlighted_color")
    for line in wrap(b.get("text", ""), COLS - 1):
        body.row(line, font=font, fill=fill, x=2)
        body.lines.append(line)


def _kv(body: _Body, b: dict[str, Any]) -> None:
    for item in b.get("items", []):
        key, value = str(item.get("key", "")), _cell(item.get("value"))
        body.lines.append(f"{key}: {value}")
        if len(key) + 2 + len(value) <= COLS:
            # Key and value on one row, with dotted leaders connecting them.
            def draw(
                d: ImageDraw.ImageDraw,
                _img: Image.Image,
                y: int,
                key: str = key,
                value: str = value,
            ) -> None:
                key_text = f"{key}:"
                d.text((2, y), key_text, font=FONT10, fill=_c("text_secondary_color"))
                kx = 2 + int(FONT10.getlength(key_text)) + 3
                vx = PAGE_WIDTH - 2 - int(FONT10.getlength(value))
                d.text(
                    (vx, y),
                    value,
                    font=FONT10,
                    fill=_c("text_color"),
                )
                # Dotted leader between key and value when long enough
                if vx > kx + 8:
                    for px in range(kx, vx - 4, 4):
                        d.point((px, y + ROW_H - 4), fill=_c("text_secondary_color"))

            body.add(ROW_H, draw)
        else:
            for line in wrap(f"{key}:", COLS - 1):
                body.row(line, fill=_c("text_secondary_color"), x=2)
            for line in wrap(value, COLS - 2):
                body.row(line, x=int(CHAR_W) + 2)


def table_layout(
    columns: list[dict[str, Any]], rows: list[list[Any]]
) -> list[tuple[int, int]]:
    """(column index, width in characters) for the columns that fit, in display order.

    Columns are dropped highest ``priority`` number first (lower is kept
    first); what is left is narrowed, widest first, until the row fits.
    The caller lists a dropped column's values under each row.
    """
    widths = []
    for i, col in enumerate(columns):
        cells = [len(_cell(r[i])) for r in rows if i < len(r)]
        widths.append(max([len(str(col.get("label", ""))), *cells]))
    keep = list(range(len(columns)))
    by_drop_order = sorted(keep, key=lambda i: (columns[i].get("priority", i), i))
    cap = 12  # a long cell is clipped before a whole column is given up for it

    def total(cols: list[int]) -> int:
        return sum(min(widths[i], cap) for i in cols) + len(cols) - 1

    while len(keep) > 1 and total(keep) > COLS:
        keep.remove(by_drop_order.pop())
    sized = {i: widths[i] for i in keep}
    while sum(sized.values()) + len(sized) - 1 > COLS:
        widest = max(sized, key=lambda i: sized[i])
        if sized[widest] <= 1:
            break
        sized[widest] -= 1
    return [(i, sized[i]) for i in keep]


def _table(body: _Body, b: dict[str, Any]) -> None:
    columns = b.get("columns", [])
    rows = b.get("rows", [])

    # Column alignment: explicit or computed from cell content
    computed_align: dict[int, str] = {}
    for i, col in enumerate(columns):
        if col.get("align") in ("left", "right"):
            computed_align[i] = col["align"]
        else:
            cells = [_cell(r[i]) for r in rows if i < len(r) and _cell(r[i]).strip()]
            if cells and all(is_numeric_str(c) for c in cells):
                computed_align[i] = "right"
            else:
                computed_align[i] = "left"

    layout = table_layout(columns, rows)

    def fmt(cells: list[str]) -> str:
        parts = []
        for i, width in layout:
            text = clip(cells[i] if i < len(cells) else "", width)
            right = computed_align.get(i) == "right"
            parts.append(text.rjust(width) if right else text.ljust(width))
        return " ".join(parts).rstrip()

    head = fmt([str(c.get("label", "")) for c in columns])

    def draw_head(d: ImageDraw.ImageDraw, _img: Image.Image, y: int) -> None:
        # Inverted title header with thin rule line
        d.rectangle(
            (0, y, PAGE_WIDTH, y + ROW_H - 1), fill=_c("page_table_title_background")
        )
        d.text((2, y), head, font=FONTB10, fill=_c("page_table_title_foreground"))
        d.line(
            (0, y + ROW_H - 1, PAGE_WIDTH, y + ROW_H - 1),
            fill=_c("page_table_row_separator"),
        )

    body.add(ROW_H, draw_head)
    body.lines.append(head)
    shown = {i for i, _ in layout}

    # Blank repeated section labels (UX round-2 parity)
    last_section: str | None = None
    section_col_idx: int | None = None
    for i, col in enumerate(columns):
        if (
            str(col.get("key", "")).lower() == "section"
            or str(col.get("label", "")).lower() == "section"
        ):
            section_col_idx = i
            break

    for r in rows:
        cells = [_cell(c) for c in r]
        display_cells = list(cells)
        if section_col_idx is not None and section_col_idx < len(display_cells):
            sec = display_cells[section_col_idx].strip()
            if sec and sec == last_section:
                display_cells[section_col_idx] = ""
            elif sec:
                last_section = sec

        line = fmt(display_cells)
        body.row(line, x=1)
        body.lines.append(line)

        # Columns that did not fit are not lost: their values follow the row.
        for i, col in enumerate(columns):
            if i in shown or i >= len(cells) or not cells[i].strip():
                continue
            for extra in wrap(f"{col.get('label', '')}: {cells[i].strip()}", COLS - 2):
                body.row(extra, fill=_c("text_secondary_color"), x=int(CHAR_W * 2))
                body.lines.append("  " + extra)


def _list(body: _Body, b: dict[str, Any]) -> None:
    selected = b.get("selected")
    for i, item in enumerate(b.get("items", [])):
        is_sel = selected is not None and i == selected
        label = str(item.get("label", ""))
        detail = item.get("detail")
        mark = ">" if item.get("branch") else None
        fg = (
            _c("page_selected_item_foreground")
            if is_sel
            else _c("page_item_foreground")
        )
        bg = _c("page_selected_item_background") if is_sel else None
        dim = fg if is_sel else _c("text_secondary_color")
        start = body.height
        room = COLS - (3 if mark else 1) - (2 if is_sel else 0)
        inline = detail is not None and len(label) + 1 + len(str(detail)) <= room

        def draw_row(
            d: ImageDraw.ImageDraw,
            _img: Image.Image,
            y: int,
            label: str = label,
            detail: Any = detail,
            is_sel: bool = is_sel,
            mark: str | None = mark,
            inline: bool = inline,
            fg: Any = fg,
            bg: Any = bg,
            dim: Any = dim,
            room: int = room,
        ) -> None:
            if is_sel:
                # Inverted pill across row with 2px margins and arrow glyph
                d.rounded_rectangle(
                    (2, y, PAGE_WIDTH - 3, y + ROW_H - 1),
                    radius=2,
                    fill=bg,
                )
                glyphs.draw_glyph(d, 4, y + 2, "arrow", fill=fg, size=8)
                tx = 14
            else:
                tx = 4

            if inline and detail is not None:
                d.text((tx, y), label, font=FONT10, fill=fg)
                right_text = f"{detail}{' >' if mark else ''}"
                rx = PAGE_WIDTH - 4 - FONT10.getlength(right_text)
                d.text((rx, y), right_text, font=FONT10, fill=dim)
            else:
                d.text((tx, y), clip(label, room), font=FONT10, fill=fg)
                if mark:
                    rx = PAGE_WIDTH - 4 - FONT10.getlength(mark)
                    d.text((rx, y), mark, font=FONT10, fill=fg)

        body.add(ROW_H, draw_row)

        if not inline and detail is not None:

            def draw_sub(
                d: ImageDraw.ImageDraw,
                _img: Image.Image,
                y: int,
                detail: Any = detail,
                is_sel: bool = is_sel,
                bg: Any = bg,
                dim: Any = dim,
            ) -> None:
                if is_sel:
                    d.rectangle((2, y, PAGE_WIDTH - 3, y + ROW_H - 1), fill=bg)
                d.text(
                    (int(CHAR_W * 2) + 2, y),
                    clip(str(detail), COLS - 3),
                    font=FONT10,
                    fill=dim,
                )

            body.add(ROW_H, draw_sub)

        if is_sel:
            body.focus = (start, body.height)
        text = ("> " if is_sel else "  ") + label
        if detail is not None:
            text += f" ({detail})"
        if mark:
            text += " >"
        body.lines.append(text)


def _status(body: _Body, b: dict[str, Any]) -> None:
    level = b.get("level", "info")
    colour = LEVEL_COLOURS.get(level, LEVEL_COLOURS["info"])
    glyph_name = LEVEL_GLYPHS.get(level, "dot_hollow")
    label = b.get("label")
    lines = wrap(b.get("text", ""), COLS - 3)
    if label:
        lines = [clip(str(label), COLS - 3), *wrap(b.get("text", ""), COLS - 3)]
    for n, line in enumerate(lines):
        first = n == 0

        def draw(
            d: ImageDraw.ImageDraw,
            _img: Image.Image,
            y: int,
            line: str = line,
            first: bool = first,
            bold: bool = bool(label) and first,
            colour: str = colour,
            glyph_name: str = glyph_name,
        ) -> None:
            if first:
                # Colored-equivalent treatment via glyph (dot/alert/check) + value emphasis
                glyphs.draw_glyph(d, 2, y + 2, glyph_name, fill=colour, size=8)
            d.text(
                (1 + CHAR_W * 2, y),
                line,
                font=FONTB10 if bold else FONT10,
                fill=colour if bold else _c("text_color"),
            )

        body.add(ROW_H, draw)
    prefix = f"[{level}] " + (f"{label}: " if label else "")
    body.lines.append(prefix + str(b.get("text", "")).replace("\n", " "))


def _progress(body: _Body, b: dict[str, Any], tick: int) -> None:
    pct = b.get("pct")
    label = b.get("label") or b.get("text") or ""
    for line in wrap(label, COLS - 1):
        body.row(line, x=2)

    def draw(d: ImageDraw.ImageDraw, _img: Image.Image, y: int) -> None:
        x0, x1 = 2, PAGE_WIDTH - 4
        # Bordered progress bar outline
        d.rectangle((x0, y + 2, x1, y + 9), outline=_c("text_secondary_color"))
        span = x1 - x0 - 3
        if pct is None:
            # Indeterminate: a block that walks along the bar.
            width = span // 4
            at = (tick * 8) % (span - width + 1)
            d.rectangle(
                (x0 + 2 + at, y + 4, x0 + 2 + at + width, y + 7),
                fill=_c("text_highlighted_color"),
            )
        elif pct > 0:
            fill = int(span * min(float(pct), 100.0) / 100)
            d.rectangle(
                (x0 + 2, y + 4, x0 + 2 + fill, y + 7), fill=_c("text_highlighted_color")
            )

    body.add(ROW_H, draw)

    # Secondary progress stats line: percent + elapsed
    elapsed = b.get("elapsed") or b.get("elapsed_sec")
    shown = ELLIPSIS if pct is None else f"{float(pct):.0f}%"

    def draw_stats(
        d: ImageDraw.ImageDraw,
        _img: Image.Image,
        y: int,
        shown: str = shown,
        elapsed: Any = elapsed,
    ) -> None:
        d.text((2, y), shown, font=FONT9, fill=_c("text_secondary_color"))
        if elapsed:
            estr = str(elapsed)
            ex = PAGE_WIDTH - 4 - FONT9.getlength(estr)
            d.text((ex, y), estr, font=FONT9, fill=_c("text_secondary_color"))

    if pct is not None or elapsed is not None or b.get("show_stats"):
        body.add(ROW_H - 2, draw_stats)

    body.lines.append(f"[progress {shown}] {label}".rstrip())


def _confirm(body: _Body, b: dict[str, Any]) -> None:
    message_lines = wrap(b.get("message", b.get("text", "")), COLS - 1)
    for line in message_lines:
        body.row(line, x=2)
        body.lines.append(line)
    selected = b.get("selected", "cancel")
    buttons = [
        ("cancel", str(b.get("cancel_label", "Cancel"))),
        ("confirm", str(b.get("confirm_label", "Confirm"))),
    ]
    stacked = sum(len(text) for _, text in buttons) + 5 > COLS
    start = body.height

    def button(
        d: ImageDraw.ImageDraw, x0: int, x1: int, y: int, which: str, text: str
    ) -> None:
        on = which == selected
        # Dialog-style box with [ Cancel ] / [ OK ] pills, selected one inverted
        d.rounded_rectangle(
            (x0, y + 1, x1, y + ROW_H - 1),
            radius=2,
            fill=_c("page_selected_item_background") if on else None,
            outline=_c("page_selected_item_background")
            if on
            else _c("text_secondary_color"),
        )
        tx = x0 + (x1 - x0 - FONTB10.getlength(text)) / 2
        d.text(
            (tx, y),
            text,
            font=FONTB10,
            fill=_c("page_selected_item_foreground") if on else _c("text_color"),
        )

    if stacked:
        for which, text in buttons:

            def one(
                d: ImageDraw.ImageDraw,
                _img: Image.Image,
                y: int,
                which: str = which,
                text: str = text,
            ) -> None:
                button(d, 2, PAGE_WIDTH - 4, y, which, clip(text, COLS - 2))

            body.add(ROW_H, one)
    else:
        mid = PAGE_WIDTH // 2

        def both(d: ImageDraw.ImageDraw, _img: Image.Image, y: int) -> None:
            button(d, 2, mid - 2, y, *buttons[0])
            button(d, mid + 1, PAGE_WIDTH - 4, y, *buttons[1])

        body.add(ROW_H, both)
    body.focus = (start, body.height)
    body.lines.append(
        " ".join(
            f"[{text}]" if which == selected else f" {text} " for which, text in buttons
        )
    )


def _qr(body: _Body, b: dict[str, Any], body_h: int = BODY_H) -> None:
    caption = b.get("caption")
    cap_lines = wrap(caption, COLS - 1) if caption else []
    room = min(PAGE_WIDTH, max(ROW_H, body_h - ROW_H * len(cap_lines)))
    if room < 33:
        room = min(PAGE_WIDTH, body_h)
    code = qr.image(str(b.get("data", "")), room)
    if code is None:
        # Too much data for one pixel per module: show the text instead.
        _text(body, {"text": b.get("text", "")})
        return

    def draw(_d: ImageDraw.ImageDraw, img: Image.Image, y: int) -> None:
        img.paste(code, ((PAGE_WIDTH - code.width) // 2, y))

    body.add(code.height, draw)
    for line in cap_lines:
        body.row(line.center(COLS), fill=_c("text_secondary_color"))
    body.lines.append(
        f"[qr {code.width}x{code.height}] {caption or b.get('text', '')}".rstrip()
    )


def _complications_row(
    body: _Body, complications: list[dict[str, Any]], clock: str | None = None
) -> None:
    """Render a dedicated complications status strip with clock and glyphs."""
    clock_str = clock or time.strftime("%H:%M")

    def draw(d: ImageDraw.ImageDraw, _img: Image.Image, y: int) -> None:
        # Subtle horizontal divider below complications
        d.line(
            (0, y + ROW_H - 1, PAGE_WIDTH, y + ROW_H - 1),
            fill=_c("page_table_row_separator"),
        )
        # Clock at left
        d.text((2, y + 1), clock_str, font=FONTB10, fill=_c("text_color"))
        cx = 2 + int(FONTB10.getlength(clock_str)) + 6

        # Draw complications that fit
        for item in complications:
            if cx + 18 > PAGE_WIDTH - 2:
                break
            app_id = str(item.get("app_id", ""))
            icon_name = item.get("icon")
            if not icon_name:
                if "wifi" in app_id:
                    icon_name = "wifi"
                elif "blue" in app_id:
                    icon_name = "bluetooth"
                elif "bat" in app_id:
                    icon_name = "battery"
                elif "plug" in app_id or "pwr" in app_id:
                    icon_name = "plug"
                elif item.get("status") == "error":
                    icon_name = "alert"
                elif item.get("status") == "ok":
                    icon_name = "dot_filled"
                else:
                    icon_name = "dot_hollow"

            status = item.get("status", "info")
            fill = LEVEL_COLOURS.get(status, _c("text_color"))
            glyphs.draw_glyph(d, cx, y + 2, icon_name, fill=fill, size=8)
            cx += 10
            val = str(item.get("value") or item.get("label") or "")
            if val and cx + int(FONT9.getlength(val)) <= PAGE_WIDTH - 2:
                d.text((cx, y + 1), val, font=FONT9, fill=fill)
                cx += int(FONT9.getlength(val)) + 4

    body.add(ROW_H, draw)
    parts = [clock_str]
    for item in complications:
        label = item.get("label") or item.get("app_id")
        val = item.get("value")
        parts.append(f"[{label}: {val}]" if val else f"[{label}]")
    body.lines.append(" ".join(parts))


def _blocks(
    blocks: list[dict[str, Any]],
    tick: int,
    screen: str | None = None,
    complications: list[dict[str, Any]] | None = None,
    clock: str | None = None,
    body_h: int = BODY_H,
) -> _Body:
    body = _Body()
    # On home screen, complications row is rendered at top of body so it is visible at 64px
    if screen == "home" and complications:
        _complications_row(body, complications, clock=clock)

    for b in blocks:
        kind = b.get("type")
        if kind == "text":
            _text(body, b)
        elif kind == "kv":
            _kv(body, b)
        elif kind == "table":
            _table(body, b)
        elif kind == "list":
            _list(body, b)
        elif kind == "status":
            _status(body, b)
        elif kind == "progress":
            _progress(body, b, tick)
        elif kind == "confirm":
            _confirm(body, b)
        elif kind == "qr":
            _qr(body, b, body_h=body_h)
        else:
            _text(body, {"text": b.get("text", "")})

    return body


# ---------------------------------------------------------------------- screen


def hint_text(hints: dict[str, str]) -> str:
    parts = [f"{KEY_GLYPHS[k]}{hints[k]}" for k in HINT_ORDER if hints.get(k)]
    return " ".join(parts)


def driver_label(driven_by: dict[str, Any] | None) -> str | None:
    """Short name of the other surface driving the shared screen, or None when it is us."""
    if not driven_by or driven_by.get("self"):
        return None
    name = (
        driven_by.get("surface")
        or (driven_by.get("principal") or {}).get("name")
        or "?"
    )
    for prefix in ("wlanpi-menu-", "wlanpi-"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    return clip(name, 6)


def image_to_ascii(img: Image.Image) -> str:
    """Render an image to a deterministic ASCII-art snapshot using Unicode half-blocks."""
    rgb_img = img.convert("RGB")
    w, h = rgb_img.size

    def _is_on(x: int, y: int) -> bool:
        pixel = rgb_img.getpixel((x, y))
        if not isinstance(pixel, tuple):
            return False
        r, g, b = pixel[:3]
        if y < TITLE_H:
            # Title bar header: blue background is ON, white/bright text cutout is OFF
            is_blue_bar = r < 50 and 80 <= g <= 140 and 150 <= b <= 220
            if is_blue_bar:
                return True
            # Foreground text drawn inside title bar
            if r > 100 or (r > 60 and g > 150 and b > 210):
                return False
            # Otherwise (e.g. if title bg was mutated to black)
            return bool((0.299 * r + 0.587 * g + 0.114 * b) > 64)

        # Table row separator rule #205493 (32, 84, 147) is dark rule line: OFF
        if (r, g, b) == (32, 84, 147) or (r < 50 and 70 <= g <= 95 and 130 <= b <= 160):
            return False

        lum = 0.299 * r + 0.587 * g + 0.114 * b
        return bool(lum > 64)

    lines = ["+" + "-" * w + "+"]
    for y in range(0, h, 2):
        row = []
        for x in range(w):
            top = _is_on(x, y)
            bot = _is_on(x, y + 1) if y + 1 < h else False
            if top and bot:
                row.append("█")
            elif top:
                row.append("▀")
            elif bot:
                row.append("▄")
            else:
                row.append(" ")
        lines.append("|" + "".join(row) + "|")
    lines.append("+" + "-" * w + "+")
    return "\n".join(lines)


def render(
    view: dict[str, Any],
    *,
    scroll: int = 0,
    notice: str | None = None,
    badge: str | None = None,
    tick: int = 0,
    mode: str | None = None,
    complications: list[dict[str, Any]] | None = None,
    clock: str | None = None,
    height: int = PAGE_HEIGHT,
) -> Frame:
    """Draw a view frame (or anything shaped like one: title, blocks, hints)."""
    page_height = height
    image = Image.new(DISPLAY_MODE, (PAGE_WIDTH, page_height), _c("display_background"))
    draw = ImageDraw.Draw(image)
    title = str(view.get("title") or "WLAN Pi")
    screen = view.get("screen")

    # Header bar: inverted title strip + right-aligned mode indicator
    mode_str = mode or view.get("mode") or view.get("device_mode")
    page = view.get("page") or {}
    right = badge or ""
    if page.get("count", 1) > 1 or page.get("more"):
        right = f"{page.get('index', 0) + 1}/{page.get('count', '?')}"
    elif not right and mode_str:
        right = str(mode_str).upper()

    draw.rectangle((0, 0, PAGE_WIDTH, TITLE_H - 1), fill=_c("page_title_background"))
    title_cols = int(PAGE_WIDTH // FONTB11.getlength("M")) - (
        len(right) + 1 if right else 0
    )
    draw.text(
        (2, 1), clip(title, title_cols), font=FONTB11, fill=_c("page_title_foreground")
    )
    if right:
        draw.text(
            (PAGE_WIDTH - 2 - FONT10.getlength(right), 2),
            right,
            font=FONT10,
            fill=_c("page_title_foreground"),
        )

    # Breadcrumb as a slim second line where present
    breadcrumb = view.get("breadcrumb")
    body_top = BODY_TOP
    if breadcrumb:
        crumb_h = 10
        y_crumb = TITLE_H
        draw.rectangle(
            (0, y_crumb, PAGE_WIDTH, y_crumb + crumb_h - 1),
            fill=_c("display_background"),
        )
        crumb_text = " > ".join(str(c) for c in breadcrumb)
        draw.text(
            (2, y_crumb),
            clip(crumb_text, COLS),
            font=FONT9,
            fill=_c("text_secondary_color"),
        )
        draw.line(
            (0, y_crumb + crumb_h - 1, PAGE_WIDTH, y_crumb + crumb_h - 1),
            fill=_c("page_table_row_separator"),
        )
        body_top = y_crumb + crumb_h + 1

    # Effective body height respecting the 64px degradation floor
    effective_body_h = (page_height - body_top - FOOTER_H) // ROW_H * ROW_H
    effective_body_h = max(effective_body_h, ROW_H)

    comps = complications if complications is not None else view.get("complications")
    body = _blocks(
        view.get("blocks", []),
        tick,
        screen=screen,
        complications=comps,
        clock=clock,
        body_h=effective_body_h,
    )
    max_scroll = max(0, body.height - effective_body_h)
    if body.focus is not None:
        # Keep the selection near the middle, on a whole-row boundary.
        top, bottom = body.focus
        scroll = (top - (effective_body_h - (bottom - top)) // 2) // ROW_H * ROW_H
    scroll = max(0, min(scroll, max_scroll))

    canvas = Image.new(
        DISPLAY_MODE,
        (PAGE_WIDTH, max(body.height, effective_body_h)),
        _c("display_background"),
    )
    cdraw = ImageDraw.Draw(canvas)
    y = 0
    for h_op, fn in body.ops:
        fn(cdraw, canvas, y)
        y += h_op
    image.paste(
        canvas.crop((0, scroll, PAGE_WIDTH, scroll + effective_body_h)), (0, body_top)
    )
    if max_scroll:
        bar = max(8, effective_body_h * effective_body_h // body.height)
        at = body_top + (effective_body_h - bar) * scroll // max_scroll
        draw.rectangle(
            (PAGE_WIDTH - 2, at, PAGE_WIDTH - 1, at + bar),
            fill=_c("page_table_scrollbar"),
        )

    # Footer: the key legend, and who is driving the shared screen if not us.
    legend = hint_text(view.get("hints") or {})
    driver = driver_label(view.get("driven_by"))
    fy = page_height - FOOTER_H
    draw.rectangle((0, fy, PAGE_WIDTH, page_height), fill=_c("system_bar_background"))
    room = FOOTER_COLS - (len(driver) + 2 if driver else 0)
    draw.text(
        (1, fy + 1), clip(legend, room), font=FONT9, fill=_c("system_bar_foreground")
    )
    if driver:
        tag = f"{DRIVEN_GLYPH}{driver}"
        draw.text(
            (PAGE_WIDTH - 1 - FONT9.getlength(tag), fy + 1),
            tag,
            font=FONT9,
            fill=_c("text_highlighted_color"),
        )

    lines = list(body.lines)
    if notice:
        box = wrap(notice, COLS - 1)[:3]
        top = fy - ROW_H * len(box) - 3
        draw.rectangle(
            (0, top, PAGE_WIDTH - 1, fy - 1),
            fill=_c("alert_popup_background"),
            outline=_c("alert_error_title_background"),
        )
        for n, line in enumerate(box):
            draw.text(
                (3, top + 1 + n * ROW_H),
                line,
                font=FONT10,
                fill=_c("alert_popup_foreground"),
            )
        lines.append(f"! {notice}")
    if legend:
        lines.append(f"({legend})")
    if driver:
        lines.append(f"(driven by {driver})")
    return Frame(image, title, lines, max_scroll=max_scroll, scroll=scroll)


def unavailable_view(
    addresses: list[tuple[str, str]],
    hostname: str,
    *,
    failures: int,
    reason: str | None,
) -> dict[str, Any]:
    """The local screen shown while wlanpi-menud cannot be reached."""
    if failures:
        head = {
            "type": "status",
            "level": "error",
            "label": "Menu unavailable",
            "text": "Retrying" + ELLIPSIS,
        }
    else:
        head = {
            "type": "status",
            "level": "info",
            "label": "Starting menu",
            "text": "Connecting" + ELLIPSIS,
        }
    blocks: list[dict[str, Any]] = [head]
    if addresses:
        blocks.append(
            {
                "type": "kv",
                "text": "",
                "items": [{"key": n, "value": a} for n, a in addresses],
            }
        )
    else:
        blocks.append({"type": "status", "level": "warn", "text": "No IP address"})
    if hostname:
        blocks.append({"type": "text", "text": hostname, "style": "muted"})
    if failures and reason:
        blocks.append({"type": "text", "text": reason, "style": "muted"})
    return {
        "v": 1,
        "type": "view",
        "id": "s:unavailable",
        "screen": "unavailable",
        "title": "WLAN Pi",
        "blocks": blocks,
        "hints": {},
    }
