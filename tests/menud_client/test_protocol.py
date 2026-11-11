"""Every frame the panel can send is valid against wlanpi-menud's frames.schema.json."""

from pathlib import Path

import pytest
from fake_menud import SCHEMA_PATH, schema_errors

from fpms.modules.menud_client import protocol

CAPS = protocol.capabilities(
    width_px=128,
    height_px=128,
    cols=21,
    rows=8,
    keys=["up", "down", "left", "right", "center"],
)


def test_vendored_schema_matches_wlanpi_menud():
    upstream = (
        Path(__file__).parents[3] / "wlanpi-menud" / "protocol" / "frames.schema.json"
    )
    if not upstream.exists():
        pytest.skip("wlanpi-menud is not checked out next to this repo")
    assert SCHEMA_PATH.read_text() == upstream.read_text()


def test_hello_is_thin_on_the_default_session():
    frame = protocol.hello("p1", version="1.2.3", capabilities=CAPS)
    assert schema_errors(frame) == []
    assert frame["mode"] == "thin"
    assert frame["session"] == "default"
    assert frame["protocol"] == [1]
    assert frame["client"] == {"name": "wlanpi-fpms", "version": "1.2.3"}
    assert frame["capabilities"]["screen"] == {
        "width_px": 128,
        "height_px": 128,
        "cols": 21,
        "rows": 8,
    }
    assert frame["capabilities"]["colour"] == "colour"
    assert frame["capabilities"]["blocks"] == [
        "text", "kv", "table", "list", "qr", "status", "progress", "confirm",
    ]  # fmt: skip
    # A five-button device (WLAN Pi Pro) does not claim key1 to key3.
    assert frame["capabilities"]["keys"] == ["up", "down", "left", "right", "center"]
    assert "resume" not in frame


def test_hello_resume_carries_epoch_session_and_seq():
    resume = protocol.resume("epochAAAA0001", "S1", {"device.summary": 4, "jobs": 1}, 7)
    frame = protocol.hello("p2", version="1", capabilities=CAPS, resume=resume)
    assert schema_errors(frame) == []
    assert frame["resume"] == {
        "epoch": "epochAAAA0001",
        "session_id": "S1",
        "seq": {"device.summary": 4, "jobs": 1},
        "menu_revision": 7,
    }


@pytest.mark.parametrize(
    "frame",
    [
        protocol.subscribe("p1", protocol.TOPICS),
        protocol.input_frame("p1", "up"),
        protocol.input_frame("p1", "key3"),
        protocol.answer("p1", "pabcd", value="x"),
        protocol.answer("p1", "pabcd", values={"ssid": "x", "channel": 6}),
        protocol.answer("p1", "pabcd", confirmed=True),
        protocol.answer("p1", "pabcd", cancel=True),
        protocol.page("p1", "jabcd", "cursor-1"),
        protocol.cancel("p1", "jabcd"),
    ],
    ids=lambda f: f["type"],
)
def test_client_frames_match_the_schema(frame):
    assert schema_errors(frame) == []


def test_subscribes_to_the_four_built_in_topics():
    assert protocol.subscribe("p1", protocol.TOPICS)["topics"] == [
        "device.summary", "complications", "alerts", "jobs",
    ]  # fmt: skip


def test_input_is_a_press_of_a_known_key():
    assert protocol.input_frame("p1", "center") == {
        "v": 1,
        "type": "input",
        "id": "p1",
        "key": "center",
    }
    with pytest.raises(ValueError):
        protocol.input_frame("p1", "enter")


def test_answer_takes_exactly_one_field():
    with pytest.raises(ValueError):
        protocol.answer("p1", "pabcd")
    with pytest.raises(ValueError):
        protocol.answer("p1", "pabcd", value=1, cancel=True)
