"""Read host battery / AC status (Linux sysfs, macOS pmset, Windows GetSystemPowerStatus)."""

from __future__ import annotations

import contextlib
import logging
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _human_status(raw: str) -> str:
    s = (raw or "").strip().lower().replace("_", " ")
    if not s:
        return "Unknown"
    mapping = {
        "charging": "Charging",
        "discharging": "Discharging",
        "full": "Full",
        "not charging": "Not charging",
        "pending charge": "Pending charge",
        "critical": "Critical",
        "unknown": "Unknown",
        "unavailable": "Unavailable",
        "no battery": "No battery",
    }
    return mapping.get(s, s[:1].upper() + s[1:] if s else "Unknown")


def _linux_read() -> tuple[int | None, str, bool | None]:
    root = Path("/sys/class/power_supply")
    if not root.is_dir():
        return None, "unavailable", None

    ac_online: bool | None = None
    percents: list[int] = []
    statuses: list[str] = []

    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        typ_file = d / "type"
        if not typ_file.is_file():
            continue
        typ = typ_file.read_text().strip()
        if typ in ("Mains", "USB", "UPS"):
            online = d / "online"
            if online.is_file():
                try:
                    ac_online = online.read_text().strip() == "1"
                except OSError:
                    logger.debug("battery: could not read %s", online, exc_info=True)
        elif typ == "Battery":
            cap = d / "capacity"
            st = d / "status"
            if cap.is_file():
                try:
                    percents.append(int(cap.read_text().strip()))
                except (ValueError, OSError):
                    logger.debug("battery: bad capacity in %s", cap, exc_info=True)
            if st.is_file():
                with contextlib.suppress(OSError):
                    statuses.append(st.read_text().strip().lower())

    if not percents:
        st = "no battery" if not statuses else (statuses[0] if statuses else "unknown")
        return None, st, ac_online

    pct = min(percents) if len(percents) > 1 else percents[0]
    st = statuses[0] if statuses else "unknown"
    return pct, st, ac_online


def _macos_read() -> tuple[int | None, str, bool | None]:
    try:
        r = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, "unknown", None
    if r.returncode != 0:
        return None, "unknown", None
    text = r.stdout or ""
    m = re.search(r"(\d+)\s*%", text)
    pct = int(m.group(1)) if m else None

    ac: bool | None = None
    if "AC Power" in text:
        ac = True
    elif "Battery Power" in text:
        ac = False

    low = text.lower()
    if "discharging" in low:
        st = "discharging"
    elif "charging" in low:
        st = "charging"
    elif "charged" in low or "; not charging" in low or "full" in low:
        st = "full"
    else:
        st = "unknown"
    return pct, st, ac


def _windows_read() -> tuple[int | None, str, bool | None]:
    import ctypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_ubyte),
            ("BatteryFlag", ctypes.c_ubyte),
            ("BatteryLifePercent", ctypes.c_ubyte),
            ("SystemStatusFlag", ctypes.c_ubyte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    s = SYSTEM_POWER_STATUS()
    ok = ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))  # type: ignore[attr-defined]
    if not ok:
        return None, "unknown", None

    ac: bool | None = None
    if s.ACLineStatus == 0:
        ac = False
    elif s.ACLineStatus == 1:
        ac = True

    if s.BatteryFlag & 128:
        return None, "no battery", ac

    pct: int | None = None
    if s.BatteryLifePercent != 255:
        try:
            pct = int(s.BatteryLifePercent)
        except ValueError:
            pct = None

    if s.BatteryFlag & 8:
        st = "charging"
    elif s.BatteryFlag & 4:
        st = "critical"
    elif pct is not None and pct >= 100 and ac:
        st = "full"
    elif ac:
        st = "charging"
    else:
        st = "discharging"
    return pct, st, ac


def read_battery_info() -> dict[str, str]:
    """Return template-friendly strings: percent, status, ac."""

    try:
        if sys.platform == "darwin":
            pct_i, raw_st, ac = _macos_read()
        elif sys.platform == "win32":
            pct_i, raw_st, ac = _windows_read()
        else:
            pct_i, raw_st, ac = _linux_read()
    except Exception:
        logger.debug("read_battery_info failed", exc_info=True)
        return {
            "battery_percent": "—",
            "battery_percent_raw": "",
            "battery_status": "Unknown",
            "battery_ac": "?",
        }

    pct_s = f"{pct_i}%" if pct_i is not None else "—"
    st = _human_status(raw_st)
    if ac is True:
        ac_s = "AC"
    elif ac is False:
        ac_s = "Battery"
    else:
        ac_s = "?"
    return {
        "battery_percent": pct_s,
        "battery_percent_raw": str(pct_i) if pct_i is not None else "",
        "battery_status": st,
        "battery_ac": ac_s,
    }
