"""Mutable config + page index shared between agent and web UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import Settings
from .config_backup import create_rotating_backup
from .config_io import (
    default_raw_config,
    ensure_minimal_structure,
    load_raw_config,
    raw_to_settings,
    save_raw_config,
)
from .config_paths import ensure_application_dirs
from .media_library import materialize_external_media

logger = logging.getLogger(__name__)


class ConfigState:
    def __init__(self, path: Path) -> None:
        self.path = path
        ensure_application_dirs(path)
        if path.is_file():
            try:
                create_rotating_backup(path)
            except Exception:
                # Best-effort: a snapshot "as of this session's start" is a nice-to-have safety
                # net (see Ctrl+Z for in-session undo), never a reason to fail startup.
                logger.debug("Startup backup snapshot failed for %s", path, exc_info=True)
            raw = ensure_minimal_structure(load_raw_config(path))
            raw, changed = materialize_external_media(raw, path.parent.resolve())
            if changed:
                save_raw_config(path, raw)
                logger.info("Copied external media into %s/library/", path.parent)
            self.raw: dict[str, Any] = ensure_minimal_structure(raw)
        else:
            self.raw = default_raw_config()
            save_raw_config(path, self.raw)
        self.page_index: int = 0

    def settings(self) -> Settings:
        return raw_to_settings(self.raw)

    def reload_from_disk(self) -> None:
        if self.path.is_file():
            raw = ensure_minimal_structure(load_raw_config(self.path))
            raw, changed = materialize_external_media(raw, self.path.parent.resolve())
            if changed:
                save_raw_config(self.path, raw)
            self.raw = ensure_minimal_structure(raw)

    def replace_raw(self, raw: dict[str, Any]) -> None:
        self.raw = ensure_minimal_structure(raw)
        logger.info("Config updated in memory (pages=%s)", len(self.raw.get("pages") or []))
