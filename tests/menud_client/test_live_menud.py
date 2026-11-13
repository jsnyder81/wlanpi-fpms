"""The panel against the real wlanpi-menud service (on its fake core).

Runs wlanpi-menud's demo/serve_fake.py from a sibling checkout with that
checkout's own virtualenv. Skipped when it is not there (CI for this repo
alone): the scripted fake in test_panel.py covers the same ground offline.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path

import pytest
from conftest import ALL_KEYS, until

from fpms.modules.menud_client.panel import Panel
from fpms.modules.screen.virtual import Virtual

MENUD = Path(__file__).parents[3] / "wlanpi-menud"
PYTHON = MENUD / ".venv" / "bin" / "python"
SERVE = MENUD / "demo" / "serve_fake.py"

pytestmark = pytest.mark.skipif(
    not (PYTHON.exists() and SERVE.exists()),
    reason="needs a wlanpi-menud checkout with a .venv next to this repo",
)


@pytest.fixture
def menud_socket():
    with tempfile.TemporaryDirectory(prefix="fpmslive") as tmp:
        proc = subprocess.Popen(
            [str(PYTHON), str(SERVE), tmp],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=tmp,
        )
        try:
            ready = proc.stdout.readline().split()
            assert ready[:1] == ["READY"], ready
            yield ready[1]
        finally:
            proc.terminate()
            proc.wait(10)


def test_navigate_run_and_confirm_against_the_real_service(menud_socket):
    async def scenario():
        screen = Virtual()
        panel = Panel(
            screen,
            socket_path=menud_socket,
            version="0.0.test",
            keys=ALL_KEYS,
            carrier_reader=lambda: None,
        )
        task = asyncio.create_task(panel.run())
        client = panel.client

        async def press(key, screen_name, node=...):
            await panel.handle_key(key)
            await until(
                lambda: (
                    client.view is not None
                    and client.view["screen"] == screen_name
                    and (node is ... or client.view.get("node") == node)
                ),
                what=f"{screen_name} {node} after {key}",
            )
            await asyncio.sleep(0.06)
            await until(lambda: not panel._dirty.is_set(), what="draw")
            return panel.last_frame.lines

        try:
            await until(
                lambda: client.connected and client.view is not None, what="attach"
            )
            assert client.resumed is False
            assert client.roles == ["admin"]
            assert client.view["screen"] == "home"
            await until(lambda: len(client.topic_seq) == 4, what="topic snapshots")

            lines = await press("down", "menu", "network")
            assert lines[0] == "> Network >"
            lines = await press("down", "menu", "bluetooth")
            assert lines[:2] == ["  Network >", "> Bluetooth >"]
            await press("up", "menu", "network")
            lines = await press("center", "menu", "network.interfaces")
            assert lines[0] == "> Interfaces"

            # Run an action: a table result, drawn on the virtual screen.
            lines = await press("center", "result", "network.interfaces")
            assert lines[0].startswith("Section")
            assert any("eth0" in line for line in lines)
            assert client.view["driven_by"]["self"] is True
            assert client.view["driven_by"]["surface"] == "wlanpi-fpms"
            await press("left", "menu", "network.interfaces")

            # key1 is the FPMS shortcut cycle, key3 the shutdown/reboot confirm.
            await press("key1", "result", "utils.reachability")
            lines = await press("key3", "prompt", "system.shutdown")
            assert lines[-2] == "[Cancel]  Confirm "
            lines = await press("down", "prompt", "system.shutdown")
            assert lines[-2] == " Cancel  [Confirm]"
            lines = await press(
                "left", "result", "system.shutdown"
            )  # cancel, not confirm
            assert lines[0] == "[info] Cancelled"

            # Back to the top; home is the service's view of the device.
            await press("left", "menu", "system.shutdown")
            await press("left", "menu", "system")
            lines = await press("left", "home")
            assert lines[0].startswith(("Host:", "Mode:"))
            assert screen.last_image.tobytes() == panel.last_frame.image.tobytes()
        finally:
            panel.stop()
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())


def test_reconnect_resumes_against_the_real_service(menud_socket):
    async def scenario():
        panel = Panel(
            Virtual(),
            socket_path=menud_socket,
            version="0.0.test",
            keys=ALL_KEYS,
            carrier_reader=lambda: None,
            backoff_min=0.05,
        )
        task = asyncio.create_task(panel.run())
        client = panel.client
        try:
            await until(
                lambda: client.connected and len(client.topic_seq) == 4, what="attach"
            )
            epoch, session = client.epoch, client.session_id
            await panel.handle_key("down")
            await until(lambda: client.view["screen"] == "menu", what="menu")

            await (
                client._ws.close()
            )  # the connection drops; the service keeps the session
            await until(lambda: client.failures == 1, what="drop noticed")
            await until(
                lambda: client.connected and client.view is not None, what="reattach"
            )
            assert client.resumed is True
            assert (client.epoch, client.session_id) == (epoch, session)
            # The default session's cursor lives in the service: still on the menu.
            assert client.view["screen"] == "menu"
        finally:
            panel.stop()
            await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
