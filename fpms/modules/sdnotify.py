"""systemd readiness notification for the Type=notify unit."""

import os
import socket


def sd_notify_ready():
    """Send READY=1 to systemd for a Type=notify unit; no-op outside systemd."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(addr)
        sock.sendall(b"READY=1")
