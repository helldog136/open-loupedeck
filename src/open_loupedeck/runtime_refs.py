"""Mutable handles shared between the agent loop and the web UI (read-only from HTTP)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentRuntimeRefs:
    """Loupedeck device and OBS session owned by the asyncio agent; updated after startup.

    ``deck_unplugged`` is set when the serial reader thread exits due to disconnect; the reconnect
    loop clears it after a successful ``_open_deck``. ``intentional_deck_shutdown`` blocks that
    loop during normal process exit.
    """

    deck: Any | None = None
    deck_unplugged: bool = False
    intentional_deck_shutdown: bool = False
    obs: Any | None = None
    ha: Any | None = None
    no_device: bool = False
    knob_page_indices: dict[str, int] = field(default_factory=dict)
    live_message_text: dict[str, str] = field(default_factory=dict)
    live_message_http_value: dict[str, str] = field(default_factory=dict)
    live_message_last_fetch: dict[str, float] = field(default_factory=dict)
    twitch_bearer_token: str = ""
    twitch_bearer_expires_at: float = 0.0
    twitch_stream_by_login: dict[str, dict[str, str]] = field(default_factory=dict)
    twitch_stream_last_fetch: dict[str, float] = field(default_factory=dict)
    obs_stream_vars: dict[str, str] = field(default_factory=dict)
    obs_stream_last_fetch: float = 0.0
    obs_scene_name: str = ""
    obs_scene_last_fetch: float = 0.0
    # Home Assistant: cached fields per entity_id, shared across all keys showing that entity.
    ha_sensor_by_entity: dict[str, dict[str, str]] = field(default_factory=dict)
    ha_sensor_last_fetch: dict[str, float] = field(default_factory=dict)
    ha_weather_by_entity: dict[str, dict[str, str]] = field(default_factory=dict)
    ha_weather_last_fetch: dict[str, float] = field(default_factory=dict)
    # Monotonic counter for multi-frame key graphics (GIF / video-derived GIF); incremented by skin_animation_loop.
    skin_animation_tick: int = 0
    # Cached strings for display.battery (refreshed together on interval).
    battery_fields: dict[str, str] = field(default_factory=dict)
    battery_last_fetch: float = 0.0
    # Broadcasts to OBS overlay browser sources (WebSocket).
    overlay_hub: Any | None = None
    # CLI -v; when True, reapply_logging keeps DEBUG on handlers.
    startup_verbose: bool = False
    # CLI --log-dir; overrides logging.dir in YAML when set.
    log_dir_override: Path | None = None
    # Set by run_agent: dispatch one synthetic device message (test press from web UI).
    simulate_raw_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    # UI health markers: storage_key -> short reason (touch keys use "p{page}:touch_N").
    control_error: dict[str, str] = field(default_factory=dict)
    control_error_updated_at: dict[str, float] = field(default_factory=dict)
    # control_id -> skin_animation_tick at the moment of press, for a control's `press_animation`.
    # skin_animation_loop prunes entries older than button_render.PRESS_ANIMATION_DURATION_TICKS.
    press_animation_start: dict[str, int] = field(default_factory=dict)

    def set_control_error(self, storage_key: str, reason: str | None) -> None:
        """Set/clear a red-outline marker for the UI."""

        key = str(storage_key or "").strip()
        if not key:
            return
        now = time.monotonic()
        if reason is None or str(reason).strip() == "":
            if key in self.control_error:
                self.control_error.pop(key, None)
                self.control_error_updated_at[key] = now
            return
        self.control_error[key] = str(reason).strip()
        self.control_error_updated_at[key] = now
