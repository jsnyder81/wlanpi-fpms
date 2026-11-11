"""The panel against a scripted fake menud: frames in, frames out, pixels on a virtual screen."""

from __future__ import annotations

import asyncio
import itertools

from conftest import ALL_KEYS, until
from PIL import ImageColor

from fpms.modules.menud_client import netinfo, render
from fpms.modules.themes import THEME

SELECTED_BG = ImageColor.getrgb(THEME.page_selected_item_background.value)

MENU_VIEW = {
    "type": "view",
    "screen": "menu",
    "node": "network",
    "title": "Menu",
    "blocks": [
        {
            "type": "list",
            "text": "> Network >\n  System >",
            "selected": 0,
            "items": [
                {"label": "Network", "node": "network", "branch": True},
                {"label": "System", "node": "system", "branch": True},
            ],
        }
    ],
    "hints": {"left": "Back", "center": "Select"},
}


def result_view(lines: int, **extra):
    return {
        "type": "view",
        "screen": "result",
        "node": "network.interfaces",
        "title": "Interfaces",
        "job_id": "jab12",
        "blocks": [
            {"type": "text", "text": "\n".join(f"line {i}" for i in range(lines))}
        ],
        "hints": {"left": "Back", "center": "Again"},
        **extra,
    }


def run(coro):
    asyncio.run(coro)


# ---------------------------------------------------------------------- handshake


def test_hello_subscribe_and_first_view(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            hello = rig.server.of_type("hello")[0]
            assert hello["mode"] == "thin"
            assert hello["session"] == "default"
            assert hello["client"]["name"] == "wlanpi-fpms"
            caps = hello["capabilities"]
            assert caps["screen"] == {
                "width_px": 128,
                "height_px": 128,
                "cols": 21,
                "rows": 8,
            }
            assert caps["colour"] == "colour"
            assert sorted(caps["blocks"]) == sorted(
                ["text", "kv", "table", "list", "qr", "status", "progress", "confirm"]
            )
            assert caps["keys"] == ALL_KEYS
            assert "resume" not in hello

            (subscribe,) = await rig.server.wait_for("subscribe")
            assert subscribe["topics"] == [
                "device.summary",
                "complications",
                "alerts",
                "jobs",
            ]
            await until(
                lambda: len(rig.panel.client.topic_seq) == 4, what="four snapshots"
            )
            assert rig.panel.client.topic("device.summary")["hostname"] == "wlanpi-test"

            # The home view the service pushed is on the (virtual) screen.
            assert await rig.drawn() == [
                "Host: wlanpi-test",
                "IP: 192.0.2.10",
                "(▼Menu)",
            ]
            assert rig.screen.last_image.size == (128, 128)
            assert (
                rig.screen.last_image.tobytes() == rig.panel.last_frame.image.tobytes()
            )

    run(scenario())


def test_five_button_device_reports_only_its_keys(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            five = ["up", "down", "left", "right", "center"]
            await rig.start_panel(keys=five)
            await rig.connected()
            assert rig.server.of_type("hello")[0]["capabilities"]["keys"] == five
            rig.panel.press("key1")  # no such button: never reaches the service
            await asyncio.sleep(0.05)
            assert rig.server.of_type("input") == []

    run(scenario())


# ---------------------------------------------------------------------- input


def test_every_key_maps_to_an_input_frame_except_key2(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            for key in ALL_KEYS:
                await rig.press(key)
            inputs = await rig.server.wait_for("input", 7)
            assert [f["key"] for f in inputs] == [
                "up",
                "down",
                "left",
                "right",
                "center",
                "key1",
                "key3",
            ]
            assert all(
                "action" not in f for f in inputs
            )  # press, the default; no long-press
            assert len({f["id"] for f in rig.server.received}) == len(
                rig.server.received
            )
            # key2 rotates the display locally, as on FPMS.
            assert rig.rotations == 1

    run(scenario())


def test_input_reply_view_is_drawn_with_selection(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            rig.server.script = lambda frame: [MENU_VIEW]
            await rig.press("down")
            await until(
                lambda: rig.panel.client.view["screen"] == "menu", what="menu view"
            )
            assert await rig.drawn() == ["> Network >", "  System >", "(◀Back ●Select)"]
            px = rig.screen.last_image.load()
            assert px[60, render.BODY_TOP + 2] == SELECTED_BG
            assert px[60, render.BODY_TOP + render.ROW_H + 2] != SELECTED_BG

    run(scenario())


def test_button_thread_path_reaches_the_service(rig_factory):
    """press() is what the GPIO monitor and the -e emulator call, from their threads."""

    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await asyncio.to_thread(rig.panel.press, "center")
            (frame,) = await rig.server.wait_for("input")
            assert frame["key"] == "center"

    run(scenario())


# ---------------------------------------------------------------------- prompts


def select_view(selected: int):
    return {
        "type": "view",
        "screen": "prompt",
        "node": "utils.scan",
        "title": "Adapter",
        "job_id": "jab12",
        "answerable": True,
        "blocks": [
            {
                "type": "list",
                "text": "",
                "selected": selected,
                "items": [
                    {"label": "wlan0", "detail": "phy0"},
                    {"label": "wlan1", "detail": "phy1"},
                ],
            }
        ],
        "hints": {"left": "Cancel", "center": "OK"},
    }


def test_select_prompt_is_answered_with_buttons_on_the_shared_screen(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(
                {
                    "type": "prompt",
                    "prompt_id": "psel1",
                    "job_id": "jab12",
                    "node": "utils.scan",
                    "kind": "select",
                    "title": "Adapter",
                    "options": [
                        {
                            "value": {"iface": "wlan0", "namespace": None},
                            "label": "wlan0",
                            "detail": "phy0",
                        },
                        {
                            "value": {"iface": "wlan1", "namespace": None},
                            "label": "wlan1",
                            "detail": "phy1",
                        },
                    ],
                    "expires_sec": 120,
                }
            )
            await rig.server.push(select_view(0))
            await until(
                lambda: rig.panel.client.view["screen"] == "prompt", what="prompt view"
            )
            assert (await rig.drawn())[:2] == ["> wlan0 (phy0)", "  wlan1 (phy1)"]
            assert rig.panel.editor is None  # the service's cursor drives a select

            state = {"selected": 0}

            def script(frame):
                assert frame["type"] == "input"
                if frame["key"] == "down":
                    state["selected"] = 1
                    return [select_view(1)]
                return [result_view(2)]  # center answered it

            rig.server.script = script
            await rig.press("down")
            await until(
                lambda: rig.panel.client.view["blocks"][0]["selected"] == 1,
                what="moved highlight",
            )
            assert (await rig.drawn())[:2] == ["  wlan0 (phy0)", "> wlan1 (phy1)"]
            await rig.press("center")
            await until(
                lambda: rig.panel.client.view["screen"] == "result", what="result"
            )
            assert [f["key"] for f in rig.server.of_type("input")] == ["down", "center"]
            assert rig.server.of_type("answer") == []
            assert rig.panel.client.prompts == {}

    run(scenario())


def confirm_view(selected: str, answerable: bool = True):
    return {
        "type": "view",
        "screen": "prompt",
        "node": "system.reboot",
        "title": "Reboot",
        "job_id": "jab12",
        "answerable": answerable,
        "blocks": [
            {
                "type": "confirm",
                "text": "Reboot?\n[Confirm] [Cancel]",
                "prompt_id": "pcnf1",
                "message": "Reboot the WLAN Pi?",
                "confirm_label": "Confirm",
                "cancel_label": "Cancel",
                "selected": selected,
            }
        ],
        "hints": {"left": "Cancel", "center": "OK"} if answerable else {},
    }


CONFIRM_PROMPT = {
    "type": "prompt",
    "prompt_id": "pcnf1",
    "job_id": "jab12",
    "node": "system.reboot",
    "kind": "confirm",
    "title": "Reboot",
    "message": "Reboot the WLAN Pi?",
    "invoked_by": {"kind": "webui", "name": "admin"},
    "confirm_label": "Confirm",
    "cancel_label": "Cancel",
}


def test_confirm_prompt_toggle_and_confirm_with_buttons(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(CONFIRM_PROMPT)
            await rig.server.push(confirm_view("cancel"))
            await until(
                lambda: rig.panel.client.view["screen"] == "prompt", what="prompt view"
            )
            assert (await rig.drawn())[:2] == [
                "Reboot the WLAN Pi?",
                "[Cancel]  Confirm ",
            ]

            rig.server.script = lambda f: (
                [confirm_view("confirm")] if f["key"] == "down" else [result_view(1)]
            )
            await rig.press("down")
            await until(
                lambda: rig.panel.client.view["blocks"][0].get("selected") == "confirm",
                what="toggle",
            )
            assert (await rig.drawn())[1] == " Cancel  [Confirm]"
            await rig.press("center")
            await until(
                lambda: rig.panel.client.view["screen"] == "result", what="confirmed"
            )
            assert [f["key"] for f in rig.server.of_type("input")] == ["down", "center"]

    run(scenario())


def test_confirmation_invoked_by_someone_else_is_not_answerable(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(CONFIRM_PROMPT)
            await rig.server.push(confirm_view("cancel", answerable=False))
            await until(
                lambda: rig.panel.client.view["screen"] == "prompt", what="prompt view"
            )
            for key in ("center", "left", "down", "key3"):
                await rig.press(key)
            await asyncio.sleep(0.05)
            assert rig.server.of_type("input") == []  # would be refused FORBIDDEN
            assert "! Only admin can answer this" in await rig.drawn()

    run(scenario())


def test_string_prompt_is_edited_locally_and_sent_as_an_answer(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(
                {
                    "type": "prompt",
                    "prompt_id": "pstr1",
                    "job_id": "jab12",
                    "kind": "string",
                    "title": "SSID",
                }
            )
            await rig.server.push(
                {
                    "type": "view",
                    "screen": "prompt",
                    "title": "SSID",
                    "job_id": "jab12",
                    "answerable": True,
                    "blocks": [
                        {"type": "text", "text": "SSID: answer on the client keyboard"}
                    ],
                    "hints": {"left": "Cancel", "center": "OK"},
                }
            )
            await until(lambda: rig.panel.editor is not None, what="editor")
            assert (await rig.drawn())[0] == "[a]"
            rig.server.script = lambda frame: [result_view(1)]
            for key in ("right", "down", "right", "key2", "right"):
                await rig.press(key)
            assert (await rig.drawn())[0] == "abA[A]"
            await rig.press("center")
            (answer,) = await rig.server.wait_for("answer")
            assert answer["prompt_id"] == "pstr1"
            assert answer["value"] == "abA"
            # Keys went to the editor, not to the service's cursor; key2 did not rotate.
            assert rig.server.of_type("input") == []
            assert rig.rotations == 0
            await until(lambda: rig.panel.editor is None, what="editor closed")

    run(scenario())


FORM_PROMPT = {
    "type": "prompt",
    "prompt_id": "pfrm1",
    "job_id": "jab12",
    "node": "system.reg_domain.set",
    "kind": "form",
    "title": "Set Domain",
    "fields": [
        {
            "name": "country",
            "label": "Country",
            "type": "enum",
            "choices": [
                {"value": "US", "label": "US"},
                {"value": "CA", "label": "Canada"},
            ],
        },
        {
            "name": "channel",
            "label": "Channel",
            "type": "integer",
            "minimum": 1,
            "maximum": 11,
            "default": 1,
        },
    ],
}
FORM_VIEW = {
    "type": "view",
    "screen": "prompt",
    "title": "Set Domain",
    "job_id": "jab12",
    "answerable": True,
    "blocks": [{"type": "text", "text": "Set Domain: answer on the client keyboard"}],
    "hints": {"left": "Cancel", "center": "OK"},
}


def test_form_prompt_fields_with_buttons_and_key1_to_send(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(FORM_PROMPT)
            await rig.server.push(FORM_VIEW)
            await until(lambda: rig.panel.editor is not None, what="editor")
            assert await rig.drawn() == [
                "> Country (US)",
                "  Channel (1)",
                "  Send",
                "  Cancel",
                "(◀Cancel ●Edit 1:Send)",
            ]
            for key in ("center", "down", "center"):  # Country -> Canada
                await rig.press(key)
            for key in ("down", "center", "up", "up", "center"):  # Channel -> 3
                await rig.press(key)
            assert (await rig.drawn())[:2] == ["  Country (Canada)", "> Channel (3)"]
            rig.server.script = lambda frame: [result_view(1)]
            await rig.press("key1")
            (answer,) = await rig.server.wait_for("answer")
            assert answer["prompt_id"] == "pfrm1"
            assert answer["values"] == {"country": "CA", "channel": 3}
            assert rig.server.of_type("input") == []

    run(scenario())


def test_form_prompt_key3_cancels(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(FORM_PROMPT)
            await rig.server.push(FORM_VIEW)
            await until(lambda: rig.panel.editor is not None, what="editor")
            rig.server.script = lambda frame: [MENU_VIEW]
            await rig.press("key3")
            (answer,) = await rig.server.wait_for("answer")
            assert answer == {
                "v": 1,
                "type": "answer",
                "id": answer["id"],
                "prompt_id": "pfrm1",
                "cancel": True,
            }

    run(scenario())


def test_prompt_answered_elsewhere_closes_the_editor(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(FORM_PROMPT)
            await rig.server.push(FORM_VIEW)
            await until(lambda: rig.panel.editor is not None, what="editor")
            await rig.server.push(result_view(1))  # first answer won on another surface
            await until(lambda: rig.panel.editor is None, what="editor closed")
            assert (await rig.drawn())[0] == "line 0"

    run(scenario())


# ---------------------------------------------------------------------- jobs


def busy_view(pct, message):
    return {
        "type": "view",
        "screen": "busy",
        "node": "utils.speedtest",
        "title": "Speedtest",
        "job_id": "jab12",
        "blocks": [{"type": "progress", "text": message, "pct": pct, "label": message}],
        "hints": {"left": "Back"},
    }


def test_job_progress_then_cancel(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(
                {
                    "type": "job",
                    "job_id": "jab12",
                    "node": "utils.speedtest",
                    "state": "queued",
                }
            )
            await rig.server.push(busy_view(None, "Starting…"))
            await until(
                lambda: rig.panel.client.view["screen"] == "busy", what="busy view"
            )
            assert (await rig.drawn())[0] == "[progress …] Starting…"

            await rig.server.push(
                {
                    "type": "job",
                    "job_id": "jab12",
                    "node": "utils.speedtest",
                    "state": "progress",
                    "progress": {"pct": 40, "message": "Downloading"},
                }
            )
            await rig.server.push(busy_view(40, "Downloading"))
            await until(
                lambda: rig.panel.client.view["blocks"][0]["pct"] == 40, what="progress"
            )
            assert (await rig.drawn())[0] == "[progress 40%] Downloading"
            assert rig.panel.client.jobs["jab12"]["state"] == "progress"

            def script(frame):
                assert frame["type"] == "cancel"
                return [
                    {
                        "type": "job",
                        "job_id": "jab12",
                        "node": "utils.speedtest",
                        "state": "cancelled",
                    },
                    {**MENU_VIEW, "id": "s:900"},
                ]

            rig.server.script = script
            await rig.press("left")
            (cancel,) = await rig.server.wait_for("cancel")
            assert cancel["job_id"] == "jab12"
            await until(
                lambda: rig.panel.client.view["screen"] == "menu",
                what="back at the menu",
            )
            assert rig.panel.client.jobs["jab12"]["state"] == "cancelled"
            assert rig.server.of_type("input") == []

    run(scenario())


def test_jobs_topic_badge_and_stale_gap(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            client = rig.panel.client
            await until(lambda: "jobs" in client.topic_seq, what="jobs snapshot")
            before = rig.screen.last_image.tobytes()
            job = {
                "job_id": "jab12",
                "node": "utils.speedtest",
                "state": "progress",
                "sessions": 1,
            }
            await rig.server.publish("jobs", [job])
            await until(lambda: client.topic("jobs") == [job], what="jobs event")
            await rig.drawn()
            assert rig.screen.last_image.tobytes() != before  # "1 job" in the title bar

            # A seq gap without snapshot: stale until the next snapshot.
            await rig.server.publish("jobs", [], skip_seq=1)
            await until(lambda: "jobs" in client.stale_topics, what="stale")
            assert client.topic("jobs") is None
            await rig.server.push(
                {
                    "type": "event",
                    "topic": "jobs",
                    "seq": rig.server.seq["jobs"],
                    "snapshot": True,
                    "data": [],
                }
            )
            await until(lambda: "jobs" not in client.stale_topics, what="fresh again")
            assert client.topic("jobs") == []

    run(scenario())


# ---------------------------------------------------------------------- paging


def test_up_down_scroll_locally_then_page_through_the_service(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            pages = {"index": 0}

            def paged():
                return result_view(
                    12,
                    page={
                        "index": pages["index"],
                        "count": 2,
                        "more": pages["index"] == 0,
                    },
                )

            def script(frame):
                if frame["key"] == "down":
                    pages["index"] = 1
                elif frame["key"] == "up":
                    pages["index"] = 0
                return [paged()]

            rig.server.script = script
            await rig.server.push(paged())
            await until(
                lambda: rig.panel.client.view["screen"] == "result", what="result"
            )
            await rig.drawn()
            assert rig.panel.max_scroll == (12 - render.ROWS) * render.ROW_H

            # 12 lines on an 8 row screen: two presses scroll, the service sees nothing.
            await rig.press("down")
            await rig.drawn()
            assert rig.panel.scroll == render.ROW_H * 3
            await rig.press("down")
            await rig.drawn()
            assert rig.panel.scroll == rig.panel.max_scroll
            assert rig.server.of_type("input") == []

            # At the end of the list the key goes to the service, which turns the page.
            await rig.press("down")
            await until(
                lambda: rig.panel.client.view["page"]["index"] == 1, what="page 2"
            )
            await rig.drawn()
            assert rig.panel.scroll == 0
            assert [f["key"] for f in rig.server.of_type("input")] == ["down"]

            # Up at the top of page 2 goes back, entering page 1 from its end.
            await rig.press("up")
            await until(
                lambda: rig.panel.client.view["page"]["index"] == 0, what="page 1"
            )
            await rig.drawn()
            assert rig.panel.scroll == rig.panel.max_scroll
            assert [f["key"] for f in rig.server.of_type("input")] == ["down", "up"]
            assert rig.server.of_type("page") == []

    run(scenario())


def test_page_frame_fetches_by_cursor_when_the_view_is_not_paged(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            job = {
                "type": "job",
                "job_id": "jab12",
                "node": "network.interfaces",
                "state": "result",
            }
            await rig.server.push(
                {
                    **job,
                    "result": {
                        "blocks": [{"type": "text", "text": "page 1"}],
                        "cursor": "cur-2",
                        "total": 3,
                    },
                }
            )
            await rig.server.push(
                {**result_view(1), "blocks": [{"type": "text", "text": "page 1"}]}
            )  # no view.page
            await until(
                lambda: rig.panel.client.view["screen"] == "result", what="result"
            )
            assert (await rig.drawn())[0] == "page 1"

            def script(frame):
                assert frame["type"] == "page"
                nxt = {"cur-2": ("page 2", "cur-3"), "cur-3": ("page 3", None)}[
                    frame["cursor"]
                ]
                return [
                    {
                        **job,
                        "result": {
                            "blocks": [{"type": "text", "text": nxt[0]}],
                            "cursor": nxt[1],
                            "total": 3,
                        },
                    }
                ]

            rig.server.script = script
            await rig.press("down")
            await until(lambda: rig.panel.client.fetched_index == 0, what="page 2")
            assert (await rig.drawn())[0] == "page 2"
            await rig.press("down")
            await until(lambda: rig.panel.client.fetched_index == 1, what="page 3")
            assert (await rig.drawn())[0] == "page 3"
            pages = rig.server.of_type("page")
            assert [(p["job_id"], p["cursor"]) for p in pages] == [
                ("jab12", "cur-2"),
                ("jab12", "cur-3"),
            ]

            # Back up through the fetched pages to the view's own, without asking again.
            await rig.press("up")
            assert (await rig.drawn())[0] == "page 2"
            await rig.press("up")
            assert (await rig.drawn())[0] == "page 1"
            assert len(rig.server.of_type("page")) == 2

            # Last page, no cursor: down is the service's again.
            await rig.press("down")
            await rig.press("down")
            assert (await rig.drawn())[0] == "page 3"
            rig.server.script = None
            await rig.press("down")
            await rig.server.wait_for("input")
            assert len(rig.server.of_type("page")) == 2

    run(scenario())


# ---------------------------------------------------------------------- reconnect


def test_reconnect_resumes_with_epoch_session_and_seq(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            client = rig.panel.client
            await until(lambda: len(client.topic_seq) == 4, what="snapshots")
            await rig.server.publish(
                "alerts", [{"level": "warn", "message": "Low battery"}]
            )
            await until(lambda: client.topic_seq["alerts"] == 2, what="alert event")

            await rig.server.drop_connections(1001)  # service stopping
            await until(lambda: rig.server.hellos == 2, what="second hello")
            await until(lambda: client.connected, what="reconnected")

            hello = rig.server.of_type("hello")[1]
            assert hello["resume"] == {
                "epoch": rig.server.epoch,
                "session_id": rig.server.session_id,
                "seq": {
                    "device.summary": 1,
                    "complications": 1,
                    "alerts": 2,
                    "jobs": 1,
                },
                "menu_revision": 1,
            }
            assert client.resumed is True
            # Resumed: the topic stream continues, so nothing is subscribed again.
            await asyncio.sleep(0.05)
            assert len(rig.server.of_type("subscribe")) == 1
            await rig.server.publish("alerts", [])
            await until(
                lambda: client.topic_seq["alerts"] == 3, what="event after resume"
            )
            assert client.stale_topics == set()
            assert (await rig.drawn())[0] == "Host: wlanpi-test"

    run(scenario())


def test_missed_updates_while_away_get_snapshots_not_a_resume(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            client = rig.panel.client
            await until(lambda: len(client.topic_seq) == 4, what="snapshots")
            await rig.server.stop()
            await until(lambda: not client.connected, what="disconnect")
            rig.server.topic_data["alerts"] = [
                {"level": "error", "message": "Disk full"}
            ]
            rig.server.seq["alerts"] += 1  # changed while the panel was away
            await rig.server.start()
            await until(lambda: client.connected, what="reconnected")
            assert client.resumed is False
            await until(lambda: client.topic_seq["alerts"] == 2, what="alerts snapshot")
            assert client.topic("alerts") == [
                {"level": "error", "message": "Disk full"}
            ]
            # Same epoch: the service re-subscribed the topics named in resume.seq itself.
            assert len(rig.server.of_type("subscribe")) == 1

    run(scenario())


def test_new_epoch_drops_old_state_and_subscribes_again(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            client = rig.panel.client
            await until(lambda: len(client.topic_seq) == 4, what="snapshots")
            await rig.server.publish(
                "jobs",
                [{"job_id": "jab12", "node": "a.b", "state": "queued", "sessions": 1}],
            )
            await until(lambda: client.topic_seq["jobs"] == 2, what="jobs event")
            await rig.server.push(
                {"type": "job", "job_id": "jab12", "node": "a.b", "state": "queued"}
            )
            await until(lambda: "jab12" in client.jobs, what="job frame")

            rig.server.topic_data["jobs"] = []
            await rig.server.restart(epoch="epochBBBB0002")
            await until(
                lambda: client.epoch == "epochBBBB0002" and client.connected,
                what="new epoch",
            )
            hello = rig.server.of_type("hello")[-1]
            assert hello["resume"]["epoch"] == "epochAAAA0001"  # what it last saw
            assert client.resumed is False
            assert client.jobs == {}
            subs = await rig.server.wait_for("subscribe", 2)
            assert subs[-1]["topics"] == [
                "device.summary",
                "complications",
                "alerts",
                "jobs",
            ]
            await until(
                lambda: client.topic_seq == dict.fromkeys(client.topics, 1),
                what="fresh snapshots",
            )
            assert client.topic("jobs") == []

    run(scenario())


def test_reconnect_backoff_grows_and_a_button_retries_at_once(rig_factory):
    async def scenario():
        async with rig_factory(start_server=False) as rig:
            panel = await rig.start_panel(backoff_min=0.05, backoff_max=0.4)
            client = panel.client
            stamps = []
            previous = 0
            loop = asyncio.get_running_loop()
            while len(stamps) < 5:
                await until(lambda: client.failures > previous, what="another failure")  # noqa: B023
                previous = client.failures
                stamps.append(loop.time())
            gaps = [b - a for a, b in itertools.pairwise(stamps)]
            assert gaps[0] < gaps[1] < gaps[2]  # 0.05, 0.1, 0.2 (with 10% jitter)
            assert all(gap < 0.4 * 1.1 + 0.1 for gap in gaps)  # capped

            # Slow retries now. A button press does not wait for the timer.
            panel.client.backoff_max = 30
            await until(lambda: client.failures > previous, what="failure")
            await rig.server.start()
            await rig.press("center")
            await until(
                lambda: client.connected, timeout=1.0, what="immediate reconnect"
            )
            assert rig.server.of_type("input") == []  # the press itself is not sent

    run(scenario())


def test_version_refusal_is_shown_and_retried_slowly(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            rig.server.refuse_hello = {
                "code": "VERSION",
                "message": "no common protocol version",
                "fatal": True,
                "close_code": 4426,
                "supported": [2],
            }
            panel = await rig.start_panel(backoff_min=0.05, backoff_max=0.3)
            await until(lambda: panel.client.failures == 1, what="refusal")
            assert panel.client.last_failure == "VERSION: no common protocol version"
            lines = await rig.drawn()
            assert lines[0] == "[error] Menu unavailable: Retrying…"
            assert " ".join(lines[-2:]) == "VERSION: no common protocol version"
            # It keeps trying (an upgrade of either side fixes it), at the slow rate.
            await asyncio.sleep(0.15)
            assert rig.server.hellos == 1
            await until(lambda: rig.server.hellos >= 2, what="slow retry")
            rig.server.refuse_hello = None
            await until(lambda: panel.client.connected, what="accepted")

    run(scenario())


# ---------------------------------------------------------------------- service down


def test_service_unavailable_screen_shows_the_ip_while_retrying(
    rig_factory, monkeypatch
):
    monkeypatch.setattr(
        netinfo,
        "ipv4_addresses",
        lambda: [("eth0", "192.0.2.44"), ("wlan0", "198.51.100.9")],
    )
    monkeypatch.setattr(netinfo, "hostname", lambda: "wlanpi-a1b2")

    async def scenario():
        async with rig_factory(start_server=False) as rig:
            panel = await rig.start_panel()
            # Before the first attempt has failed: starting, with the address already up.
            panel.draw()
            assert panel.last_frame.lines[:2] == [
                "[info] Starting menu: Connecting…",
                "eth0: 192.0.2.44",
            ]

            await until(lambda: panel.client.failures >= 2, what="retries")
            lines = await rig.drawn()
            assert lines[:4] == [
                "[error] Menu unavailable: Retrying…",
                "eth0: 192.0.2.44",
                "wlan0: 198.51.100.9",
                "wlanpi-a1b2",
            ]
            assert rig.screen.last_image is not None
            colours = {c for _, c in rig.screen.last_image.getcolors(maxcolors=1 << 16)}
            assert ImageColor.getrgb(render.LEVEL_COLOURS["error"]) in colours
            for key in ("down", "center"):  # nothing to send to
                await rig.press(key)
            assert panel.scroll == 0  # four rows: nothing to scroll either

            # The service comes up: the next retry attaches and the menu replaces the screen.
            await rig.server.start()
            await rig.connected()
            assert (await rig.drawn())[0] == "Host: wlanpi-test"
            assert rig.server.of_type("input") == []

            # And when it goes away again the address screen is back.
            await rig.server.stop()
            await until(lambda: not panel.client.connected, what="disconnect")
            assert (await rig.drawn())[:2] == [
                "[error] Menu unavailable: Retrying…",
                "eth0: 192.0.2.44",
            ]

    run(scenario())


# ---------------------------------------------------------------------- local behaviour


def test_error_frame_is_shown_as_a_notice(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            rig.server.script = lambda frame: [
                {
                    "type": "error",
                    "code": "CONFLICT",
                    "message": "capture already running",
                    "core_status": 409,
                }
            ]
            await rig.press("center")
            await until(lambda: rig.panel.client.notice, what="notice")
            assert "! CONFLICT: capture already running" in await rig.drawn()
            assert rig.panel.client.connected  # not fatal

    run(scenario())


def test_driven_by_another_surface_is_indicated(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            await rig.server.push(
                {
                    **MENU_VIEW,
                    "driven_by": {
                        "principal": {"kind": "webui", "name": "admin"},
                        "surface": "wlanpi-webui",
                        "self": False,
                    },
                }
            )
            await until(lambda: rig.panel.client.view["screen"] == "menu", what="menu")
            assert (await rig.drawn())[-1] == "(driven by webui)"
            await rig.server.push(
                {
                    **MENU_VIEW,
                    "driven_by": {
                        "principal": {"kind": "local", "name": "root", "uid": 0},
                        "surface": "wlanpi-fpms",
                        "self": True,
                    },
                }
            )
            await until(
                lambda: rig.panel.client.view["driven_by"]["self"], what="own view"
            )
            assert "(driven by" not in (await rig.drawn())[-1]

    run(scenario())


def test_screen_sleeps_and_first_press_only_wakes(rig_factory, monkeypatch):
    monkeypatch.setattr("fpms.modules.menud_client.panel.TICK_SEC", 0.02)

    async def scenario():
        async with rig_factory() as rig:
            await rig.start_panel(sleep_after=0.1)
            await rig.connected()
            await until(lambda: rig.screen.asleep, what="sleep")
            assert rig.panel.asleep
            frames = rig.screen.frames
            await rig.server.publish("alerts", [{"level": "info", "message": "x"}])
            await asyncio.sleep(0.05)
            assert rig.screen.frames == frames  # nothing is drawn while asleep

            await rig.press("down")
            assert not rig.screen.asleep
            assert (
                rig.server.of_type("input") == []
            )  # the waking press is not a menu press
            await rig.press("down")
            await rig.server.wait_for("input")

            # Someone navigating from another surface wakes the panel too.
            await until(lambda: rig.screen.asleep, what="sleep again")
            await rig.server.push(
                {
                    **MENU_VIEW,
                    "driven_by": {
                        "principal": {"kind": "webui", "name": "admin"},
                        "self": False,
                    },
                }
            )
            await until(
                lambda: not rig.screen.asleep, what="woken by remote navigation"
            )

    run(scenario())


def test_ethernet_link_change_wakes_the_screen(rig_factory, monkeypatch):
    monkeypatch.setattr("fpms.modules.menud_client.panel.TICK_SEC", 0.02)
    carrier = {"value": 0}

    async def scenario():
        async with rig_factory() as rig:
            await rig.start_panel(
                sleep_after=0.1, carrier_reader=lambda: carrier["value"]
            )
            await rig.connected()
            await until(lambda: rig.screen.asleep, what="sleep")
            carrier["value"] = 1
            await until(lambda: not rig.screen.asleep, what="wake on link")

    run(scenario())


def test_unchanged_screen_is_not_redrawn(rig_factory):
    async def scenario():
        async with rig_factory() as rig:
            await rig.connected()
            frames = rig.screen.frames
            await rig.server.push(rig.server.view_frame())  # the same view again
            await rig.drawn()
            assert rig.screen.frames == frames

    run(scenario())


def test_unavailable_screen_scrolls_when_there_are_many_addresses(
    rig_factory, monkeypatch
):
    many = [(f"eth{i}", f"192.0.2.{i}") for i in range(12)]
    monkeypatch.setattr(netinfo, "ipv4_addresses", lambda: many)

    async def scenario():
        async with rig_factory(start_server=False) as rig:
            panel = await rig.start_panel()
            await until(lambda: panel.client.failures >= 1, what="first failure")
            await rig.drawn()
            assert panel.max_scroll > 0
            await rig.press("down")
            await rig.drawn()
            assert panel.scroll == render.ROW_H * 3
            await rig.press("up")
            await rig.drawn()
            assert panel.scroll == 0

    run(scenario())
