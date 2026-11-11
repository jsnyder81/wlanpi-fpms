"""Physical button layer: GPIO edges and the -e keyboard emulation."""

import types

from fpms.modules.nav import buttons

PINS_8 = {
    "up": 6,
    "down": 19,
    "left": 5,
    "right": 26,
    "center": 13,
    "key1": 21,
    "key2": 20,
    "key3": 16,
}
PINS_5 = {"up": 22, "down": 5, "left": 17, "right": 27, "center": 6}


class FakeRequest:
    """gpiod line request that yields scripted edge events, then stops the monitor."""

    def __init__(self, offsets):
        self.batches = [[types.SimpleNamespace(line_offset=o) for o in offsets]]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def wait_edge_events(self, timeout):
        if not self.batches:
            raise StopIteration

    def read_edge_events(self):
        return self.batches.pop(0)


def monitor(offsets, orientation="normal"):
    seen = []
    try:
        buttons.monitor_buttons(
            FakeRequest(offsets), PINS_8, lambda: orientation, seen.append
        )
    except StopIteration:
        pass
    return seen


def test_gpio_offsets_become_protocol_keys():
    assert monitor([6, 19, 5, 26, 13, 21, 20, 16]) == [
        "up", "down", "left", "right", "center", "key1", "key2", "key3",
    ]  # fmt: skip


def test_unknown_gpio_offset_is_ignored():
    assert monitor([99, 13]) == ["center"]


def test_flipped_display_swaps_directions_and_key1_with_key3():
    assert monitor([6, 19, 5, 26, 13, 21, 20, 16], "flipped") == [
        "down", "up", "right", "left", "center", "key3", "key2", "key1",
    ]  # fmt: skip


def test_emulated_keys():
    typed = "8w2x4a6d5s*i-o+p"
    assert [buttons.emulated_key(c, PINS_8) for c in typed] == [
        "up", "up", "down", "down", "left", "left", "right", "right",
        "center", "center", "key1", "key1", "key2", "key2", "key3", "key3",
    ]  # fmt: skip
    assert buttons.emulated_key("W", PINS_8) == "up"
    assert buttons.emulated_key("z", PINS_8) is None


def test_emulation_ignores_keys_the_device_does_not_have():
    assert buttons.emulated_key("i", PINS_5) is None
    assert len(buttons.emulation_hints(PINS_5)) == 2
    assert "key1" in buttons.emulation_hints(PINS_8)[-1]


def test_emulate_buttons_reads_until_quit():
    typed = iter("wsg?pk" + "w")
    seen, shots, quits = [], [], []
    buttons.emulate_buttons(
        PINS_8,
        seen.append,
        lambda: shots.append(1),
        lambda: quits.append(1),
        read=lambda: next(typed),
    )
    assert seen == ["up", "center", "key3"]
    assert shots == [1]
    assert quits == [1]


def test_emulate_buttons_stops_quietly_at_end_of_input():
    typed = iter(["d", ""])
    seen, quits = [], []
    buttons.emulate_buttons(
        PINS_8,
        seen.append,
        lambda: None,
        lambda: quits.append(1),
        read=lambda: next(typed),
    )
    assert seen == ["right"]
    assert quits == []


def test_getch_reads_from_a_pipe(tmp_path):
    path = tmp_path / "keys"
    path.write_text("ab")
    with open(path) as stream:
        assert buttons.getch(stream) == "a"
        assert buttons.getch(stream) == "b"
        assert buttons.getch(stream) == ""
