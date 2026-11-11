"""
Hardware facts the panel needs before it can draw: the WLAN Pi model, the
display that model carries and the gpiochip behind the 40-pin header.
"""

import glob
import os
import subprocess

from fpms.modules.display import DISPLAY_TYPE_SSD1351, DISPLAY_TYPE_ST7735
from fpms.modules.platform import HEADER_GPIOCHIP_LABELS, PLATFORM_PRO, PLATFORM_UNKNOWN


class EnvUtils:
    def __init__(self):
        pass

    def get_platform(self, WLANPI_MODEL_FILE):
        """
        Method to determine which platform we're running on.
        Uses output of "cat /proc/cpuinfo"

        Possible strings seen in the wild:

           Pro:    Raspberry Pi Compute Module 4
           RPi3b+: Raspberry Pi 3 Model B Plus Rev 1.3
           RPi4:   Raspberry Pi 4 Model B Rev 1.1

        Errors sent to stdout, but will not exit on error
        """

        platform = PLATFORM_UNKNOWN

        if os.path.isfile(WLANPI_MODEL_FILE):
            with open(WLANPI_MODEL_FILE) as f:
                platform = f.readline().strip()

        if platform == PLATFORM_UNKNOWN:
            model_cmd = 'wlanpi-model | grep "Model:" | cut -d ":" -f2 | xargs'
            try:
                platform = (
                    subprocess.check_output(model_cmd, shell=True).decode().strip()
                )
            except subprocess.CalledProcessError:
                return PLATFORM_UNKNOWN

        if platform.endswith("?"):
            platform = PLATFORM_UNKNOWN

        return platform

    def get_gpiochip(self, dev_dir="/dev"):
        """
        Return the gpiochip that drives the 40-pin header. Chip numbering is
        not stable: on the Pi 5 the RP1 header chip is not gpiochip0 on every
        kernel, so match the driver label instead. Falls back to gpiochip0.
        """
        fallback = os.path.join(dev_dir, "gpiochip0")
        try:
            import gpiod
        except ImportError:
            return fallback

        for path in sorted(glob.glob(os.path.join(dev_dir, "gpiochip*"))):
            try:
                with gpiod.Chip(path) as chip:
                    if chip.get_info().label in HEADER_GPIOCHIP_LABELS:
                        return path
            except OSError:
                continue
        return fallback

    def get_display_type(self, platform):
        if platform == PLATFORM_PRO:
            return DISPLAY_TYPE_SSD1351
        else:
            return DISPLAY_TYPE_ST7735
