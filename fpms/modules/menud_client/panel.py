"""The panel: buttons in, screen out, wlanpi-menud in between.

Runs on one asyncio loop. Button threads hand keys over with ``press()``;
frames from the service and key presses both end in a redraw.

What stays local, because it is about this piece of hardware and not the
menu:

* key2 rotates the display (the service ignores key2 for that reason);
* the screen sleeps after a while and the first press only wakes it;
* scrolling inside a screen taller than the display;
* editing string and form prompts (see editor.py);
* the screen shown while the service cannot be reached.

Everything else is an ``input`` frame.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from . import netinfo, protocol, render
from .client import MenudClient
from .editor import PromptEditor

log = logging.getLogger(__name__)

SCROLL_STEP = render.ROW_H * 3
TICK_SEC = 1.0


def read_eth_carrier() -> int | None:
    try:
        with open("/sys/class/net/eth0/carrier") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


class Panel:
    def __init__(
        self,
        screen: Any,
        *,
        socket_path: str,
        version: str,
        keys: list[str],
        on_rotate: Callable[[], None] | None = None,
        sleep_after: float = 600.0,
        carrier_reader: Callable[[], int | None] = read_eth_carrier,
        backoff_min: float = 0.5,
        backoff_max: float = 8.0,
    ):
        """``screen`` needs drawImage(image), sleep(), wakeup() and render_text(title, lines)."""
        self.screen = screen
        self.keys = list(keys)
        self.on_rotate = on_rotate
        self.sleep_after = sleep_after
        self.carrier_reader = carrier_reader
        self.client = MenudClient(
            socket_path,
            version=version,
            capabilities=protocol.capabilities(
                width_px=render.PAGE_WIDTH,
                height_px=render.PAGE_HEIGHT,
                cols=render.COLS,
                rows=render.ROWS,
                keys=self.keys,
            ),
            on_change=self._changed,
            backoff_min=backoff_min,
            backoff_max=backoff_max,
        )
        self.editor: PromptEditor | None = None
        self.scroll = 0
        self.max_scroll = 0
        self.asleep = False
        self.last_frame: render.Frame | None = None
        self._view_key: tuple[Any, ...] | None = None
        self._page_index: int | None = None
        self._scroll_to_end = False
        self._drawn: bytes | None = None
        self._tick = 0
        self._last_activity = time.monotonic()
        self._carrier: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._dirty = asyncio.Event()
        self._keys: asyncio.Queue[str] = asyncio.Queue()
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ entry points

    def press(self, key: str) -> None:
        """A button was pressed. Safe to call from any thread."""
        loop = self._loop
        if loop is not None and key in self.keys:
            loop.call_soon_threadsafe(self._keys.put_nowait, key)

    def stop(self) -> None:
        """Stop run(). Safe to call from any thread."""
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._stop.set)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._dirty.set()
        tasks = [
            asyncio.create_task(self.client.run()),
            asyncio.create_task(self._key_loop()),
            asyncio.create_task(self._draw_loop()),
            asyncio.create_task(self._tick_loop()),
        ]
        try:
            await self._stop.wait()
        finally:
            self.client.stop()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------ state changes

    def _changed(self) -> None:
        """The client's state changed (a frame arrived or the connection moved)."""
        view = self.client.view
        key = None
        if view is not None:
            page = (view.get("page") or {}).get("index")
            key = (view.get("screen"), view.get("node"), view.get("job_id"), page)
            if key != self._view_key:
                # A different screen starts at the top; the previous page of
                # the same result is entered from its end.
                same_result = (
                    self._view_key is not None and key[:3] == self._view_key[:3]
                )
                went_back = (
                    same_result and page is not None and (self._page_index or 0) > page
                )
                self.scroll = 0
                self._scroll_to_end = bool(went_back)
                if self.asleep and not (view.get("driven_by") or {}).get("self", True):
                    self._wake()  # someone is driving the screen from elsewhere
                if not same_result:
                    self.client.clear_notice()
            self._page_index = page
        elif self._view_key is not None:
            self.scroll = (
                0  # the connection went away: the local screen starts at the top
            )
        self._view_key = key
        self._sync_editor()
        self._dirty.set()

    def _sync_editor(self) -> None:
        """Open the local editor for a string or form prompt, drop it when the prompt is gone."""
        view = self.client.view
        prompt = self.client.prompt_for_view()
        wanted = (
            prompt is not None
            and prompt.get("kind") in ("string", "form")
            and (view or {}).get("answerable", True)
        )
        if not wanted:
            self.editor = None
        elif prompt is not None and (
            self.editor is None or self.editor.prompt_id != str(prompt["prompt_id"])
        ):
            self.editor = PromptEditor(prompt)

    def _wake(self) -> None:
        self._last_activity = time.monotonic()
        if self.asleep:
            self.asleep = False
            self.screen.wakeup()
            self._drawn = None
            self._dirty.set()

    # ------------------------------------------------------------------ keys

    async def _key_loop(self) -> None:
        while True:
            key = await self._keys.get()
            try:
                await self.handle_key(key)
            except Exception:
                log.exception("key %s failed", key)

    async def handle_key(self, key: str) -> None:
        if self.asleep:
            self._wake()  # the first press only wakes the screen
            return
        self._last_activity = time.monotonic()
        client = self.client
        string_edit = (
            self.editor is not None
            and self.editor.editing is not None
            and self.editor.editing["type"] == "string"
        )
        if key == "key2" and not string_edit:
            if self.on_rotate is not None:
                self.on_rotate()
                self._drawn = None
                self._dirty.set()
            return
        if not client.connected or client.view is None:
            client.retry_now()
            if key in ("up", "down"):
                # The address list can be longer than the screen.
                step = SCROLL_STEP if key == "down" else -SCROLL_STEP
                self.scroll = max(0, min(self.scroll + step, self.max_scroll))
                self._dirty.set()
            return
        view = client.view
        screen = view.get("screen")

        if screen == "prompt":
            if view.get("answerable") is False:
                who = (client.prompt_for_view() or {}).get("invoked_by", {}).get("name")
                client.set_notice(f"Only {who or 'the invoker'} can answer this")
                self._dirty.set()
                return
            if self.editor is not None:
                action, payload = self.editor.handle(key)
                if action == "answer":
                    await client.send_answer(self.editor.prompt_id, **payload)
                self._dirty.set()
                return
            await client.send_input(key)
            return

        if screen == "busy" and key == "left" and view.get("job_id"):
            await client.send_cancel(view["job_id"])
            return

        if key in ("up", "down") and screen != "menu":
            if self._dirty.is_set():
                # A frame arrived and is not drawn yet: measure the screen the
                # key is meant for, not the one it replaced.
                self._dirty.clear()
                self.draw()
            if await self._scroll_or_page(key, view):
                return
        await client.send_input(key)

    async def _scroll_or_page(self, key: str, view: dict[str, Any]) -> bool:
        """Scroll inside the screen, or page at its ends. False: the key goes to the service."""
        client = self.client
        if key == "down" and self.scroll < self.max_scroll:
            self.scroll = min(self.scroll + SCROLL_STEP, self.max_scroll)
        elif key == "up" and self.scroll > 0:
            self.scroll = max(self.scroll - SCROLL_STEP, 0)
        elif key == "up" and client.fetched_index >= 0:
            client.fetched_index -= 1
            self._scroll_to_end = True
        elif key == "down" and client.fetched_index + 1 < len(client.fetched_pages):
            client.fetched_index += 1
            self.scroll = 0
        elif key == "down" and view.get("screen") == "result" and not view.get("page"):
            # The view has no server-side paging: fetch the next page of the
            # job result by cursor with a page frame.
            job_id = view.get("job_id")
            if client.fetched_index >= 0:
                cursor = client.fetched_pages[client.fetched_index].get("cursor")
            else:
                cursor = (
                    (client.jobs.get(job_id or "") or {}).get("result") or {}
                ).get("cursor")
            if not (job_id and cursor):
                return False
            await client.send_page(job_id, cursor)
            self.scroll = 0
            return True
        else:
            return False
        self._dirty.set()
        return True

    # ------------------------------------------------------------------ drawing

    def _badge(self, screen: str | None) -> str | None:
        if screen not in ("home", "menu"):
            return None
        jobs = self.client.topic("jobs")
        if jobs:
            return f"{len(jobs)} job" + ("s" if len(jobs) > 1 else "")
        return None

    def compose(self) -> render.Frame:
        """The frame for the current state."""
        client = self.client
        view = client.view
        if not client.connected or view is None:
            self.editor = None
            local = render.unavailable_view(
                netinfo.ipv4_addresses(),
                netinfo.hostname(),
                failures=client.failures,
                reason=client.last_failure,
            )
            frame = render.render(local, scroll=self.scroll)
        else:
            shown = dict(view)
            if self.editor is not None:
                shown.update(self.editor.view())
            elif client.fetched_index >= 0:
                result = client.fetched_pages[client.fetched_index]
                shown["blocks"] = result.get("blocks", [])
                if result.get("title"):
                    shown["title"] = result["title"]
            comps = (
                client.topic("complications") if view.get("screen") == "home" else None
            )
            frame = render.render(
                shown,
                scroll=self.scroll,
                notice=client.notice,
                badge=self._badge(view.get("screen")),
                tick=self._tick,
                complications=comps or None,
            )
        self.max_scroll = frame.max_scroll
        if self._scroll_to_end and frame.max_scroll:
            self._scroll_to_end = False
            self.scroll = frame.max_scroll
            return self.compose()
        self._scroll_to_end = False
        self.scroll = frame.scroll
        return frame

    def draw(self) -> None:
        frame = self.compose()
        self.last_frame = frame
        if self.asleep:
            return
        data = frame.image.tobytes()
        if data == self._drawn:
            return  # nothing changed on screen: skip the SPI write
        self._drawn = data
        self.screen.drawImage(frame.image)
        self.screen.render_text(frame.title, frame.lines)

    async def _draw_loop(self) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            try:
                self.draw()
            except Exception:
                log.exception("draw failed")
            await asyncio.sleep(0.02)  # coalesce bursts of frames

    async def _tick_loop(self) -> None:
        """Once a second: animation, notice expiry, link changes and screen sleep."""
        had_notice = False
        while True:
            await asyncio.sleep(TICK_SEC)
            self._tick += 1
            carrier = self.carrier_reader()
            if carrier != self._carrier:
                if self._carrier is not None:
                    self._wake()  # cable plugged or pulled
                self._carrier = carrier
            if self.asleep:
                continue
            if time.monotonic() - self._last_activity >= self.sleep_after:
                self.asleep = True
                self.screen.sleep()
                continue
            notice = self.client.notice is not None
            view = self.client.view
            animated = view is not None and view.get("screen") == "busy"
            if animated or notice != had_notice or not self.client.connected:
                self._dirty.set()
            had_notice = notice
