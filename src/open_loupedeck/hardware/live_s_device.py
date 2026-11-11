"""Compatibility shim: the Live S driver moved to :mod:`open_loupedeck.devices.loupedeck.live_s`."""

from __future__ import annotations

from ..devices.loupedeck.live_s import (  # noqa: F401
    KEY_PX,
    LIVE_S_COLUMNS,
    LIVE_S_MAX_KEY,
    LIVE_S_ROWS,
    LIVE_S_VISIBLE_X0,
    LIVE_S_VISIBLE_X1,
    LoupedeckLiveS,
)
