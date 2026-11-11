"""Device screen brightness: day level, optional night window, debounced persistence.

Config (top level of ``config.yaml``)::

    brightness: 80                 # 0-100, used outside the night window
    brightness_night:
      enabled: false
      from: "22:00"                # the window may cross midnight
      to: "07:00"
      level: 20

:class:`DeckBrightness` owns the runtime behaviour. The pure helpers (``clamp_level``,
``normalize_night``, ``in_window``) need no device. Time sources are injectable so the logic is
testable with a fake clock.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime, time
from time import monotonic
from typing import Any

from .devices.base import device_model_of

logger = logging.getLogger(__name__)

DEFAULT_LEVEL = 80
DEFAULT_NIGHT: dict[str, Any] = {"enabled": False, "from": "22:00", "to": "07:00", "level": 20}
PERSIST_DEBOUNCE_SEC = 1.0
REEVALUATE_SEC = 30.0


def clamp_level(value: Any, default: int = DEFAULT_LEVEL) -> int:
    """An int in 0..100; junk (None, text, bool, NaN) gives ``default``."""

    if isinstance(value, bool):
        return default
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if n != n or n in (float("inf"), float("-inf")):
        return default
    return max(0, min(100, round(n)))


def parse_hhmm(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return time(h, m)


def _fmt(tm: time) -> str:
    return f"{tm.hour:02d}:{tm.minute:02d}"


def normalize_night(value: Any) -> dict[str, Any]:
    """A complete, valid ``brightness_night`` mapping; invalid parts fall back to the defaults."""

    src = value if isinstance(value, dict) else {}
    d = DEFAULT_NIGHT
    start = parse_hhmm(src.get("from")) or parse_hhmm(d["from"])
    end = parse_hhmm(src.get("to")) or parse_hhmm(d["to"])
    return {
        "enabled": src.get("enabled") is True,
        "from": _fmt(start),  # type: ignore[arg-type]
        "to": _fmt(end),  # type: ignore[arg-type]
        "level": clamp_level(src.get("level"), d["level"]),
    }


def in_window(now: time, start: time, end: time) -> bool:
    """True when ``now`` is in ``[start, end)``; crosses midnight when ``start > end``; empty if equal."""

    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


class DeckBrightness:
    """Holds the brightness settings, applies them to ``runtime.deck`` (the device backend) and persists changes."""

    def __init__(
        self,
        runtime: Any,
        persist: Callable[[int, dict[str, Any]], None] | None = None,
        *,
        level: Any = DEFAULT_LEVEL,
        night: Any = None,
        now: Callable[[], datetime] = datetime.now,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._runtime = runtime
        self._persist = persist
        self._now = now
        self._clock = clock
        self.level = clamp_level(level)
        self.night = normalize_night(night)
        self._dirty_since: float | None = None
        self._last_eval = clock()
        self._last_applied: int | None = None

    # --- settings -------------------------------------------------------------------------

    def load_from_raw(self, raw: dict[str, Any]) -> None:
        self.level = clamp_level(raw.get("brightness"))
        self.night = normalize_night(raw.get("brightness_night"))

    def snapshot(self) -> dict[str, Any]:
        return {"brightness": self.level, "brightness_night": dict(self.night)}

    def night_active(self, now: datetime | None = None) -> bool:
        if not self.night["enabled"]:
            return False
        cur = (now or self._now()).time()
        return in_window(cur, parse_hhmm(self.night["from"]), parse_hhmm(self.night["to"]))  # type: ignore[arg-type]

    def effective_level(self, now: datetime | None = None) -> int:
        return self.night["level"] if self.night_active(now) else self.level

    # --- device ---------------------------------------------------------------------------

    def apply(self) -> int:
        """Send the effective level to the current device (no device / device errors are ignored)."""

        level = self.effective_level()
        self._last_applied = level
        deck = getattr(self._runtime, "deck", None)
        model = device_model_of(deck)
        if model is not None and not model.brightness:
            return level
        if deck is not None and hasattr(deck, "set_brightness"):
            try:
                deck.set_brightness(level)
            except Exception:
                logger.debug("Could not set brightness", exc_info=True)
        return level

    # --- changes --------------------------------------------------------------------------

    def set(self, pct: Any, period: str | None = None) -> int:
        """Set a level. ``period``: ``day``, ``night`` or ``None`` (the period active right now)."""

        value = clamp_level(pct, self.effective_level())
        if period is None:
            period = "night" if self.night_active() else "day"
        if period == "night":
            self.night["level"] = value
        else:
            self.level = value
        self._changed()
        return self.apply()

    def delta(self, n: Any) -> int:
        """Move the active period's level by ``n`` points (clamped); returns the new effective level."""

        try:
            step = round(float(n))
        except (TypeError, ValueError):
            return self.effective_level()
        return self.set(self.effective_level() + step)

    def update_night(self, night: Any) -> int:
        """Merge a partial ``brightness_night`` mapping (invalid parts keep their current value)."""

        merged = dict(self.night)
        if isinstance(night, dict):
            for key in ("enabled", "from", "to", "level"):
                if key in night:
                    merged[key] = night[key]
            if parse_hhmm(merged["from"]) is None:
                merged["from"] = self.night["from"]
            if parse_hhmm(merged["to"]) is None:
                merged["to"] = self.night["to"]
            if isinstance(merged["level"], bool):
                merged["level"] = self.night["level"]
        self.night = normalize_night(merged)
        self._changed()
        return self.apply()

    # --- persistence + background loop ----------------------------------------------------

    def _changed(self) -> None:
        self._dirty_since = self._clock()

    def tick(self) -> None:
        """Flush a due debounced save and re-evaluate the night window every 30 s."""

        now = self._clock()
        if self._dirty_since is not None and now - self._dirty_since >= PERSIST_DEBOUNCE_SEC:
            self.flush()
        if now - self._last_eval >= REEVALUATE_SEC:
            self._last_eval = now
            if self.effective_level() != self._last_applied:
                self.apply()

    def flush(self) -> None:
        if self._dirty_since is None:
            return
        self._dirty_since = None
        if self._persist is not None:
            try:
                self._persist(self.level, dict(self.night))
            except Exception:
                logger.exception("Could not save brightness")

    async def run(self, interval: float = 0.5) -> None:
        """Background loop (cancel it to stop); flushes pending changes on the way out."""

        try:
            while True:
                await asyncio.sleep(interval)
                self.tick()
        finally:
            with contextlib.suppress(Exception):
                self.flush()


def make_deck_brightness(state: Any, runtime: Any) -> DeckBrightness:
    """Controller bound to a ``ConfigState``; saves go straight to the config file."""

    from .config_io import save_raw_config

    def persist(level: int, night: dict[str, Any]) -> None:
        raw = dict(state.raw)
        raw["brightness"] = level
        raw["brightness_night"] = night
        save_raw_config(state.path, raw)
        state.raw = raw

    return DeckBrightness(runtime, persist, level=state.raw.get("brightness"), night=state.raw.get("brightness_night"))
