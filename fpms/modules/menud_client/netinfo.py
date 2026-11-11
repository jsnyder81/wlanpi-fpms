"""Local network facts for the screen shown while wlanpi-menud is unreachable."""

from __future__ import annotations

import fcntl
import socket
import struct

SIOCGIFADDR = 0x8915
PREFERRED = ("eth0", "wlan0", "usb0", "pan0")


def ipv4_addresses() -> list[tuple[str, str]]:
    """(interface, address) for every interface with an IPv4 address, loopback excluded."""
    found: dict[str, str] = {}
    try:
        names = [name for _, name in socket.if_nameindex()]
    except OSError:
        return []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for name in names:
            if name == "lo":
                continue
            try:
                packed = fcntl.ioctl(
                    sock.fileno(),
                    SIOCGIFADDR,
                    struct.pack("256s", name[:15].encode()),
                )
            except OSError:
                continue  # no IPv4 address on this interface
            found[name] = socket.inet_ntoa(packed[20:24])
    order = [n for n in PREFERRED if n in found]
    order += sorted(n for n in found if n not in PREFERRED)
    return [(n, found[n]) for n in order]


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""
