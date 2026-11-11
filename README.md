[![packagecloud-badge](https://img.shields.io/badge/deb-packagecloud.io-844fec.svg)](https://packagecloud.io/)

# WLAN Pi Front Panel Menu System (FPMS)

This project enables the SPI display of WLAN Pi based on the CM4 hardware.

The original ["fpms" repo](https://github.com/WLAN-Pi/fpms) is only compatible with NEO2 hardware and its NanoHat OLED I2C display.

## How it works

`wlanpi-fpms` is the front panel: the display and the buttons. It no longer holds a menu of its own. The menu tree, the cursor, jobs and prompts live in [`wlanpi-menud`](https://github.com/WLAN-Pi/wlanpi-menud), and the panel is a thin client of it:

* It connects to `/run/wlanpi-menud/local.sock` (WebSocket over a Unix socket, protocol v1) and attaches to the service's default session, the shared screen that the TUI and the WebUI can mirror.
* Each button press is sent as an `input` frame (`up`, `down`, `left`, `right`, `center`, `key1`, `key3`). The service answers with a `view` frame, which the panel draws. All eight view block types are drawn: text, key/value, table, list, QR code, status, progress and confirm.
* `key2` stays local: it rotates the display, as before. So do the screen sleep timer, scrolling inside a screen taller than the display, and the button editor for text and form prompts.
* When another surface drives the shared screen, the footer names it.
* If `wlanpi-menud` is not running, the panel shows the device's IP addresses and retries (0.5 s, doubling to 8 s; any button retries at once). After a reconnect it resumes with the epoch and topic sequence numbers it last saw.

What `wlanpi-fpms` still owns is the physical and lifecycle layer: model and display detection, the screen drivers, GPIO buttons, the boot splash, systemd readiness (`Type=notify`) and the reboot/shutdown screen.

| Path | Purpose |
| --- | --- |
| `fpms/fpms.py` | Start-up, D-Bus shutdown handling, systemd notify, wiring |
| `fpms/modules/menud_client/` | Protocol frames, connection and resume, renderer, prompt editor, panel loop |
| `fpms/modules/nav/buttons.py` | GPIO button input and `-e` keyboard emulation |
| `fpms/modules/screen/` | ST7735, SSD1351 (luma) and virtual screen backends |

## Components and Troubleshooting

### Packages 

We are using dh-virtualenv to package the `wlanpi-fpms` Python project into an installable Debian package (`.deb`). The Debian software packages for `wlanpi-fpms` are hosted on Packagecloud and installed automatically on the WLAN Pi OS images.

### Systemd Service

FPMS is now run as a Systemd Service on the WLAN Pi. Systemd is a widely used system manager across Linux distributions.

There is a single primary service for `wlanpi-fpms`:

* `wlanpi-fpms` service which displays information on the SPI display.

It `Wants=wlanpi-menud.service` but does not require it: the panel comes up either way.

You can use `systemctl` to view the status of it:

```bash
systemctl status wlanpi-fpms
```

### Troubleshooting

For troubleshooting, use `systemctl` or `journalctl` to check status or log for the service:

```bash
systemctl status wlanpi-fpms
journalctl -u wlanpi-fpms
```

If the panel shows "Menu unavailable" with the IP addresses, the display side is fine and the menu service is not answering:

```bash
systemctl status wlanpi-menud
journalctl -u wlanpi-menud
```

## Developers

Looking to get your hands dirty?

To install and run `wlanpi-fpms` for development and manual testing refer to the [DEVELOPMENT.md](DEVELOPMENT.md) documentation.

### System requirements

The SPI interface must be enabled for FPMS to work and communicate with the display. 

#### Option 1

Use `raspi-config` to enable SPI:

```
sudo raspi-config
```

#### Option 2

1. Edit boot config: `sudo vim /boot/config.txt`
2. Enable SPI interface by adding this line: `dtparam=spi=on`

## Thanks

`wlanpi-fpms` is built and maintained by a wonderful list of folks found in either [AUTHORS.md](fpms/AUTHORS.md) or the git commit log. If your name is missing, please add yourself and submit a PR.

## OSS

Thank you to all the creators and maintainers of the following open source software used by `wlanpi-fpms`:

* [dh-virtualenv](https://github.com/spotify/dh-virtualenv)
* [Luma.OLED](https://luma-oled.readthedocs.io/en/latest)
* [Pillow](https://python-pillow.org)
* [pip-tools](https://github.com/jazzband/pip-tools)
* [Python](https://www.python.org)
* [RPi.GPIO](https://pypi.org/project/RPi.GPIO)
* [python-qrcode](https://github.com/lincolnloop/python-qrcode)
* [websockets](https://websockets.readthedocs.io)
