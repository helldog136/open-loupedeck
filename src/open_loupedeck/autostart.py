"""Enable/disable launching the tray app when the user logs in (per OS).

Windows: a ``HKCU\\...\\Run`` registry value (no admin rights needed).
macOS: a LaunchAgent plist under ``~/Library/LaunchAgents``.
Linux: an XDG autostart ``.desktop`` file under ``~/.config/autostart``.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_APP_NAME = "open-loupedeck"
_WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_MACOS_LAUNCH_AGENT_LABEL = "com.open-loupedeck.agent"


def _launch_argv() -> list[str]:
    """Command to relaunch this program, whether running from source or a frozen build."""

    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "open_loupedeck.tray_app"]


# --- Windows -----------------------------------------------------------------


def _windows_command_line() -> str:
    return " ".join(f'"{part}"' for part in _launch_argv())


def _windows_is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except FileNotFoundError:
        return False


def _windows_set_enabled(enabled: bool) -> None:
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _windows_command_line())
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, _APP_NAME)


# --- macOS ---------------------------------------------------------------------


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_MACOS_LAUNCH_AGENT_LABEL}.plist"


def _macos_is_enabled() -> bool:
    return _macos_plist_path().is_file()


def _macos_set_enabled(enabled: bool) -> None:
    path = _macos_plist_path()
    if not enabled:
        if path.is_file():
            subprocess.run(["launchctl", "unload", "-w", str(path)], check=False, capture_output=True)
            path.unlink(missing_ok=True)
        return

    argv = _launch_argv()
    program_args = "\n".join(f"        <string>{arg}</string>" for arg in argv)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_MACOS_LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{program_args}
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist)
    subprocess.run(["launchctl", "load", "-w", str(path)], check=False, capture_output=True)


# --- Linux (XDG autostart) ------------------------------------------------------


def _linux_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / f"{_APP_NAME}.desktop"


def _linux_is_enabled() -> bool:
    return _linux_desktop_path().is_file()


def _linux_set_enabled(enabled: bool) -> None:
    path = _linux_desktop_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return

    exec_line = " ".join(_launch_argv())
    entry = f"""[Desktop Entry]
Type=Application
Name=open-loupedeck
Exec={exec_line}
X-GNOME-Autostart-enabled=true
NoDisplay=false
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry)


# --- Public API ------------------------------------------------------------------


def is_enabled() -> bool:
    try:
        if sys.platform == "win32":
            return _windows_is_enabled()
        if sys.platform == "darwin":
            return _macos_is_enabled()
        return _linux_is_enabled()
    except Exception:
        logger.exception("autostart.is_enabled failed")
        return False


def set_enabled(enabled: bool) -> None:
    try:
        if sys.platform == "win32":
            _windows_set_enabled(enabled)
        elif sys.platform == "darwin":
            _macos_set_enabled(enabled)
        else:
            _linux_set_enabled(enabled)
        logger.info("autostart %s", "enabled" if enabled else "disabled")
    except Exception:
        logger.exception("autostart.set_enabled(%s) failed", enabled)
