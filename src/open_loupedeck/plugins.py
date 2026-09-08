"""Load optional user Python modules that register custom actions."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_plugin_files(paths: list[str]) -> None:
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            logger.error("Plugin file not found: %s", path)
            continue
        name = f"loupedeck_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            logger.error("Could not load plugin spec for %s", path)
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception:
            logger.exception("Failed to load plugin %s", path)
        else:
            logger.info("Loaded plugin module %s", path)
