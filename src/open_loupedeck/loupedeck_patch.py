"""Compatibility shim: the driver patches moved to :mod:`open_loupedeck.devices.loupedeck.patches`."""

from __future__ import annotations

from .devices.loupedeck.patches import (  # noqa: F401
    apply_loupedeck_init_patch,
    apply_loupedeck_serial_reader_patch,
    set_serial_fatal_callback,
)
