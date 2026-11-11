"""Thin-mode client of wlanpi-menud: the front panel as buttons and a screen.

wlanpi-menud holds the menu, the cursor, jobs and prompts. This package
connects to its local socket, sends button presses as ``input`` frames and
draws the ``view`` frames it gets back. See wlanpi-menud's
protocol/PROTOCOL.md and protocol/frames.schema.json.
"""
