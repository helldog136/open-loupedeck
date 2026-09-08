"""OBS WebSocket: stream output status for display overlays."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _fmt_ms(ms: float) -> str:
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return "—"
    v = max(v, 0)
    sec = int(v // 1000)
    h, r = divmod(sec, 3600)
    m, s2 = divmod(r, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s2:02d}"
    return f"{m}:{s2:02d}"


async def fetch_obs_stream_fields(obs: Any | None) -> dict[str, str]:
    """Fields for ``display.obs_stream`` templates."""

    if obs is None:
        return {
            "obs_status": "OBS off",
            "obs_streaming": "no",
            "obs_live": "no",
            "obs_duration": "—",
            "obs_uptime": "—",
            "obs_duration_ms": "0",
            "obs_timecode": "—",
        }
    try:
        data = await obs.call("GetStreamStatus", {})
    except Exception:
        logger.debug("GetStreamStatus failed", exc_info=True)
        return {
            "obs_status": "Error",
            "obs_streaming": "—",
            "obs_live": "—",
            "obs_duration": "—",
            "obs_uptime": "—",
            "obs_duration_ms": "0",
            "obs_timecode": "—",
        }

    if not isinstance(data, dict):
        data = {}

    active = bool(data.get("outputActive"))
    dur_raw = data.get("outputDuration")
    try:
        dur_ms = float(dur_raw) if dur_raw is not None else 0.0
    except (TypeError, ValueError):
        dur_ms = 0.0

    tc = str(data.get("outputTimecode") or "").strip() or "—"
    dur_fmt = _fmt_ms(dur_ms) if active else "—"
    return {
        "obs_status": "LIVE" if active else "Not streaming",
        "obs_streaming": "yes" if active else "no",
        "obs_live": "yes" if active else "no",
        "obs_duration": dur_fmt,
        "obs_uptime": dur_fmt,
        "obs_duration_ms": str(int(dur_ms)),
        "obs_timecode": tc,
    }
