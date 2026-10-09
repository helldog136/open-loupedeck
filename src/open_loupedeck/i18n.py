"""Internationalisation: flat JSON locale files, ``{var}`` interpolation, simple plurals.

Locale files live in ``locales/<code>.json`` (flat ``section.sub.name`` keys). ``en.json`` is the
source of truth; every other file is a translation. A plural message has ``key.one`` and
``key.other`` variants and is selected by passing ``count=<n>`` to :func:`t`.

Lookup never raises: requested language -> English -> the key itself.
"""

from __future__ import annotations

import json
import locale
import logging
import os
import re
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .package_paths import package_root

logger = logging.getLogger(__name__)

SOURCE_LANGUAGE = "en"
META_NAME_KEY = "_meta.name"
_VAR_RE = re.compile(r"\{(\w+)\}")
# Languages where 0 and 1 are both "one" (French, Portuguese...); languages without plural forms.
_ZERO_IS_ONE = {"fr", "pt"}
_NO_PLURAL = {"ja", "zh", "ko", "vi", "th", "id"}

_lock = threading.RLock()
_cache: dict[str, dict[str, str]] = {}
_current = SOURCE_LANGUAGE
_listeners: list[Callable[[str], None]] = []


def locales_dir() -> Path:
    return package_root() / "locales"


def _load_file(code: str) -> dict[str, str]:
    with _lock:
        cached = _cache.get(code)
        if cached is not None:
            return cached
        data: dict[str, str] = {}
        path = locales_dir() / f"{code}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {str(k): v for k, v in raw.items() if isinstance(v, str)}
        except FileNotFoundError:
            pass
        except Exception:
            logger.warning("Could not read locale file %s", path, exc_info=True)
        _cache[code] = data
        return data


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def available_languages() -> list[dict[str, str]]:
    """``[{"code": "en", "name": "English"}, ...]`` (English first, then by code)."""

    out: list[dict[str, str]] = []
    try:
        files = sorted(locales_dir().glob("*.json"))
    except OSError:
        files = []
    for p in files:
        code = p.stem
        name = _load_file(code).get(META_NAME_KEY) or code
        out.append({"code": code, "name": name})
    out.sort(key=lambda d: (d["code"] != SOURCE_LANGUAGE, d["code"]))
    return out


def _match_code(candidate: str, codes: list[str]) -> str | None:
    cand = candidate.strip().replace("_", "-").split(".")[0].split("@")[0].lower()
    if not cand:
        return None
    by_lower = {c.lower(): c for c in codes}
    if cand in by_lower:
        return by_lower[cand]
    return by_lower.get(cand.split("-")[0])


def detect_os_language() -> str | None:
    """Best-effort OS UI language tag such as ``fr_FR`` or ``en-US``; None if unknown."""

    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
                return buf.value
        except Exception:
            logger.debug("GetUserDefaultLocaleName failed", exc_info=True)
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v and v not in ("C", "POSIX"):
            return v
    try:
        lang = locale.getlocale()[0]
        if lang:
            return lang
    except Exception:
        logger.debug("locale.getlocale failed", exc_info=True)
    return None


def resolve_language(config_value: Any = "auto") -> str:
    """Map a config ``language`` value (``auto`` or a code) to an available language code."""

    codes = [d["code"] for d in available_languages()]
    value = str(config_value or "auto").strip()
    if value.lower() != "auto":
        return _match_code(value, codes) or SOURCE_LANGUAGE
    try:
        detected = detect_os_language()
    except Exception:
        detected = None
    if detected:
        hit = _match_code(detected, codes)
        if hit:
            return hit
    return SOURCE_LANGUAGE


def get_language() -> str:
    with _lock:
        return _current


def set_language(config_value: Any = "auto") -> str:
    """Resolve and make it the process-wide current language; notifies listeners on change."""

    global _current
    code = resolve_language(config_value)
    with _lock:
        changed = code != _current
        _current = code
        listeners = list(_listeners)
    if changed:
        for fn in listeners:
            try:
                fn(code)
            except Exception:
                logger.debug("i18n listener failed", exc_info=True)
    return code


def set_language_from_raw(raw: dict[str, Any] | None) -> str:
    return set_language((raw or {}).get("language", "auto"))


def on_language_change(fn: Callable[[str], None]) -> None:
    with _lock:
        _listeners.append(fn)


def messages_for(code: str) -> dict[str, str]:
    """Flat dict for ``code`` with English merged underneath for any missing key."""

    merged = dict(_load_file(SOURCE_LANGUAGE))
    if code != SOURCE_LANGUAGE:
        merged.update({k: v for k, v in _load_file(code).items() if v})
    return merged


def plural_category(code: str, n: float) -> str:
    primary = code.split("-")[0].lower()
    if primary in _NO_PLURAL:
        return "other"
    if primary in _ZERO_IS_ONE:
        return "one" if 0 <= n < 2 else "other"
    return "one" if n == 1 else "other"


def _interpolate(template: str, values: dict[str, Any]) -> str:
    return _VAR_RE.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


def _lookup(code: str, key: str, values: dict[str, Any]) -> str | None:
    msgs = _load_file(code)
    if "count" in values:
        try:
            cat = plural_category(code, float(values["count"]))
        except (TypeError, ValueError):
            cat = "other"
        for k in (f"{key}.{cat}", f"{key}.other"):
            if msgs.get(k):
                return msgs[k]
    return msgs.get(key) or None


def t(key: str, lang: str | None = None, **vars: Any) -> str:
    """Translate ``key``. Falls back requested -> English -> the key itself; never raises."""

    try:
        code = lang if lang else get_language()
        for candidate in (code, SOURCE_LANGUAGE):
            text = _lookup(candidate, key, vars)
            if text is not None:
                return _interpolate(text, vars)
    except Exception:
        logger.debug("i18n lookup failed for %r", key, exc_info=True)
    return key
