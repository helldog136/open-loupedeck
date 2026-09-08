"""Find Loupedeck serial port via USB IDs (preferred) or handshake fallback."""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

LOUPEDECK_VID = 0x2EC2
PID_LOUPEDECK_LIVE = 0x0004
PID_LOUPEDECK_LIVE_S = 0x0006

HardwareHint = Literal["live", "live_s", "unknown"]


def usb_hint_for_port(device_path: str) -> HardwareHint:
    """Best-effort: map /dev/tty* to USB VID/PID via pyserial."""

    try:
        from serial.tools import list_ports
    except ImportError:
        return "unknown"

    device_path = device_path.rstrip()
    for p in list_ports.comports():
        if p.device == device_path:
            if p.vid == LOUPEDECK_VID:
                if p.pid == PID_LOUPEDECK_LIVE_S:
                    return "live_s"
                if p.pid == PID_LOUPEDECK_LIVE:
                    return "live"
            return "unknown"
    return "unknown"


def list_loupedeck_usb_ports() -> list[tuple[str, HardwareHint]]:
    """Return [(path, hint), ...] for known Loupedeck USB serial ports."""

    try:
        from serial.tools import list_ports
    except ImportError:
        return []

    out: list[tuple[str, HardwareHint]] = []
    for p in list_ports.comports():
        if p.vid != LOUPEDECK_VID:
            continue
        if p.pid == PID_LOUPEDECK_LIVE_S:
            out.append((p.device, "live_s"))
        elif p.pid == PID_LOUPEDECK_LIVE:
            out.append((p.device, "live"))
        else:
            out.append((p.device, "unknown"))
            logger.debug("Loupedeck VID with unknown PID 0x%04x: %s", p.pid or 0, p.device)
    return out
