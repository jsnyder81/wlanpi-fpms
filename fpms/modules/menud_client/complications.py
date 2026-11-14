"""Complications resolution and display for the front panel (spec §2.6, §4, §5).

The service announces ``complications.2`` in ``welcome.features``. Only then
does the panel subscribe to ``complications.live``, ``.catalog`` and ``.config``
and draw its status strip from the ``panel.strip`` profile; against an older
service the strip falls back to the legacy ``complications`` topic.

The user's profile decides which tiles and in what order; the panel decides how
many fit (§4.5: floor((cols - 5) / 5) = 3 slots on a 21-column micro-display).
Overflow is cut from the end and never reordered.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

FEATURE = "complications.2"
PROFILE_STRIP = "panel.strip"
PROFILE_PANEL = "panel"
DEFAULT_PROFILE = "default"

TOPIC_LIVE = "complications.live"
TOPIC_CATALOG = "complications.catalog"
TOPIC_CONFIG = "complications.config"
TOPICS: tuple[str, ...] = (TOPIC_LIVE, TOPIC_CATALOG, TOPIC_CONFIG)

STRIP_MAX_SLOTS = 3
UNKNOWN_VALUE = "--"

# Shipped defaults (§4.4)
SHIPPED_STRIP_SHOW: tuple[str, ...] = (
    "wlanpi.battery",
    "wlanpi.bluetooth",
    "wlanpi.internet",
)
SHIPPED_PANEL_SHOW: tuple[str, ...] = (
    "wlanpi.mode",
    "wlanpi.ip",
    "wlanpi.wifi",
    "wlanpi.cpu_temp",
    "wlanpi.hotspot_clients",
    "plugin.*",
    "local.*",
)

# Status vocabulary (§2.6)
VALID_STATUSES = frozenset({"ok", "info", "warn", "error", "off", "unknown"})


def normalize_status(status: Any) -> str:
    """An unrecognized status is drawn as ``unknown`` (§2.6)."""
    s = str(status or "").lower()
    if s == "warning":  # deprecated alias the service stores as warn
        return "warn"
    return s if s in VALID_STATUSES else "unknown"


def resolve(show: Iterable[str], live_ids: Iterable[str]) -> list[str]:
    """§4.3 resolution, before the capacity cut.

    Walk ``show`` in order; an exact id yields itself if live; a ``.*``
    pattern yields every live id it matches that no exact entry anywhere in
    the list names and that nothing earlier yielded, sorted by id.
    """
    show = list(show)
    live = sorted(set(live_ids))
    exact = {e for e in show if not e.endswith(".*")}
    out: list[str] = []
    seen: set[str] = set()
    for entry in show:
        if entry.endswith(".*"):
            prefix = entry[:-1]
            for i in live:
                if i.startswith(prefix) and i not in exact and i not in seen:
                    out.append(i)
                    seen.add(i)
        elif entry in live and entry not in seen:
            out.append(entry)
            seen.add(entry)
    return out


def show_for(config: Any, profile: str = PROFILE_STRIP) -> list[str]:
    """The profile's show list from ``complications.config`` data, falling back
    to the service's ``default`` profile, then the shipped default list."""
    surfaces = config.get("surfaces") if isinstance(config, dict) else None
    if isinstance(surfaces, dict):
        for name in (profile, DEFAULT_PROFILE):
            body = surfaces.get(name)
            if isinstance(body, dict) and isinstance(body.get("show"), list):
                return [str(e) for e in body["show"]]
    fallback = SHIPPED_STRIP_SHOW if profile == PROFILE_STRIP else SHIPPED_PANEL_SHOW
    return list(fallback)


def resolved_tiles(
    live: Any, config: Any, profile: str = PROFILE_STRIP
) -> list[dict[str, Any]]:
    """Live records the profile selects, in profile order (not yet cut)."""
    if not isinstance(live, list):
        return []
    by_id = {
        str(r["app_id"]): r for r in live if isinstance(r, dict) and r.get("app_id")
    }
    return [by_id[i] for i in resolve(show_for(config, profile), by_id)]


def slot_text(tile: dict[str, Any]) -> str:
    """1 to 4 character compact text form for a strip slot (§2.2, §2.7).

    A strip slot is 4 characters. Without ``short`` it shows the first 4
    characters of ``value``. If status is ``unknown`` it shows ``--``.
    Any glyph the font lacks becomes ``?``.
    """
    status = normalize_status(tile["status"]) if "status" in tile else "info"
    if status == "unknown":
        raw = UNKNOWN_VALUE
    elif tile.get("short"):
        raw = str(tile["short"])
    elif tile.get("value"):
        raw = str(tile["value"])[:4]
    else:
        raw = str(tile.get("label", ""))[:4]

    # Non-ASCII or unprintable chars replaced with '?' (§2.7, §6.3)
    return "".join(c if 32 <= ord(c) <= 126 else "?" for c in raw)
