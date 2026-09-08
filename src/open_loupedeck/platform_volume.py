"""System output volume + mute: Linux (pactl/wpctl), macOS (AppleScript), Windows (pycaw COM)."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Match previous Linux behavior (Pulse/PipeWire can exceed 100%).
SYSTEM_VOLUME_MAX_PERCENT = 120.0


async def _run_exec(argv: list[str], what: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        msg = err.decode(errors="replace") if err else ""
        raise RuntimeError(f"{what} failed ({proc.returncode}): {msg}".strip())


async def _run_exec_stdout(argv: list[str], what: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        msg = err.decode(errors="replace") if err else ""
        raise RuntimeError(f"{what} failed ({proc.returncode}): {msg}".strip())
    return out.decode(errors="replace")


# --- Linux ---


def _pick_linux_backend() -> str:
    if shutil.which("pactl"):
        return "pactl"
    if shutil.which("wpctl"):
        return "wpctl"
    raise RuntimeError(
        "No volume command found: on Linux install pulseaudio-utils (pactl) or wireplumber (wpctl). "
        "On macOS/Windows use the native backends (osascript / pycaw)."
    )


def _sink_tokens_linux(params: dict[str, Any]) -> tuple[str, str]:
    custom = params.get("sink")
    if custom:
        s = str(custom).strip()
        return s, s
    return "@DEFAULT_SINK@", "@DEFAULT_AUDIO_SINK@"


async def _linux_get_volume_percent(backend: str, sp: str, sw: str) -> float:
    if backend == "pactl":
        text = await _run_exec_stdout(["pactl", "get-sink-volume", sp], "get-sink-volume")
        m = re.search(r"(\d+)%", text)
        if not m:
            raise RuntimeError(f"Could not parse pactl get-sink-volume output: {text!r}")
        return float(m.group(1))
    text = (await _run_exec_stdout(["wpctl", "get-volume", sw], "get-volume")).strip()
    m = re.search(r"Volume:\s*([\d.]+)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"\b(\d+\.\d+)\b", text)
    if not m:
        m = re.search(r"\b(\d+)\b", text)
    if not m:
        raise RuntimeError(f"Could not parse wpctl get-volume output: {text!r}")
    try:
        frac = float(m.group(1))
    except ValueError as e:
        raise RuntimeError(f"Could not parse wpctl get-volume output: {text!r}") from e
    return frac * 100.0


async def _linux_set_volume_percent(percent: float, backend: str, sp: str, sw: str) -> None:
    pct = max(0.0, min(float(percent), SYSTEM_VOLUME_MAX_PERCENT))
    if backend == "pactl":
        await _run_exec(
            ["pactl", "set-sink-volume", sp, f"{round(pct)}%"],
            "set-sink-volume",
        )
    else:
        frac = pct / 100.0
        await _run_exec(["wpctl", "set-volume", sw, str(frac)], "set-volume")
    logger.debug("sink volume set to %s%% (capped at %s%%) via %s", pct, SYSTEM_VOLUME_MAX_PERCENT, backend)


async def _linux_mute(mode: str, backend: str, sp: str, sw: str) -> None:
    if mode == "mute":
        pactl_arg, wpctl_arg = "1", "1"
    elif mode == "unmute":
        pactl_arg, wpctl_arg = "0", "0"
    else:
        pactl_arg = wpctl_arg = "toggle"
    if backend == "pactl":
        await _run_exec(["pactl", "set-sink-mute", sp, pactl_arg], "set-sink-mute")
    else:
        await _run_exec(["wpctl", "set-mute", sw, wpctl_arg], "set-mute")
    logger.debug("linux mute %s via %s", mode, backend)


# --- macOS (osascript) ---


async def _macos_get_volume_percent() -> float:
    text = await _run_exec_stdout(
        ["osascript", "-e", "output volume of (get volume settings)"],
        "osascript get volume",
    )
    try:
        return float(text.strip())
    except ValueError as e:
        raise RuntimeError(f"Could not parse osascript volume: {text!r}") from e


async def _macos_set_volume_percent(percent: float) -> None:
    pct = max(0.0, min(float(percent), SYSTEM_VOLUME_MAX_PERCENT))
    await _run_exec(
        ["osascript", "-e", f"set volume output volume {round(pct)}"],
        "osascript set volume",
    )


async def _macos_get_muted() -> bool:
    text = await _run_exec_stdout(
        ["osascript", "-e", "output muted of (get volume settings)"],
        "osascript get mute",
    )
    t = text.strip().lower()
    return t in ("true", "yes")


async def _macos_set_muted(muted: bool) -> None:
    await _run_exec(
        [
            "osascript",
            "-e",
            f"set volume with output muted {str(muted).lower()}",
        ],
        "osascript set mute",
    )


async def _macos_mute(mode: str) -> None:
    if mode in ("on", "mute"):
        await _macos_set_muted(True)
    elif mode in ("off", "unmute"):
        await _macos_set_muted(False)
    else:
        cur = await _macos_get_muted()
        await _macos_set_muted(not cur)


# --- Windows (pycaw + comtypes) ---


def _windows_volume_api():
    try:
        from comtypes import CLSCTX_ALL, POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError as e:
        raise RuntimeError(
            "sound.volume_* on Windows requires COM audio support. Install with:\n"
            "  pip install pycaw comtypes\n"
            "or reinstall the agent with Windows extras if provided."
        ) from e
    return CLSCTX_ALL, POINTER, cast, AudioUtilities, IAudioEndpointVolume


def _sync_windows_get_volume_percent() -> float:
    CLSCTX_ALL, POINTER, cast, AudioUtilities, IAudioEndpointVolume = _windows_volume_api()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    return float(volume.GetMasterVolumeLevelScalar() * 100.0)


def _sync_windows_set_volume_percent(percent: float) -> None:
    CLSCTX_ALL, POINTER, cast, AudioUtilities, IAudioEndpointVolume = _windows_volume_api()
    pct = max(0.0, min(float(percent), SYSTEM_VOLUME_MAX_PERCENT)) / 100.0
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMasterVolumeLevelScalar(pct, None)


def _sync_windows_get_muted() -> bool:
    CLSCTX_ALL, POINTER, cast, AudioUtilities, IAudioEndpointVolume = _windows_volume_api()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    return bool(volume.GetMute())


def _sync_windows_set_muted(muted: bool) -> None:
    CLSCTX_ALL, POINTER, cast, AudioUtilities, IAudioEndpointVolume = _windows_volume_api()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMute(1 if muted else 0, None)


async def _windows_get_volume_percent() -> float:
    return await asyncio.to_thread(_sync_windows_get_volume_percent)


async def _windows_set_volume_percent(percent: float) -> None:
    await asyncio.to_thread(_sync_windows_set_volume_percent, percent)


async def _windows_mute(mode: str) -> None:
    if mode in ("on", "mute"):

        def _go() -> None:
            _sync_windows_set_muted(True)

        await asyncio.to_thread(_go)
    elif mode in ("off", "unmute"):

        def _go2() -> None:
            _sync_windows_set_muted(False)

        await asyncio.to_thread(_go2)
    else:

        def _toggle() -> None:
            m = _sync_windows_get_muted()
            _sync_windows_set_muted(not m)

        await asyncio.to_thread(_toggle)


# --- Public API ---


def _warn_ignored_sink(params: dict[str, Any]) -> None:
    if params.get("sink"):
        logger.warning("sound.volume*: 'sink' is only used on Linux (pactl/wpctl); ignored on this OS")


async def set_output_volume_percent(params: dict[str, Any], percent: float) -> None:
    plat = sys.platform
    if plat == "darwin":
        _warn_ignored_sink(params)
        await _macos_set_volume_percent(percent)
        return
    if plat == "win32":
        _warn_ignored_sink(params)
        await _windows_set_volume_percent(percent)
        return
    backend = _pick_linux_backend()
    sp, sw = _sink_tokens_linux(params)
    await _linux_set_volume_percent(percent, backend, sp, sw)


async def get_output_volume_percent(params: dict[str, Any]) -> float:
    plat = sys.platform
    if plat == "darwin":
        _warn_ignored_sink(params)
        return await _macos_get_volume_percent()
    if plat == "win32":
        _warn_ignored_sink(params)
        return await _windows_get_volume_percent()
    backend = _pick_linux_backend()
    sp, sw = _sink_tokens_linux(params)
    return await _linux_get_volume_percent(backend, sp, sw)


async def delta_output_volume(params: dict[str, Any], delta: float) -> None:
    if delta == 0:
        return
    current = await get_output_volume_percent(params)
    new_vol = max(0.0, min(current + delta, SYSTEM_VOLUME_MAX_PERCENT))
    await set_output_volume_percent(params, new_vol)
    logger.debug(
        "sound.volume_delta %+g (was %s%% -> %s%%)",
        delta,
        current,
        new_vol,
    )


async def mute_output(params: dict[str, Any], mode: str) -> None:
    m = str(mode).strip().lower()
    if m not in ("toggle", "mute", "unmute", "on", "off"):
        raise ValueError("sound.mute_toggle mode must be toggle, mute, or unmute")
    plat = sys.platform
    if plat == "darwin":
        _warn_ignored_sink(params)
        await _macos_mute(m)
        return
    if plat == "win32":
        _warn_ignored_sink(params)
        await _windows_mute(m)
        return
    backend = _pick_linux_backend()
    sp, sw = _sink_tokens_linux(params)
    if m in ("on", "mute"):
        lm = "mute"
    elif m in ("off", "unmute"):
        lm = "unmute"
    else:
        lm = "toggle"
    await _linux_mute(lm, backend, sp, sw)
