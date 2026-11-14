"""Connection to wlanpi-menud and the state its frames describe.

One WebSocket over the local Unix socket, kept up with reconnect, backoff and
``hello.resume``. The client holds no menu logic: it stores the latest
``view``, open prompts, job frames and topic data, and tells the panel when
something changed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Callable
from typing import Any

from websockets.asyncio.client import unix_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from . import protocol

log = logging.getLogger(__name__)

MAX_TRACKED_JOBS = 16
MAX_CACHED_PAGES = 4
NOTICE_SEC = 4.0


class MenudClient:
    def __init__(
        self,
        socket_path: str,
        *,
        version: str,
        capabilities: dict[str, Any],
        on_change: Callable[[], None] | None = None,
        topics: list[str] | None = None,
        backoff_min: float = 0.5,
        backoff_max: float = 8.0,
        open_timeout: float = 5.0,
    ):
        self.socket_path = socket_path
        self.version = version
        self.capabilities = capabilities
        self.on_change = on_change or (lambda: None)
        self.topics = list(topics if topics is not None else protocol.TOPICS)
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self.open_timeout = open_timeout

        # Connection.
        self.connected = False  # welcome received on the current connection
        self.failures = 0  # consecutive failed or dropped connections
        self.last_failure: str | None = None
        self._ws: Any = None
        self._stopping = False
        self._retry_now = asyncio.Event()
        self._msg_counter = 0

        # Session, kept across reconnects for hello.resume.
        self.epoch: str | None = None
        self.session_id: str | None = None
        self.principal: dict[str, Any] | None = None
        self.roles: list[str] = []
        self.features: list[str] = []
        self.resumed: bool | None = None
        self.menu_revision: int | None = None
        self.device_mode: str | None = None

        # What the service is showing.
        self.view: dict[str, Any] | None = None
        self.prompts: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        # Result pages fetched with page frames, for a result view that
        # carries no server-side paging (see Panel._page_down).
        self.fetched_pages: list[dict[str, Any]] = []
        self.fetched_index = -1  # -1: showing the view's own blocks
        self._page_requests: set[str] = set()

        # Topics.
        self.topic_seq: dict[str, int] = {}
        self.topic_data: dict[str, Any] = {}
        self.stale_topics: set[str] = set()

        self.last_error: dict[str, Any] | None = None
        self._notice: tuple[str, float] | None = None

    # ------------------------------------------------------------------ helpers

    def next_id(self) -> str:
        self._msg_counter += 1
        return f"p{self._msg_counter}"

    @property
    def notice(self) -> str | None:
        """A short message to overlay (a refused request), until it times out."""
        if self._notice and self._notice[1] > time.monotonic():
            return self._notice[0]
        return None

    def set_notice(self, text: str, seconds: float = NOTICE_SEC) -> None:
        self._notice = (text, time.monotonic() + seconds)

    def clear_notice(self) -> None:
        self._notice = None

    def has_feature(self, feature: str) -> bool:
        """Whether the server announced support for this protocol feature."""
        return feature in self.features

    def topic(self, name: str) -> Any:
        """Current data for a topic, or None while it is unknown or stale."""
        if name in self.stale_topics:
            return None
        return self.topic_data.get(name)

    def prompt_for_view(self) -> dict[str, Any] | None:
        """The prompt frame behind the current prompt screen, when known."""
        view = self.view
        if not view or view.get("screen") != "prompt":
            return None
        for block in view.get("blocks", []):
            if (
                block.get("type") == "confirm"
                and block.get("prompt_id") in self.prompts
            ):
                return self.prompts[block["prompt_id"]]
        job_id = view.get("job_id")
        for frame in reversed(list(self.prompts.values())):
            if job_id is None or frame.get("job_id") == job_id:
                return frame
        return None

    # ------------------------------------------------------------------ sending

    async def send(self, frame: dict[str, Any]) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(json.dumps(frame, separators=(",", ":")))
            return True
        except (WebSocketException, OSError):
            log.debug("send %s failed", frame.get("type"), exc_info=True)
            return False

    async def send_input(self, key: str) -> bool:
        return await self.send(protocol.input_frame(self.next_id(), key))

    async def send_cancel(self, job_id: str) -> bool:
        return await self.send(protocol.cancel(self.next_id(), job_id))

    async def send_answer(self, prompt_id: str, **one: Any) -> bool:
        return await self.send(protocol.answer(self.next_id(), prompt_id, **one))

    async def send_page(self, job_id: str, cursor: str) -> bool:
        msg_id = self.next_id()
        self._page_requests.add(msg_id)
        return await self.send(protocol.page(msg_id, job_id, cursor))

    # ------------------------------------------------------------------ connection

    def retry_now(self) -> None:
        """Skip the rest of the current backoff wait (a button was pressed)."""
        self._retry_now.set()

    def stop(self) -> None:
        self._stopping = True
        self._retry_now.set()

    def _resume_payload(self) -> dict[str, Any] | None:
        if not self.epoch:
            return None
        return protocol.resume(
            self.epoch, self.session_id, self.topic_seq, self.menu_revision
        )

    async def run(self) -> None:
        """Connect, serve frames, reconnect with backoff. Returns after stop()."""
        delay = self.backoff_min
        while not self._stopping:
            reason = "connection closed"
            floor = 0.0
            welcomed = False
            try:
                async with unix_connect(
                    path=self.socket_path,
                    uri="ws://localhost/ws",
                    open_timeout=self.open_timeout,
                ) as ws:
                    self._ws = ws
                    resume = self._resume_payload()
                    await self.send(
                        protocol.hello(
                            self.next_id(),
                            version=self.version,
                            capabilities=self.capabilities,
                            resume=resume,
                        )
                    )
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", "replace")
                        try:
                            frame = json.loads(raw)
                        except ValueError:
                            log.warning("dropping a frame that is not JSON")
                            continue
                        if not isinstance(frame, dict):
                            continue
                        await self._handle(frame, resume)
                        welcomed = welcomed or self.connected
                        self.on_change()
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
                reason = (exc.rcvd.reason if exc.rcvd else "") or f"closed ({code})"
                if code in protocol.FATAL_CLOSE_CODES:
                    floor = self.backoff_max
                elif code == protocol.CLOSE_RETRY_LATER:
                    floor = min(2.0, self.backoff_max)
            except asyncio.CancelledError:
                raise
            except (OSError, WebSocketException, TimeoutError, ValueError) as exc:
                reason = str(exc) or type(exc).__name__
            finally:
                self._ws = None
                self.connected = False

            if self._stopping:
                break
            err = self.last_error
            if err and err.get("fatal"):
                reason = f"{err.get('code')}: {err.get('message')}"
                floor = self.backoff_max
            elif err and err.get("retry_after_sec"):
                floor = max(floor, float(err["retry_after_sec"]))
            self.last_error = None
            if welcomed:
                delay = self.backoff_min
            self.failures += 1
            self.last_failure = reason
            self.view = None
            self.fetched_pages = []
            self.fetched_index = -1
            self._page_requests.clear()
            log.info("wlanpi-menud unavailable (%s)", reason)
            self.on_change()

            wait = max(delay, floor) * random.uniform(0.9, 1.1)
            self._retry_now.clear()
            try:
                await asyncio.wait_for(self._retry_now.wait(), wait)
            except TimeoutError:
                pass
            delay = min(delay * 2, self.backoff_max)

    # ------------------------------------------------------------------ frames

    async def _handle(
        self, frame: dict[str, Any], resume: dict[str, Any] | None
    ) -> None:
        kind = frame.get("type")
        if kind == "welcome":
            await self._welcome(frame, resume)
        elif kind == "menu":
            # Thin mode: the tree itself is the service's; only the revision is
            # kept, for hello.resume.
            self.menu_revision = frame.get("revision")
            self.device_mode = frame.get("device_mode")
        elif kind == "view":
            self.view = frame
            # The view is the authority on what is shown: locally fetched
            # pages belong to the screen it replaces.
            self.fetched_pages = []
            self.fetched_index = -1
            if frame.get("screen") != "prompt":
                self.prompts.clear()
        elif kind == "prompt":
            self.prompts[str(frame.get("prompt_id"))] = frame
        elif kind == "job":
            self._job(frame)
        elif kind == "event":
            self._event(frame)
        elif kind == "error":
            self.last_error = frame
            self.set_notice(f"{frame.get('code')}: {frame.get('message')}")
            log.warning("menud error %s: %s", frame.get("code"), frame.get("message"))

    async def _welcome(
        self, frame: dict[str, Any], resume: dict[str, Any] | None
    ) -> None:
        if self.epoch and frame.get("epoch") != self.epoch:
            # The service restarted: nothing held from the old epoch is current.
            self.topic_seq.clear()
            self.topic_data.clear()
            self.stale_topics.clear()
            self.jobs.clear()
            self.prompts.clear()
            self.menu_revision = None
            resume = None
        self.epoch = frame.get("epoch")
        self.session_id = frame.get("session_id")
        self.principal = frame.get("principal")
        self.roles = list(frame.get("roles", []))
        self.features = [str(f) for f in frame.get("features", [])]
        self.resumed = bool(frame.get("resumed", False))
        self.connected = True
        self.failures = 0
        self.last_failure = None
        # Add additive topics when advertised by welcome.features (§5.1)
        if protocol.FEATURE_COMPLICATIONS in self.features:
            for t in protocol.NEW_TOPICS:
                if t not in self.topics:
                    self.topics.append(t)
        # Topics listed in resume.seq are subscribed again by the service
        # (snapshots follow when not resumed). Anything else is asked for.
        carried = set((resume or {}).get("seq", {}))
        missing = [t for t in self.topics if t not in carried]
        if missing:
            await self.send(protocol.subscribe(self.next_id(), missing))

    def _job(self, frame: dict[str, Any]) -> None:
        job_id = str(frame.get("job_id"))
        if str(frame.get("id")) in self._page_requests:
            self._page_requests.discard(str(frame.get("id")))
            if frame.get("state") == "result":
                self.fetched_pages.append(frame.get("result") or {"blocks": []})
                del self.fetched_pages[:-MAX_CACHED_PAGES]
                self.fetched_index = len(self.fetched_pages) - 1
            return
        self.jobs.pop(job_id, None)
        self.jobs[job_id] = frame
        while len(self.jobs) > MAX_TRACKED_JOBS:
            self.jobs.pop(next(iter(self.jobs)))

    def _event(self, frame: dict[str, Any]) -> None:
        topic = str(frame.get("topic"))
        seq = int(frame.get("seq", 0))
        prev = self.topic_seq.get(topic)
        if frame.get("snapshot") or prev is None:
            self.stale_topics.discard(topic)
        elif seq != prev + 1:
            # A gap without a snapshot: stale until the next snapshot.
            self.stale_topics.add(topic)
        self.topic_seq[topic] = seq
        self.topic_data[topic] = frame.get("data")
