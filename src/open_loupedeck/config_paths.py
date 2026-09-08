"""Per-OS application config directory (XDG on Linux, %APPDATA% on Windows, Application Support on macOS)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# App name segment under the per-OS config root.
APP_CONFIG_DIR_NAME = "open-loupedeck"


def user_config_dir() -> Path:
    """Directory containing ``config.yaml`` (e.g. ``%APPDATA%\\open-loupedeck`` on Windows)."""

    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base).expanduser().resolve() / APP_CONFIG_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / APP_CONFIG_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_CONFIG_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser().resolve() / APP_CONFIG_DIR_NAME
    return Path.home() / ".config" / APP_CONFIG_DIR_NAME


def default_config_path() -> Path:
    """Default config file path for the current OS."""

    return user_config_dir() / "config.yaml"


def ensure_application_dirs(config_path: Path) -> Path:
    """Create config parent, ``library/images|videos|sounds|fonts``, and ``assets`` (legacy uploads)."""

    root = config_path.parent.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "library" / "images").mkdir(parents=True, exist_ok=True)
    (root / "library" / "videos").mkdir(parents=True, exist_ok=True)
    (root / "library" / "sounds").mkdir(parents=True, exist_ok=True)
    (root / "library" / "fonts").mkdir(parents=True, exist_ok=True)
    (root / "library" / "generated" / "key_video_gif").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    return root
