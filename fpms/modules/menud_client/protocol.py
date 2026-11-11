"""Protocol v1 frame builders for the panel (client to server frames)."""

from __future__ import annotations

from typing import Any

PROTOCOL_VERSION = 1
CLIENT_NAME = "wlanpi-fpms"

BLOCK_TYPES = ["text", "kv", "table", "list", "qr", "status", "progress", "confirm"]
KEYS = ["up", "down", "left", "right", "center", "key1", "key2", "key3"]
TOPICS = ["device.summary", "complications", "alerts", "jobs"]

# After these the same hello would be refused again. The panel still retries
# (a package upgrade on either side fixes it) but at the slowest rate.
FATAL_CLOSE_CODES = frozenset({1008, 4400, 4401, 4426})
CLOSE_RETRY_LATER = 1013


def _frame(kind: str, msg_id: str, **fields: Any) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": kind, "id": msg_id, **fields}


def capabilities(
    *,
    width_px: int,
    height_px: int,
    cols: int,
    rows: int,
    keys: list[str],
    colour: str = "colour",
) -> dict[str, Any]:
    return {
        "screen": {
            "width_px": width_px,
            "height_px": height_px,
            "cols": cols,
            "rows": rows,
        },
        "colour": colour,
        "blocks": list(BLOCK_TYPES),
        "keys": [k for k in KEYS if k in keys],
    }


def hello(
    msg_id: str,
    *,
    version: str,
    capabilities: dict[str, Any],
    resume: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Thin hello on the persistent default session: the panel's screen is that session."""
    frame = _frame(
        "hello",
        msg_id,
        mode="thin",
        session="default",
        protocol=[PROTOCOL_VERSION],
        client={"name": CLIENT_NAME, "version": version[:32]},
        capabilities=capabilities,
    )
    if resume:
        frame["resume"] = resume
    return frame


def resume(
    epoch: str,
    session_id: str | None,
    seq: dict[str, int],
    menu_revision: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"epoch": epoch}
    if session_id:
        payload["session_id"] = session_id
    if seq:
        payload["seq"] = dict(seq)
    if menu_revision is not None:
        payload["menu_revision"] = menu_revision
    return payload


def subscribe(msg_id: str, topics: list[str]) -> dict[str, Any]:
    return _frame("subscribe", msg_id, topics=list(topics))


def input_frame(msg_id: str, key: str) -> dict[str, Any]:
    """A button press. ``action`` is left at its default (press): FPMS has no long-press."""
    if key not in KEYS:
        raise ValueError(f"not a panel key: {key!r}")
    return _frame("input", msg_id, key=key)


def answer(msg_id: str, prompt_id: str, **one: Any) -> dict[str, Any]:
    """Exactly one of value, values, confirmed or cancel."""
    if len(one) != 1 or next(iter(one)) not in (
        "value",
        "values",
        "confirmed",
        "cancel",
    ):
        raise ValueError("answer takes exactly one of value, values, confirmed, cancel")
    return _frame("answer", msg_id, prompt_id=prompt_id, **one)


def page(msg_id: str, job_id: str, cursor: str) -> dict[str, Any]:
    return _frame("page", msg_id, job_id=job_id, cursor=cursor)


def cancel(msg_id: str, job_id: str) -> dict[str, Any]:
    return _frame("cancel", msg_id, job_id=job_id)
