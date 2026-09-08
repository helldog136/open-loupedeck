"""YAML configuration loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ObsConfig:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""


@dataclass
class HaConfig:
    """Home Assistant REST API (long-lived access token, no OAuth)."""

    base_url: str = ""
    token: str = ""


@dataclass
class DeviceConfig:
    """Serial path, optional baud, and hardware model (see README)."""

    path: str = ""
    baudrate: int | None = None
    model: str = "auto"


@dataclass
class Settings:
    obs: ObsConfig | None = None
    ha: HaConfig | None = None
    device: DeviceConfig = field(default_factory=DeviceConfig)
    bindings: list[dict[str, Any]] = field(default_factory=list)
    """Multi-page layout: each page has name + buttons map (see README). When non-empty, used instead of bindings."""

    pages: list[dict[str, Any]] = field(default_factory=list)
    """Absolute paths to extra Python files that register actions (see examples/custom_action.py)."""

    plugin_modules: list[str] = field(default_factory=list)


def load_config(path: Path) -> Settings:
    from .config_io import load_raw_config, raw_to_settings

    return raw_to_settings(load_raw_config(path))
