#!/usr/bin/env python3

"""
FPMS
~~~~

Front Panel Menu System

The panel is the buttons and the screen. The menu itself (tree, cursor, jobs,
prompts) lives in wlanpi-menud; this process attaches to its default session
as a thin client, sends button presses and draws the views it gets back.
What remains here is the physical and lifecycle layer: display and GPIO
setup, the boot splash, systemd readiness and the shutdown/reboot screen.
"""

import asyncio
import configparser
import getopt
import logging
import os
import os.path
import sys
import syslog
import threading
import time
from datetime import datetime
from typing import Any

import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from PIL import Image

if not os.geteuid() == 0:
    print("fpms must be run as root ... exiting ...")
    sys.exit(-1)

from .__version__ import __title__, __version__
from .modules import wlanpi_oled as oled
from .modules.constants import (
    BUTTONS_PINS,
    DISPLAY_MODE,
    DISPLAY_ORIENTATION_FLIPPED,
    DISPLAY_ORIENTATION_NORMAL,
    GPIO_CHIP,
    IMAGE_DIR,
    MENUD_SOCKET,
    PAGE_SLEEP_SEC,
    SCRIPT_PATH,
)
from .modules.menud_client.panel import Panel
from .modules.nav import buttons
from .modules.sdnotify import sd_notify_ready

FPMS_CONF_FILE = "/etc/wlanpi-fpms.conf"
SCREENSHOTS_DIR = "/home/wlanpi/screenshots"

g_vars: dict[str, Any] = {
    "display_orientation": DISPLAY_ORIENTATION_NORMAL,
    "shutdown_in_progress": False,
}


def log_to_syslog(message, level=syslog.LOG_INFO):
    syslog.openlog(ident="fpms", logoption=syslog.LOG_PID, facility=syslog.LOG_USER)
    syslog.syslog(level, message)
    syslog.closelog()


def _release_shutdown_inhibitor():
    """Release the delay lock once, even if both shutdown signals arrive."""
    inhibitor_fd = g_vars.pop("shutdown_inhibitor_fd", None)
    if inhibitor_fd is not None:
        os.close(inhibitor_fd)


def handle_reboot_or_shutdown(shutdown=False):
    global g_vars
    log_to_syslog(f"shutdown_in_progress: {g_vars['shutdown_in_progress']}")
    try:
        if not g_vars["shutdown_in_progress"]:
            g_vars["shutdown_in_progress"] = True
            log_to_syslog("Drawing shutdown/reboot image")
            if shutdown:
                oled.final_frame(g_vars["shutdown_image"])
            else:
                oled.final_frame(g_vars["reboot_image"])
            log_to_syslog("Shutdown/reboot image drawn")
    finally:
        _release_shutdown_inhibitor()


def handle_prepare_for_shutdown(arg):
    log_to_syslog("PrepareForShutdown signal received")
    handle_reboot_or_shutdown()


def handle_jobnew(*args):
    log_to_syslog("JobNew signal received")
    for arg in args:
        if isinstance(arg, str):
            if "reboot.target" in arg:
                handle_reboot_or_shutdown()
            elif ("halt.target" in arg) or ("poweroff.target" in arg):
                handle_reboot_or_shutdown(True)


dbus_handlers_ready = threading.Event()


def run_dbus_loop():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()

    login1_proxy = bus.get_object("org.freedesktop.login1", "/org/freedesktop/login1")
    login1 = dbus.Interface(login1_proxy, "org.freedesktop.login1.Manager")

    g_vars["shutdown_inhibitor_fd"] = login1.Inhibit(
        "shutdown", "fpms", "Delaying shutdown", "delay"
    ).take()

    bus.add_signal_receiver(
        handle_prepare_for_shutdown,
        signal_name="PrepareForShutdown",
        dbus_interface="org.freedesktop.login1.Manager",
        bus_name="org.freedesktop.login1",
        path="/org/freedesktop/login1",
    )

    bus.add_signal_receiver(
        handle_jobnew,
        dbus_interface="org.freedesktop.systemd1.Manager",
        signal_name="JobNew",
    )

    log_to_syslog("event handlers added")
    dbus_handlers_ready.set()

    loop = GLib.MainLoop()
    try:
        loop.run()
    finally:
        _release_shutdown_inhibitor()


def save_boot_splash():
    try:
        oled.save_boot_splash(Image.open(IMAGE_DIR + "/booting.png"))
        oled.save_boot_splash(
            Image.open(IMAGE_DIR + "/fpms-failed.png"), oled.boot_splash.FAILED_FILE
        )
    except OSError as exc:
        log_to_syslog(f"Boot splash not saved: {exc}", syslog.LOG_WARNING)


def read_value(section, key, default_value):
    config = configparser.ConfigParser()
    config.read(FPMS_CONF_FILE)

    if config.has_section(section) and config.has_option(section, key):
        value = config.get(section, key)
        return value
    else:
        return default_value


def save_value(section, key, new_value):
    config = configparser.ConfigParser()
    config.read(FPMS_CONF_FILE)

    if not config.has_section(section):
        config.add_section(section)

    config.set(section, key, new_value)

    with open(FPMS_CONF_FILE, "w") as f:
        config.write(f)


def toggle_display_orientation():
    """key2: flip the display, remember it, and redraw the boot splash to match."""
    if g_vars["display_orientation"] == DISPLAY_ORIENTATION_NORMAL:
        g_vars["display_orientation"] = DISPLAY_ORIENTATION_FLIPPED
    else:
        g_vars["display_orientation"] = DISPLAY_ORIENTATION_NORMAL
    oled.orientation = g_vars["display_orientation"]
    try:
        save_value("display", "orientation", g_vars["display_orientation"])
    except OSError as exc:
        log_to_syslog(f"Display orientation not saved: {exc}", syslog.LOG_WARNING)
    save_boot_splash()


def capture_screen(panel):
    frame = panel.last_frame
    if frame is None:
        return
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    timestr = datetime.now().strftime("%Y_%m_%d-%I_%M_%S_%p")
    save_file = os.path.join(SCREENSHOTS_DIR, f"screenshot_{timestr}.png")
    frame.image.save(save_file)
    print(save_file)


def authors():
    path = os.path.join(SCRIPT_PATH, "AUTHORS.md")
    if not os.path.isfile(path):
        return ""
    with open(path) as f:
        return "\n".join(line for line in f.read().splitlines() if line.startswith("*"))


def usage():
    return """
usage: fpms [-a] [-h] [-e] [-v]

wlanpi-fpms drives the front panel of the WLAN Pi: it shows the menu served
by wlanpi-menud and sends it the button presses

optional options:
  -a                print authors
  -e                emulate buttons from keyboard; the menu is shown as
                    terminal text only when no ST7735/SSD1351 display is
                    present (on real hardware this drives that screen)
  -h                show this message and exit
  -v                show module version and exit

environment:
  FPMS_MENUD_SOCKET  wlanpi-menud socket (default /run/wlanpi-menud/local.sock)
  FPMS_DISPLAY       set to "virtual" to run without display hardware
        """


def main():
    try:
        opts, _args = getopt.getopt(
            sys.argv[1:], ":ahev", ["authors", "help", "emulate-buttons", "version"]
        )
    except getopt.GetoptError as error:
        print(f"{error} ... ")
        print(usage())
        sys.exit(2)

    emulate = False

    for opt, _arg in opts:
        if opt in ["-e", "--emulate-buttons"]:
            emulate = True
        elif opt in ("-a", "--authors"):
            print(authors())
            sys.exit()
        elif opt in ("-h", "--help"):
            print(usage())
            sys.exit()
        elif opt in ("-v", "--version"):
            print(f"{__title__} {__version__}")
            sys.exit()
        else:
            raise AssertionError("unhandled option")

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    dbus_thread = threading.Thread(target=run_dbus_loop)
    dbus_thread.daemon = True
    dbus_thread.start()
    log_to_syslog("fpms starting after dbus thread setup")

    # ponytail: gpio contention is the proxy for "another instance owns the
    # display/buttons"; it won't catch a non-fpms holder of the display only.
    # Add an explicit lock file if that case ever matters.
    button_request: Any = None
    if os.path.exists(GPIO_CHIP):
        try:
            button_request = buttons.request_buttons(GPIO_CHIP, BUTTONS_PINS)
        except OSError:
            print(
                "fpms: another fpms instance is using the display/buttons. "
                "Stop it first (e.g. 'sudo systemctl stop wlanpi-fpms').",
                file=sys.stderr,
            )
            sys.exit(1)

    g_vars["display_orientation"] = read_value(
        "display", "orientation", DISPLAY_ORIENTATION_NORMAL
    )
    oled.orientation = g_vars["display_orientation"]
    oled.select_device()
    save_boot_splash()
    oled.init()

    g_vars["reboot_image"] = Image.open(IMAGE_DIR + "/reboot.png").convert(DISPLAY_MODE)
    g_vars["shutdown_image"] = Image.open(IMAGE_DIR + "/shutdown.png").convert(
        DISPLAY_MODE
    )

    # Report ready only once a reboot can draw its screen: startup reboots
    # (wlanpi-config-at-startup) wait for multi-user.target, which waits for this.
    # Without D-Bus, report ready anyway: a menu with no reboot screen beats
    # systemd killing fpms at TimeoutStartSec.
    # Readiness does not wait for wlanpi-menud: the panel shows the device's IP
    # address and keeps retrying while the menu service is away.
    if not dbus_handlers_ready.wait(timeout=20):
        log_to_syslog(
            "D-Bus handlers not ready; reboots started outside fpms show no screen",
            syslog.LOG_WARNING,
        )
    sd_notify_ready()

    for n in range(5):
        img = Image.open(f"{IMAGE_DIR}/wlanpi{n}.png").convert(DISPLAY_MODE)
        oled.drawImage(img)
        time.sleep(0.100)

    time.sleep(2)

    panel = Panel(
        oled,
        socket_path=os.environ.get("FPMS_MENUD_SOCKET", MENUD_SOCKET),
        version=__version__,
        keys=list(BUTTONS_PINS),
        on_rotate=toggle_display_orientation,
        sleep_after=PAGE_SLEEP_SEC,
    )

    if button_request is not None:
        m = threading.Thread(
            name="button-monitor",
            target=buttons.monitor_buttons,
            args=(
                button_request,
                BUTTONS_PINS,
                lambda: g_vars["display_orientation"],
                panel.press,
            ),
        )
        m.daemon = True
        m.start()
    else:
        log_to_syslog(
            f"No {GPIO_CHIP} found; hardware buttons unavailable (use -e for keyboard emulation)"
        )

    if emulate:
        hints = buttons.emulation_hints(BUTTONS_PINS)
        oled.set_hints(hints)
        print("\n".join(hints), flush=True)
        e = threading.Thread(
            name="button-emulator",
            target=buttons.emulate_buttons,
            args=(BUTTONS_PINS, panel.press, lambda: capture_screen(panel), panel.stop),
        )
        e.daemon = True
        e.start()

    try:
        asyncio.run(panel.run())
    except KeyboardInterrupt:
        pass
