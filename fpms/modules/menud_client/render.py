"""Draw a ``view`` frame on the 128x128 panel.

Layout: a title bar, a body and a key-legend footer. The body is laid out
at its full height on an off-screen canvas and the visible window is
cropped from it, so anything taller than the screen scrolls. A list with a
selection (a menu, a select prompt) or a confirm block scrolls itself to
keep the selection in sight.

All eight block types are drawn natively; an unknown type falls back to the
block's ``text``, as the protocol requires.

``Frame.lines`` is the same screen as plain text. The virtual screen prints
it on a terminal and tests assert on it.
"""

from __future__ import annotations

import textwrap
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

from . import qr

TITLE_H = 15
FOOTER_H = 12
ROW_H = 12
ROWS = (PAGE_HEIGHT - TITLE_H - FOOTER_H) // ROW_H
BODY_H = ROWS * ROW_H  # whole rows only, so a scrolled screen never shows half a row
BODY_TOP = TITLE_H + 2
CHAR_W = FONT10.getlength("M")
COLS = int(PAGE_WIDTH // CHAR_W)
FOOTER_COLS = int(PAGE_WIDTH // FONT9.getlength("M"))

LEVEL_COLOURS = {
    "ok": "#2e8540",
    "info": "#4773aa",
    "warn": "#fdb81e",
    "error": "#cd2026",
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


# ---------------------------------------------------------------------- blocks


def _text(body: _Body, b: dict[str, Any]) -> None:
    style = b.get("style", "body")
    font = FONTB10 if style == "heading" else FONT10
    fill = _c("text_secondary_color") if style == "muted" else _c("text_color")
    if style == "heading":
        fill = _c("text_highlighted_color")
    for line in wrap(b.get("text", "")):
        body.row(line, font=font, fill=fill)
        body.lines.append(line)


def _kv(body: _Body, b: dict[str, Any]) -> None:
    for item in b.get("items", []):
        key, value = str(item.get("key", "")), _cell(item.get("value"))
        body.lines.append(f"{key}: {value}")
        if len(key) + 2 + len(value) <= COLS:
            # Key and value on one row, the value where the key ends.
            def draw(
                d: ImageDraw.ImageDraw,
                _img: Image.Image,
                y: int,
                key: str = key,
                value: str = value,
            ) -> None:
                d.text((1, y), f"{key}:", font=FONT10, fill=_c("text_secondary_color"))
                d.text(
                    (1 + CHAR_W * (len(key) + 2), y),
                    value,
                    font=FONT10,
                    fill=_c("text_color"),
                )

            body.add(ROW_H, draw)
        else:
            for line in wrap(f"{key}:"):
                body.row(line, fill=_c("text_secondary_color"))
            for line in wrap(value, COLS - 1):
                body.row(line, x=int(CHAR_W))


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
    layout = table_layout(columns, rows)

    def fmt(cells: list[str]) -> str:
        parts = []
        for i, width in layout:
            text = clip(cells[i] if i < len(cells) else "", width)
            right = columns[i].get("align") == "right"
            parts.append(text.rjust(width) if right else text.ljust(width))
        return " ".join(parts).rstrip()

    head = fmt([str(c.get("label", "")) for c in columns])
    body.row(
        head,
        font=FONTB10,
        fill=_c("page_table_title_foreground"),
        bg=_c("page_table_title_background"),
    )
    body.lines.append(head)
    shown = {i for i, _ in layout}
    for r in rows:
        cells = [_cell(c) for c in r]
        line = fmt(cells)
        body.row(line)
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
        room = COLS - (2 if mark else 0)
        inline = detail is not None and len(label) + 1 + len(str(detail)) <= room
        if inline:
            body.row(
                label,
                fill=fg,
                bg=bg,
                right=f"{detail}{' >' if mark else ''}",
                right_fill=dim,
            )
        else:
            body.row(clip(label, room), fill=fg, bg=bg, right=mark, right_fill=fg)
            if detail is not None:
                body.row(
                    clip(str(detail), COLS - 2), fill=dim, bg=bg, x=int(CHAR_W * 2)
                )
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
    label = b.get("label")
    lines = wrap(b.get("text", ""), COLS - 2)
    if label:
        lines = [clip(str(label), COLS - 2), *wrap(b.get("text", ""), COLS - 2)]
    for n, line in enumerate(lines):
        first = n == 0

        def draw(
            d: ImageDraw.ImageDraw,
            _img: Image.Image,
            y: int,
            line: str = line,
            first: bool = first,
            bold: bool = bool(label) and first,
        ) -> None:
            if first:
                d.rectangle((1, y + 3, 6, y + 8), fill=colour)
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
    for line in wrap(label):
        body.row(line)

    def draw(d: ImageDraw.ImageDraw, _img: Image.Image, y: int) -> None:
        x0, x1 = 2, PAGE_WIDTH - 4
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
    shown = ELLIPSIS if pct is None else f"{float(pct):.0f}%"
    body.lines.append(f"[progress {shown}] {label}".rstrip())


def _confirm(body: _Body, b: dict[str, Any]) -> None:
    for line in wrap(b.get("message", b.get("text", ""))):
        body.row(line)
        body.lines.append(line)
    body.add(4, lambda d, img, y: None)
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
        d.rectangle(
            (x0, y, x1, y + ROW_H),
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
                button(d, 2, PAGE_WIDTH - 3, y, which, clip(text, COLS - 2))

            body.add(ROW_H + 3, one)
    else:
        mid = PAGE_WIDTH // 2

        def both(d: ImageDraw.ImageDraw, _img: Image.Image, y: int) -> None:
            button(d, 2, mid - 2, y, *buttons[0])
            button(d, mid + 1, PAGE_WIDTH - 3, y, *buttons[1])

        body.add(ROW_H + 3, both)
    body.focus = (start, body.height)
    body.lines.append(
        " ".join(
            f"[{text}]" if which == selected else f" {text} " for which, text in buttons
        )
    )


def _qr(body: _Body, b: dict[str, Any]) -> None:
    caption = b.get("caption")
    cap_lines = wrap(caption) if caption else []
    room = min(PAGE_WIDTH, BODY_H - ROW_H * len(cap_lines))
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


def _blocks(blocks: list[dict[str, Any]], tick: int) -> _Body:
    body = _Body()
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
            _qr(body, b)
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


def render(
    view: dict[str, Any],
    *,
    scroll: int = 0,
    notice: str | None = None,
    badge: str | None = None,
    tick: int = 0,
) -> Frame:
    """Draw a view frame (or anything shaped like one: title, blocks, hints)."""
    image = Image.new(DISPLAY_MODE, (PAGE_WIDTH, PAGE_HEIGHT), _c("display_background"))
    draw = ImageDraw.Draw(image)
    title = str(view.get("title") or "WLAN Pi")

    body = _blocks(view.get("blocks", []), tick)
    max_scroll = max(0, body.height - BODY_H)
    if body.focus is not None:
        # Keep the selection near the middle, on a whole-row boundary.
        top, bottom = body.focus
        scroll = (top - (BODY_H - (bottom - top)) // 2) // ROW_H * ROW_H
    scroll = max(0, min(scroll, max_scroll))
    canvas = Image.new(
        DISPLAY_MODE, (PAGE_WIDTH, max(body.height, BODY_H)), _c("display_background")
    )
    cdraw = ImageDraw.Draw(canvas)
    y = 0
    for height, fn in body.ops:
        fn(cdraw, canvas, y)
        y += height
    image.paste(canvas.crop((0, scroll, PAGE_WIDTH, scroll + BODY_H)), (0, BODY_TOP))
    if max_scroll:
        bar = max(8, BODY_H * BODY_H // body.height)
        at = BODY_TOP + (BODY_H - bar) * scroll // max_scroll
        draw.rectangle(
            (PAGE_WIDTH - 2, at, PAGE_WIDTH - 1, at + bar),
            fill=_c("page_table_scrollbar"),
        )

    # Title bar: title on the left; page position (or a badge) on the right.
    page = view.get("page") or {}
    right = badge or ""
    if page.get("count", 1) > 1 or page.get("more"):
        right = f"{page.get('index', 0) + 1}/{page.get('count', '?')}"
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

    # Footer: the key legend, and who is driving the shared screen if not us.
    legend = hint_text(view.get("hints") or {})
    driver = driver_label(view.get("driven_by"))
    fy = PAGE_HEIGHT - FOOTER_H
    draw.rectangle((0, fy, PAGE_WIDTH, PAGE_HEIGHT), fill=_c("system_bar_background"))
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
    return {"screen": "unavailable", "title": "WLAN Pi", "blocks": blocks, "hints": {}}
