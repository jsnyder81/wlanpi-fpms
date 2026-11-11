"""A scripted stand-in for wlanpi-menud on a Unix socket.

It speaks enough of protocol v1 for a thin client on the default session:
hello/welcome with epoch and resume, menu, view, subscribe snapshots. What
it answers to input, answer, cancel and page frames is scripted per test.
Every frame in either direction is validated against the frames.schema.json
vendored from wlanpi-menud, and written to a transcript.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from websockets.asyncio.server import ServerConnection, unix_serve
from websockets.exceptions import ConnectionClosed

SCHEMA_PATH = Path(__file__).parent / "fixtures" / "frames.schema.json"
VALIDATOR = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
C2S = {
    "hello",
    "subscribe",
    "unsubscribe",
    "input",
    "invoke",
    "answer",
    "page",
    "cancel",
    "nav",
}

HOME_VIEW = {
    "screen": "home",
    "node": None,
    "title": "WLAN Pi",
    "blocks": [
        {
            "type": "kv",
            "text": "Host: wlanpi-test\nIP: 192.0.2.10",
            "items": [
                {"key": "Host", "value": "wlanpi-test"},
                {"key": "IP", "value": "192.0.2.10"},
            ],
        }
    ],
    "hints": {"down": "Menu"},
}

TOPIC_DATA: dict[str, Any] = {
    "device.summary": {
        "hostname": "wlanpi-test",
        "ip": "192.0.2.10",
        "mode": "classic",
    },
    "complications": [],
    "alerts": [],
    "jobs": [],
}

Script = Callable[[dict[str, Any]], "list[dict[str, Any]] | None"]


def schema_errors(frame: dict[str, Any]) -> list[str]:
    return [f"{list(e.path)}: {e.message}" for e in VALIDATOR.iter_errors(frame)]


class FakeMenud:
    def __init__(self, path: str, *, epoch: str = "epochAAAA0001"):
        self.path = path
        self.epoch = epoch
        self.session_id = "Sdefault0001"
        self.menu_revision = 1
        self.view: dict[str, Any] = dict(HOME_VIEW)
        self.topic_data = dict(TOPIC_DATA.items())
        self.seq = dict.fromkeys(self.topic_data, 1)
        self.pending_prompts: list[dict[str, Any]] = []
        self.script: Script | None = None
        self.refuse_hello: dict[str, Any] | None = None  # error fields; then close

        self.received: list[dict[str, Any]] = []
        self.transcript: list[str] = []
        self.violations: list[str] = []
        self.connections: list[ServerConnection] = []
        self.subscriptions: dict[ServerConnection, set[str]] = {}
        self.hellos = 0
        self._server: Any = None
        self._sid = 0
        self._arrived = asyncio.Condition()

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self._server = await unix_serve(self._serve, self.path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.connections.clear()

    async def restart(self, *, epoch: str | None = None) -> None:
        """Stop and start again; a new epoch models a service restart."""
        await self.stop()
        if epoch:
            self.epoch = epoch
            self.seq = dict.fromkeys(self.topic_data, 1)
        await self.start()

    async def drop_connections(self, code: int = 1001) -> None:
        for ws in list(self.connections):
            await ws.close(code, "going away")

    # ------------------------------------------------------------------ frames

    def _log(self, arrow: str, frame: dict[str, Any]) -> None:
        self.transcript.append(f"{arrow} {json.dumps(frame, separators=(',', ':'))}")
        for err in schema_errors(frame):
            self.violations.append(f"{arrow} {frame.get('type')}: {err}")

    def _next_sid(self) -> str:
        self._sid += 1
        return f"s:{self._sid}"

    async def _send(
        self, ws: ServerConnection, body: dict[str, Any], msg_id: str | None = None
    ) -> None:
        frame = {"v": 1, **body}
        frame.setdefault("id", msg_id or self._next_sid())
        frame = {
            "v": 1,
            "type": frame["type"],
            "id": frame["id"],
            **{k: v for k, v in frame.items() if k not in ("v", "type", "id")},
        }
        self._log("S>", frame)
        try:
            await ws.send(json.dumps(frame))
        except ConnectionClosed:
            pass

    async def push(self, body: dict[str, Any]) -> None:
        """An unprompted server frame (s: id) to every connection."""
        if body.get("type") == "view":
            self.view = {k: v for k, v in body.items() if k != "type"}
        for ws in list(self.connections):
            await self._send(ws, body)

    async def publish(self, topic: str, data: Any, *, skip_seq: int = 0) -> None:
        """A topic change. ``skip_seq`` leaves a gap, as a dropped update would."""
        self.topic_data[topic] = data
        self.seq[topic] += 1 + skip_seq
        for ws in list(self.connections):
            if topic in self.subscriptions.get(ws, ()):
                await self._send(
                    ws,
                    {
                        "type": "event",
                        "topic": topic,
                        "seq": self.seq[topic],
                        "data": data,
                    },
                )

    def _event(self, topic: str) -> dict[str, Any]:
        return {
            "type": "event",
            "topic": topic,
            "seq": self.seq[topic],
            "snapshot": True,
            "data": self.topic_data[topic],
        }

    def view_frame(self) -> dict[str, Any]:
        return {"type": "view", **self.view}

    # ------------------------------------------------------------------ serving

    async def _serve(self, ws: ServerConnection) -> None:
        self.connections.append(ws)
        self.subscriptions[ws] = set()
        self.transcript.append("-- connection opened")
        try:
            async for raw in ws:
                frame = json.loads(raw)
                self._log("C>", frame)
                if frame.get("type") not in C2S:
                    self.violations.append(
                        f"C> unexpected frame type {frame.get('type')}"
                    )
                await self._handle(ws, frame)
                async with self._arrived:
                    self.received.append(frame)
                    self._arrived.notify_all()
        except ConnectionClosed:
            pass
        finally:
            self.transcript.append("-- connection closed")
            if ws in self.connections:
                self.connections.remove(ws)
            self.subscriptions.pop(ws, None)

    async def _handle(self, ws: ServerConnection, frame: dict[str, Any]) -> None:
        kind, mid = frame.get("type"), frame.get("id")
        if kind == "hello":
            await self._hello(ws, frame)
        elif kind == "subscribe":
            for topic in frame["topics"]:
                if topic not in self.subscriptions[ws]:
                    self.subscriptions[ws].add(topic)
                    await self._send(ws, self._event(topic), mid)
        elif kind == "unsubscribe":
            self.subscriptions[ws].difference_update(frame["topics"])
        else:
            replies = self.script(frame) if self.script else None
            if replies is None:
                replies = [self.view_frame()]
            for body in replies:
                if body.get("type") == "view":
                    self.view = {
                        k: v for k, v in body.items() if k not in ("type", "id")
                    }
                await self._send(
                    ws, body, None if str(body.get("id", "")).startswith("s:") else mid
                )

    async def _hello(self, ws: ServerConnection, frame: dict[str, Any]) -> None:
        self.hellos += 1
        mid = frame["id"]
        if self.refuse_hello is not None:
            await self._send(ws, {"type": "error", **self.refuse_hello}, mid)
            await ws.close(self.refuse_hello.get("close_code", 1000), "refused")
            return
        resume = frame.get("resume") or {}
        seqs = resume.get("seq", {})
        same = (
            resume.get("epoch") == self.epoch
            and resume.get("session_id") == self.session_id
        )
        resumed = same and all(self.seq.get(t) == n for t, n in seqs.items())
        if same:
            self.subscriptions[ws] = set(seqs)
        await self._send(
            ws,
            {
                "type": "welcome",
                "session_id": self.session_id,
                "session": "default",
                "epoch": self.epoch,
                "principal": {"kind": "local", "name": "root", "uid": 0},
                "roles": ["admin"],
                "version": 1,
                "mode": "thin",
                "resumed": resumed,
                "limits": {"queue_frames": 64, "max_frame_bytes": 262144},
            },
            mid,
        )
        if not resumed or resume.get("menu_revision") != self.menu_revision:
            await self._send(
                ws,
                {
                    "type": "menu",
                    "revision": self.menu_revision,
                    "device_mode": "classic",
                    "nodes": [],
                },
            )
        if not resumed:
            for topic in sorted(self.subscriptions[ws]):
                await self._send(ws, self._event(topic))
            for prompt in self.pending_prompts:
                await self._send(ws, prompt)
        await self._send(ws, self.view_frame())

    # ------------------------------------------------------------------ test helpers

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [f for f in self.received if f.get("type") == kind]

    async def wait_for(
        self, kind: str, count: int = 1, timeout: float = 3.0
    ) -> list[dict[str, Any]]:
        """Wait until ``count`` frames of ``kind`` have arrived; return them all."""
        async with self._arrived:
            await asyncio.wait_for(
                self._arrived.wait_for(lambda: len(self.of_type(kind)) >= count),
                timeout,
            )
        return self.of_type(kind)
