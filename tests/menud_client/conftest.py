"""Fixtures for the menud client tests: a fake menud, a panel on a virtual screen."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_menud import FakeMenud

from fpms.modules.menud_client.panel import Panel
from fpms.modules.screen.virtual import Virtual

ALL_KEYS = ["up", "down", "left", "right", "center", "key1", "key2", "key3"]


async def until(condition, timeout: float = 3.0, what: str = "condition"):
    """Poll until ``condition()`` is truthy."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = condition()
        if value:
            return value
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


class Rig:
    """A fake menud and a panel wired to it."""

    def __init__(self, sock: str, request_name: str):
        self.sock = sock
        self.name = request_name
        self.server = FakeMenud(sock)
        self.screen = Virtual()
        self.rotations = 0
        self.panel: Panel | None = None
        self._task: asyncio.Task | None = None

    def make_panel(self, **kwargs) -> Panel:
        def rotate():
            self.rotations += 1

        kwargs.setdefault("keys", ALL_KEYS)
        kwargs.setdefault("backoff_min", 0.05)
        kwargs.setdefault("backoff_max", 0.2)
        kwargs.setdefault("carrier_reader", lambda: None)
        self.panel = Panel(
            self.screen,
            socket_path=self.sock,
            version="0.0.test",
            on_rotate=rotate,
            **kwargs,
        )
        return self.panel

    async def start_panel(self, **kwargs) -> Panel:
        panel = self.make_panel(**kwargs)
        self._task = asyncio.create_task(panel.run())
        return panel

    async def connected(self) -> Panel:
        """Start the panel (if needed) and wait for the first view to be drawn."""
        panel = self.panel or await self.start_panel()
        await until(
            lambda: panel.client.connected and panel.client.view is not None,
            what="welcome and view",
        )
        await self.drawn()
        return panel

    async def drawn(self) -> list[str]:
        """Let pending frames be drawn; return the screen as text lines."""
        panel = self.panel
        assert panel is not None
        await asyncio.sleep(0.06)
        await until(lambda: not panel._dirty.is_set(), what="draw")
        assert panel.last_frame is not None
        return panel.last_frame.lines

    async def press(self, key: str) -> None:
        assert self.panel is not None
        await self.panel.handle_key(key)

    async def close(self) -> None:
        if self.panel is not None and self._task is not None:
            self.panel.stop()
            await asyncio.wait_for(self._task, 3)
        await self.server.stop()
        out = os.environ.get("FPMS_MENUD_TRANSCRIPT")
        if out:
            with open(out, "a") as f:
                f.write(f"\n===== {self.name}\n")
                f.write("\n".join(self.server.transcript) + "\n")
        assert not self.server.violations, "frames broke the schema:\n" + "\n".join(
            self.server.violations
        )


@pytest.fixture
def rig_factory(request):
    """``async with rig_factory() as rig``: fake menud started, everything torn down after."""

    @asynccontextmanager
    async def factory(start_server: bool = True):
        # A short path: AF_UNIX socket paths are limited to about 108 bytes.
        with tempfile.TemporaryDirectory(prefix="fpms") as tmp:
            rig = Rig(os.path.join(tmp, "local.sock"), request.node.name)
            if start_server:
                await rig.server.start()
            try:
                yield rig
            finally:
                await rig.close()

    return factory
