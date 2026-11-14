"""fpms -e end to end: the real main(), keyboard emulation on stdin, the
virtual screen and a fake menud. Only D-Bus and the SPI screen drivers are
stubbed."""

from __future__ import annotations

import asyncio
import configparser
import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import until
from fake_menud import HOME_VIEW

from fpms.modules.menud_client import render


@pytest.fixture
def fpms_main(monkeypatch, tmp_path):
    """Load fpms/fpms.py as root would run it, on a machine with no panel hardware."""
    stubs = {
        name: types.ModuleType(name)
        for name in (
            "dbus",
            "dbus.mainloop",
            "dbus.mainloop.glib",
            "gi",
            "gi.repository",
        )
    }
    stubs["dbus"].mainloop = stubs["dbus.mainloop"]
    stubs["dbus.mainloop"].glib = stubs["dbus.mainloop.glib"]
    stubs["dbus.mainloop.glib"].DBusGMainLoop = Mock()
    login1 = Mock()
    login1.Inhibit.return_value.take.return_value = None
    stubs["dbus"].SystemBus = Mock()
    stubs["dbus"].Interface = Mock(return_value=login1)
    stubs["gi.repository"].GLib = types.SimpleNamespace(MainLoop=Mock())
    # The hardware screen drivers import spidev and luma; the virtual one is used.
    for name, cls in (("luma", "Luma"), ("st7735", "ST7735")):
        mod = types.ModuleType(f"fpms.modules.screen.{name}")
        setattr(mod, cls, type(cls, (), {}))
        stubs[mod.__name__] = mod
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.delitem(sys.modules, "fpms.modules.wlanpi_oled", raising=False)
    monkeypatch.setenv("FPMS_DISPLAY", "virtual")
    monkeypatch.setattr("os.geteuid", lambda: 0)

    path = Path(__file__).parents[2] / "fpms" / "fpms.py"
    spec = importlib.util.spec_from_file_location("fpms._emulation_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, "fpms.modules.wlanpi_oled", raising=False)

    module.log_to_syslog = Mock()
    module.GPIO_CHIP = str(tmp_path / "no-gpiochip")  # no hardware buttons
    module.FPMS_CONF_FILE = str(tmp_path / "wlanpi-fpms.conf")
    module.SCREENSHOTS_DIR = str(tmp_path / "screenshots")
    module.time = types.SimpleNamespace(sleep=lambda s: None)  # skip the splash hold
    return module


def test_emulated_buttons_drive_the_menu_service(
    fpms_main, rig_factory, monkeypatch, tmp_path, capsys
):
    module = fpms_main

    async def scenario():
        async with rig_factory() as rig:
            read_fd, write_fd = os.pipe()
            monkeypatch.setattr(sys, "stdin", os.fdopen(read_fd, "r"))
            monkeypatch.setattr(sys, "argv", ["fpms", "-e"])
            monkeypatch.setenv("FPMS_MENUD_SOCKET", rig.sock)
            main = asyncio.create_task(asyncio.to_thread(module.main))
            try:
                (hello,) = await rig.server.wait_for("hello", timeout=10)
                assert hello["client"] == {
                    "name": "wlanpi-fpms",
                    "version": module.__version__,
                }
                await rig.server.wait_for("subscribe")
                screen = module.oled.device
                # After the splash, the service's home view is on the screen,
                # drawn through wlanpi_oled.
                home = render.render(HOME_VIEW, mode="classic").image.tobytes()
                await until(
                    lambda: screen.last_image.tobytes() == home, what="home view drawn"
                )

                def type_keys(chars):
                    os.write(write_fd, chars.encode())

                # w/x/a/d/s and i/p are buttons; they arrive as input frames, in order.
                type_keys("xwadsip")
                inputs = await rig.server.wait_for("input", 7)
                assert [f["key"] for f in inputs] == [
                    "down",
                    "up",
                    "left",
                    "right",
                    "center",
                    "key1",
                    "key3",
                ]

                # o is key2: the display flips, here and in the config file.
                assert module.oled.orientation == "normal"
                type_keys("o")
                await until(
                    lambda: module.oled.orientation == "flipped", what="rotation"
                )
                conf = configparser.ConfigParser()
                conf.read(module.FPMS_CONF_FILE)
                assert conf.get("display", "orientation") == "flipped"
                assert len(rig.server.of_type("input")) == 7  # key2 stays local

                # g saves what is on screen as a PNG.
                type_keys("g")
                shots = Path(module.SCREENSHOTS_DIR)
                await until(
                    lambda: shots.is_dir() and list(shots.glob("*.png")),
                    what="screenshot",
                )

                # k quits.
                type_keys("k")
                await asyncio.wait_for(main, 5)
            finally:
                if not main.done():
                    os.write(
                        write_fd, b"k"
                    )  # a failed assertion must not leave main() running
                    await asyncio.wait_for(main, 5)
                os.close(write_fd)

    asyncio.run(scenario())
    out = capsys.readouterr().out
    assert "w/x/a/d/s: up/down/left/right/center" in out
    assert "i/o/p: key1/key2/key3" in out


@pytest.mark.parametrize(
    "flag,expected", [("-v", "wlanpi-fpms"), ("-h", "emulate buttons"), ("-a", "*")]
)
def test_information_flags_exit_without_touching_hardware(
    fpms_main, monkeypatch, capsys, flag, expected
):
    monkeypatch.setattr(sys, "argv", ["fpms", flag])
    with pytest.raises(SystemExit) as exit_info:
        fpms_main.main()
    assert not exit_info.value.code
    assert expected in capsys.readouterr().out
