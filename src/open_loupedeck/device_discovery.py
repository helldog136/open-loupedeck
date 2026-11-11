"""Compatibility shim: Loupedeck USB discovery moved to :mod:`open_loupedeck.devices.loupedeck.discovery`."""

from __future__ import annotations

from .devices.loupedeck.discovery import (  # noqa: F401
    LOUPEDECK_VID,
    PID_LOUPEDECK_LIVE,
    PID_LOUPEDECK_LIVE_S,
    HardwareHint,
    list_loupedeck_usb_ports,
    usb_hint_for_port,
)
