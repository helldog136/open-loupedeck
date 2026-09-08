"""Central logging: console + rotating file under XDG state (or config dir)."""

from __future__ import annotations

import logging
import logging.config
import os
import sys
from pathlib import Path
from typing import Any

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def default_log_dir() -> Path:
    """Rotating log directory (per-OS conventional location)."""

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local).expanduser().resolve() / "open-loupedeck" / "logs"
        return Path.home() / "AppData" / "Local" / "open-loupedeck" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "open-loupedeck"
    state = os.environ.get("XDG_STATE_HOME")
    base = Path(state) if state else Path.home() / ".local" / "state"
    return base / "open-loupedeck" / "logs"


def default_icon_cache_dir() -> Path:
    """Downloaded SVG icon cache."""

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local).expanduser().resolve() / "open-loupedeck" / "icons"
        return Path.home() / "AppData" / "Local" / "open-loupedeck" / "icons"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "open-loupedeck" / "icons"
    c = os.environ.get("XDG_CACHE_HOME")
    base = Path(c) if c else Path.home() / ".cache"
    return base / "open-loupedeck" / "icons"


def _parse_level(name: str | None) -> int:
    if not name:
        return logging.INFO
    mapping = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
    }
    return mapping.get(str(name).strip().upper(), logging.INFO)


def bootstrap_logging(
    *,
    verbose: bool,
    log_dir_override: Path | None,
    file_enabled: bool,
    console_enabled: bool,
    level_from_config: str | None,
    raw: dict[str, Any] | None = None,
) -> Path | None:
    """
    Configure root logging once (call before uvicorn; pass uvicorn log_config=None).

    Returns the directory used for log files, or None if file logging is disabled.
    """
    section = (raw or {}).get("logging") or {}
    if not isinstance(section, dict):
        section = {}

    dir_str = section.get("dir")
    resolved_dir: Path
    if log_dir_override is not None:
        resolved_dir = log_dir_override.expanduser().resolve()
    elif isinstance(dir_str, str) and dir_str.strip():
        resolved_dir = Path(dir_str).expanduser().resolve()
    else:
        resolved_dir = default_log_dir()

    file_on = bool(section.get("file", True)) if file_enabled else False
    console_on = bool(section.get("console", True)) if console_enabled else False

    cfg_level = _parse_level(
        level_from_config or (section.get("level") if isinstance(section.get("level"), str) else None)
    )

    file_level = logging.DEBUG if verbose else cfg_level
    console_level = logging.DEBUG if verbose else cfg_level
    root_level = logging.DEBUG if verbose else cfg_level

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.handlers.clear()

    if not file_on and not console_on:
        logging.basicConfig(
            level=root_level,
            format=_LOG_FORMAT,
            datefmt=_DATE_FORMAT,
        )
        _quiet_external(verbose, root_level)
        return None

    if not file_on:
        logging.basicConfig(
            level=console_level,
            format=_LOG_FORMAT,
            datefmt=_DATE_FORMAT,
        )
        root.setLevel(root_level)
        _quiet_external(verbose, root_level)
        logging.getLogger(__name__).info("Logging: console only (level=%s)", logging.getLevelName(root_level))
        return None

    resolved_dir.mkdir(parents=True, exist_ok=True)

    handlers: list[str] = []
    h_cfg: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"std": {"format": _LOG_FORMAT, "datefmt": _DATE_FORMAT}},
        "handlers": {},
        "loggers": {},
    }

    if console_on:
        h_cfg["handlers"]["console"] = {
            "class": "logging.StreamHandler",
            "formatter": "std",
            "level": console_level,
        }
        handlers.append("console")

    log_file = resolved_dir / "open-loupedeck.log"
    err_file = resolved_dir / "open-loupedeck-errors.log"
    h_cfg["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "std",
        "level": file_level,
        "filename": str(log_file),
        "maxBytes": 10 * 1024 * 1024,
        "backupCount": 8,
        "encoding": "utf-8",
    }
    h_cfg["handlers"]["errors"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "std",
        "level": logging.WARNING,
        "filename": str(err_file),
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 5,
        "encoding": "utf-8",
    }
    handlers.extend(["file", "errors"])

    hx_level = logging.DEBUG if verbose else logging.WARNING
    h_cfg["loggers"] = {
        "httpx": {"level": hx_level, "handlers": handlers, "propagate": False},
        "httpcore": {"level": hx_level, "handlers": handlers, "propagate": False},
    }

    h_cfg["root"] = {
        "handlers": handlers,
        "level": root_level,
    }

    logging.config.dictConfig(h_cfg)
    _quiet_external(verbose, root_level)
    logging.getLogger(__name__).info(
        "Logging initialized dir=%s root=%s verbose=%s console=%s files=%s %s",
        resolved_dir,
        logging.getLevelName(root_level),
        verbose,
        console_on,
        log_file.name,
        err_file.name,
    )
    return resolved_dir


def reapply_logging_from_config(
    raw: dict[str, Any],
    *,
    verbose: bool,
    log_dir_override: Path | None,
) -> Path | None:
    """
    Re-run :func:`bootstrap_logging` after the YAML changes (e.g. web UI saved ``logging.level``).

    Preserves CLI ``verbose`` and ``--log-dir`` behavior from process startup.
    """

    return bootstrap_logging(
        verbose=verbose,
        log_dir_override=log_dir_override,
        file_enabled=True,
        console_enabled=True,
        level_from_config=None,
        raw=raw,
    )


def _quiet_external(verbose: bool, root_level: int) -> None:
    """
    Tune noisy third-party loggers.

    **Uvicorn:** ``uvicorn.error`` stays at INFO so lifecycle (startup/shutdown, connection closed)
    remains visible at the default app level. Per-request **access** lines use logger ``uvicorn.access``
    at INFO from Starlette; we raise that logger's level to WARNING when ``root_level`` is INFO (or
    higher) so routine ``GET /api/…`` lines only appear when logging is DEBUG (or ``-v``).
    """

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    if verbose or root_level <= logging.DEBUG:
        logging.getLogger("uvicorn.access").setLevel(logging.DEBUG)
    else:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    if verbose:
        return
    for name in ("asyncio", "urllib3", "PIL"):
        logging.getLogger(name).setLevel(logging.WARNING)


def load_raw_for_logging(config_path: Path) -> dict[str, Any]:
    """Load YAML for logging bootstrap before full ConfigState (best-effort)."""
    try:
        if config_path.is_file():
            from .config_io import load_raw_config

            return dict(load_raw_config(config_path))
    except Exception:
        logging.getLogger(__name__).debug("load_raw_for_logging: could not read %s", config_path, exc_info=True)
    return {}
