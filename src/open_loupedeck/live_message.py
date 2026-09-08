"""Resolve ``display.live_message`` / ``live_message`` templates (HTTP + page context)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .control_ids import is_page_scoped_control
from .obs_stream_status import fetch_obs_stream_fields
from .platform_battery import read_battery_info
from .twitch_helix import (
    fetch_stream_fields_for_login,
    normalize_twitch_login_params,
)
from .twitch_helix import (
    offline_fields as twitch_offline_fields,
)

logger = logging.getLogger(__name__)

LIVE_MESSAGE_ACTION = "display.live_message"
CLOCK_ACTION = "display.clock"
TWITCH_LIVE_ACTION = "display.twitch_live"
OBS_STREAM_ACTION = "display.obs_stream"
OBS_SCENE_ACTION = "display.obs_scene"
BATTERY_ACTION = "display.battery"
HA_SENSOR_ACTION = "display.ha_sensor"
HA_WEATHER_ACTION = "display.ha_weather"
# How often to re-fetch HTTP URLs for display buttons (seconds).
DEFAULT_HTTP_REFRESH_INTERVAL_SEC = 60.0
DEFAULT_OBS_STREAM_INTERVAL_SEC = 5.0
DEFAULT_OBS_SCENE_INTERVAL_SEC = 2.0
DEFAULT_BATTERY_INTERVAL_SEC = 30.0
DEFAULT_HA_SENSOR_INTERVAL_SEC = 30.0
DEFAULT_HA_WEATHER_INTERVAL_SEC = 300.0


def obs_interval_seconds_from_params(params: dict[str, Any]) -> float:
    """Poll interval for OBS stream status (local WebSocket)."""

    for key in ("interval_seconds", "refresh_seconds", "interval"):
        if key not in params or params[key] is None:
            continue
        try:
            v = float(params[key])
        except (TypeError, ValueError):
            logger.warning("display.obs_stream: invalid %s=%r", key, params[key])
            continue
        return max(2.0, min(120.0, v))
    return DEFAULT_OBS_STREAM_INTERVAL_SEC


def obs_scene_interval_seconds_from_params(params: dict[str, Any]) -> float:
    """Poll interval for OBS current scene name."""

    for key in ("interval_seconds", "refresh_seconds", "interval"):
        if key not in params or params[key] is None:
            continue
        try:
            v = float(params[key])
        except (TypeError, ValueError):
            logger.warning("display.obs_scene: invalid %s=%r", key, params[key])
            continue
        return max(0.5, min(30.0, v))
    return DEFAULT_OBS_SCENE_INTERVAL_SEC


def battery_interval_seconds_from_params(params: dict[str, Any]) -> float:
    """Poll interval for host battery display."""

    for key in ("interval_seconds", "refresh_seconds", "interval"):
        if key not in params or params[key] is None:
            continue
        try:
            v = float(params[key])
        except (TypeError, ValueError):
            logger.warning("display.battery: invalid %s=%r", key, params[key])
            continue
        return max(5.0, min(600.0, v))
    return DEFAULT_BATTERY_INTERVAL_SEC


def ha_sensor_interval_seconds_from_params(params: dict[str, Any]) -> float:
    """Poll interval for a Home Assistant entity's state (sensor, binary_sensor, light, etc.)."""

    for key in ("interval_seconds", "refresh_seconds", "interval"):
        if key not in params or params[key] is None:
            continue
        try:
            v = float(params[key])
        except (TypeError, ValueError):
            logger.warning("display.ha_sensor: invalid %s=%r", key, params[key])
            continue
        return max(5.0, min(3600.0, v))
    return DEFAULT_HA_SENSOR_INTERVAL_SEC


def ha_weather_interval_seconds_from_params(params: dict[str, Any]) -> float:
    """Poll interval for a Home Assistant weather entity."""

    for key in ("interval_seconds", "refresh_seconds", "interval"):
        if key not in params or params[key] is None:
            continue
        try:
            v = float(params[key])
        except (TypeError, ValueError):
            logger.warning("display.ha_weather: invalid %s=%r", key, params[key])
            continue
        return max(30.0, min(3600.0, v))
    return DEFAULT_HA_WEATHER_INTERVAL_SEC


def interval_seconds_from_params(params: dict[str, Any]) -> float:
    """Refresh period for HTTP-backed templates. Default 60s. Aliases: ``refresh_seconds``, ``interval``."""

    for key in ("interval_seconds", "refresh_seconds", "http_refresh_seconds", "interval"):
        if key not in params or params[key] is None:
            continue
        try:
            v = float(params[key])
        except (TypeError, ValueError):
            logger.warning("live_message: invalid %s=%r, trying next key", key, params[key])
            continue
        return max(5.0, min(3600.0, v))
    return DEFAULT_HTTP_REFRESH_INTERVAL_SEC


def live_message_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return params dict if this key should show a live-updating message."""

    lm = entry.get("live_message")
    if isinstance(lm, dict) and str(lm.get("template") or "").strip():
        return dict(lm)
    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == LIVE_MESSAGE_ACTION:
        p = {k: v for k, v in act.items() if k != "type"}
        return p if str(p.get("template") or "").strip() else None
    return None


def clock_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Return params (possibly empty) if this key shows the clock overlay."""

    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == CLOCK_ACTION:
        return {k: v for k, v in act.items() if k != "type"}
    return None


def twitch_live_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Params for Twitch stream status overlay (Helix)."""

    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == TWITCH_LIVE_ACTION:
        return {k: v for k, v in act.items() if k != "type"}
    return None


def obs_stream_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Params for OBS stream status overlay (GetStreamStatus)."""

    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == OBS_STREAM_ACTION:
        return {k: v for k, v in act.items() if k != "type"}
    return None


def obs_scene_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Params for OBS current program scene name (GetCurrentProgramScene)."""

    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == OBS_SCENE_ACTION:
        return {k: v for k, v in act.items() if k != "type"}
    return None


def battery_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Params for host battery / AC display."""

    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == BATTERY_ACTION:
        return {k: v for k, v in act.items() if k != "type"}
    return None


def ha_sensor_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Params for a Home Assistant entity state display (``display.ha_sensor``)."""

    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == HA_SENSOR_ACTION:
        return {k: v for k, v in act.items() if k != "type"}
    return None


def ha_weather_params_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Params for a Home Assistant weather entity display (``display.ha_weather``)."""

    act = entry.get("action")
    if isinstance(act, dict) and act.get("type") == HA_WEATHER_ACTION:
        return {k: v for k, v in act.items() if k != "type"}
    return None


def dynamic_display_overlay_entry(entry: dict[str, Any]) -> bool:
    """True if the key uses agent-driven overlay text (live message or clock)."""

    return bool(
        live_message_params_from_entry(entry)
        or clock_params_from_entry(entry) is not None
        or twitch_live_params_from_entry(entry) is not None
        or obs_stream_params_from_entry(entry) is not None
        or obs_scene_params_from_entry(entry) is not None
        or battery_params_from_entry(entry) is not None
        or ha_sensor_params_from_entry(entry) is not None
        or ha_weather_params_from_entry(entry) is not None
    )


def _append_entry_slots(
    out: list[tuple[str, str, dict[str, Any]]],
    prefix: str,
    cid: str,
    entry: dict[str, Any],
) -> None:
    if not isinstance(entry, dict):
        return
    tp = twitch_live_params_from_entry(entry)
    if tp is not None:
        out.append((f"{prefix}{cid}", "twitch_live", tp))
        return
    op = obs_stream_params_from_entry(entry)
    if op is not None:
        out.append((f"{prefix}{cid}", "obs_stream", op))
        return
    sp = obs_scene_params_from_entry(entry)
    if sp is not None:
        out.append((f"{prefix}{cid}", "obs_scene", sp))
        return
    bp = battery_params_from_entry(entry)
    if bp is not None:
        out.append((f"{prefix}{cid}", "battery", bp))
        return
    hsp = ha_sensor_params_from_entry(entry)
    if hsp is not None:
        out.append((f"{prefix}{cid}", "ha_sensor", hsp))
        return
    hwp = ha_weather_params_from_entry(entry)
    if hwp is not None:
        out.append((f"{prefix}{cid}", "ha_weather", hwp))
        return
    p = live_message_params_from_entry(entry)
    if p:
        out.append((f"{prefix}{cid}", "live_message", p))
        return
    cp = clock_params_from_entry(entry)
    if cp is not None:
        out.append((f"{prefix}{cid}", "clock", cp))


def _now_for_clock(params: dict[str, Any]) -> datetime:
    tz_name = str(params.get("timezone") or "").strip()
    if tz_name:
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            logger.warning("display.clock: invalid timezone %r, using local time", tz_name)
    return datetime.now().astimezone()


def format_clock_overlay_text(params: dict[str, Any]) -> str:
    """Two lines: time then date (``strftime`` formats, local time unless ``timezone`` is set)."""

    now = _now_for_clock(params)
    tf = str(params.get("time_format") or "%H:%M").strip() or "%H:%M"
    df = str(params.get("date_format") or "%a %d %b").strip() or "%a %d %b"
    return f"{now.strftime(tf)}\n{now.strftime(df)}"


def iter_dynamic_display_slots(
    raw: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any]]]:
    """``(storage_key, kind, params)`` for display overlays (HTTP, clock, Twitch, OBS)."""

    out: list[tuple[str, str, dict[str, Any]]] = []
    pages = raw.get("pages") or []
    if not isinstance(pages, list):
        return out
    for pi, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        bt = page.get("buttons") or {}
        if not isinstance(bt, dict):
            continue
        for cid, entry in bt.items():
            _append_entry_slots(out, f"p{pi}:", cid, entry)
    gb = raw.get("global_buttons") or {}
    if isinstance(gb, dict):
        for cid, entry in gb.items():
            _append_entry_slots(out, "g:", cid, entry)
    return out


def _get_json_path(obj: Any, path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                idx = int(part)
            except ValueError:
                return None
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return None
        else:
            return None
    return cur


def _extract_from_body(
    body: str,
    mode: str,
    json_path: str | None,
    regex_pattern: str | None,
) -> str:
    mode = (mode or "text").strip().lower()
    if mode == "json":
        if not json_path:
            return ""
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.debug("live_message: response is not JSON")
            return ""
        v = _get_json_path(data, json_path.strip())
        if v is None:
            return ""
        return str(v).strip()
    if mode == "regex":
        if not regex_pattern:
            return ""
        try:
            m = re.search(regex_pattern, body, re.DOTALL)
        except re.error:
            logger.exception("live_message: bad regex")
            return ""
        if not m:
            return ""
        if m.lastindex:
            return str(m.group(1)).strip()
        return str(m.group(0)).strip()
    # text: body
    s = body.strip()
    return s[:2000] if len(s) > 2000 else s


def _substitute_template(template: str, mapping: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        return mapping.get(key, m.group(0))

    return re.sub(r"\{(\w+)\}", repl, template)


def prune_stale_live_message_keys(raw: dict[str, Any], runtime: Any) -> bool:
    """Drop runtime caches for controls that no longer have a live message in ``raw``.

    Returns True if anything was removed.
    """

    valid = {k for k, _, _ in iter_dynamic_display_slots(raw)}
    changed = False
    for d in (
        runtime.live_message_text,
        runtime.live_message_http_value,
        runtime.live_message_last_fetch,
    ):
        for k in list(d.keys()):
            if k not in valid:
                del d[k]
                changed = True
    return changed


def _page_context(raw: dict[str, Any], page_index: int) -> dict[str, str]:
    pages = raw.get("pages") or []
    if not isinstance(pages, list) or len(pages) == 0:
        return {
            "page_name": "",
            "page_index": "0",
            "page_number": "1",
            "page_count": "0",
        }
    n = len(pages)
    idx = page_index % n
    page = pages[idx] if isinstance(pages[idx], dict) else {}
    name = str(page.get("name") or "").strip()
    return {
        "page_name": name,
        "page_index": str(idx),
        "page_number": str(idx + 1),
        "page_count": str(n),
    }


def _ha_sensor_fields(entity_id: str, state: dict[str, Any] | None) -> dict[str, str]:
    if state is None:
        return {"state": "—", "unit": "", "name": entity_id}
    attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    unit = str(attrs.get("unit_of_measurement") or "").strip()
    name = str(attrs.get("friendly_name") or entity_id).strip()
    value = str(state.get("state") or "—")
    return {"state": value, "unit": unit, "name": name}


def _ha_weather_fields(entity_id: str, state: dict[str, Any] | None) -> dict[str, str]:
    if state is None:
        return {
            "condition": "—",
            "temperature": "—",
            "temperature_unit": "",
            "humidity": "—",
            "wind_speed": "—",
            "name": entity_id,
        }
    attrs = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
    name = str(attrs.get("friendly_name") or entity_id).strip()
    return {
        "condition": str(state.get("state") or "—"),
        "temperature": str(attrs.get("temperature") if attrs.get("temperature") is not None else "—"),
        "temperature_unit": str(attrs.get("temperature_unit") or ""),
        "humidity": str(attrs.get("humidity") if attrs.get("humidity") is not None else "—"),
        "wind_speed": str(attrs.get("wind_speed") if attrs.get("wind_speed") is not None else "—"),
        "name": name,
    }


async def refresh_live_messages(
    raw: dict[str, Any],
    page_index: int,
    runtime: Any,
    http_client: httpx.AsyncClient,
    log: logging.Logger,
    obs: Any | None = None,
    ha: Any | None = None,
) -> bool:
    """
    Update ``runtime.live_message_text`` (and HTTP caches). Returns True if any displayed string changed.
    """

    slots = iter_dynamic_display_slots(raw)
    changed = prune_stale_live_message_keys(raw, runtime)
    if not slots:
        return changed

    now = time.monotonic()
    page_ctx = _page_context(raw, page_index)
    raw_dict = dict(raw)

    async def _fetch_one(key: str, params: dict[str, Any]) -> tuple[str, str]:
        """Returns (storage_key, http_fragment)."""

        url = str(params.get("url") or "").strip()
        timeout = float(params.get("timeout") or 15.0)
        timeout = max(3.0, min(120.0, timeout))
        headers: dict[str, str] = {}
        raw_h = params.get("headers")
        if isinstance(raw_h, dict):
            headers = {str(k): str(v) for k, v in raw_h.items()}
        mode = str(params.get("extract_mode") or params.get("extract") or "text")
        if isinstance(mode, dict):
            mode = str(mode.get("kind") or "text")
        json_path = params.get("json_path")
        if isinstance(json_path, (int, float)):
            json_path = str(int(json_path))
        elif json_path is not None:
            json_path = str(json_path)
        regex_pattern = params.get("regex")
        if regex_pattern is not None:
            regex_pattern = str(regex_pattern)
        try:
            r = await http_client.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            body = r.text
            http_val = _extract_from_body(
                body,
                str(mode),
                json_path,
                regex_pattern,
            )
            with contextlib.suppress(Exception):
                if hasattr(runtime, "set_control_error"):
                    runtime.set_control_error(key, None)
            return key, http_val
        except Exception:
            log.debug("live_message fetch failed for %s", key, exc_info=True)
            with contextlib.suppress(Exception):
                if hasattr(runtime, "set_control_error"):
                    runtime.set_control_error(key, "URL refresh failed")
            return key, runtime.live_message_http_value.get(key, "—")

    # Parallel HTTP fetches for slots that are due (independent URLs).
    due_fetches: list[asyncio.Task[tuple[str, str]]] = []
    for key, kind, params in slots:
        if kind != "live_message":
            continue
        url = str(params.get("url") or "").strip()
        if not url:
            continue
        interval = interval_seconds_from_params(params)
        last = runtime.live_message_last_fetch.get(key, 0.0)
        need_fetch = (now - last >= interval) or (key not in runtime.live_message_http_value)
        if need_fetch:
            due_fetches.append(asyncio.create_task(_fetch_one(key, params)))

    if due_fetches:
        results = await asyncio.gather(*due_fetches, return_exceptions=True)
        for res in results:
            if isinstance(res, tuple) and len(res) == 2:
                key, http_val = res
                runtime.live_message_http_value[key] = http_val
                runtime.live_message_last_fetch[key] = now
            else:
                log.debug("live_message gather task failed: %r", res)

    # Twitch Helix: refresh per streamer login (shared across keys).
    twitch_logins_due: list[str] = []
    for _key, kind, params in slots:
        if kind != "twitch_live":
            continue
        login = normalize_twitch_login_params(params)
        if not login:
            continue
        interval = interval_seconds_from_params(params)
        last = float(runtime.twitch_stream_last_fetch.get(login, 0.0))
        need = (now - last >= interval) or (login not in runtime.twitch_stream_by_login)
        if need:
            twitch_logins_due.append(login)

    for login in sorted(set(twitch_logins_due)):
        try:
            fields = await fetch_stream_fields_for_login(http_client, raw_dict, runtime, login)
            runtime.twitch_stream_by_login[login] = fields
            runtime.twitch_stream_last_fetch[login] = now
        except Exception:
            log.debug("twitch fetch failed for %r", login, exc_info=True)
            runtime.twitch_stream_by_login[login] = twitch_offline_fields(login)
            runtime.twitch_stream_last_fetch[login] = now

    # OBS GetStreamStatus (one poll for all obs_stream keys).
    obs_interval = DEFAULT_OBS_STREAM_INTERVAL_SEC
    has_obs_slot = False
    for _key, kind, params in slots:
        if kind == "obs_stream":
            has_obs_slot = True
            obs_interval = min(obs_interval, obs_interval_seconds_from_params(params))

    if has_obs_slot:
        last_obs = float(getattr(runtime, "obs_stream_last_fetch", 0.0) or 0.0)
        need_obs = (now - last_obs >= obs_interval) or not getattr(runtime, "obs_stream_vars", None)
        if need_obs:
            try:
                runtime.obs_stream_vars = await fetch_obs_stream_fields(obs)
            except Exception:
                log.debug("obs stream status fetch failed", exc_info=True)
                runtime.obs_stream_vars = await fetch_obs_stream_fields(None)
            runtime.obs_stream_last_fetch = now

    # OBS current program scene name (one poll for all obs_scene keys).
    scene_interval = DEFAULT_OBS_SCENE_INTERVAL_SEC
    has_scene_slot = False
    for _key, kind, params in slots:
        if kind == "obs_scene":
            has_scene_slot = True
            scene_interval = min(scene_interval, obs_scene_interval_seconds_from_params(params))

    if has_scene_slot:
        last_scene = float(getattr(runtime, "obs_scene_last_fetch", 0.0) or 0.0)
        need_scene = (now - last_scene >= scene_interval) or not getattr(runtime, "obs_scene_name", "")
        if need_scene:
            try:
                if obs is None:
                    raise RuntimeError("OBS is not configured")
                runtime.obs_scene_name = await obs.get_current_program_scene()
            except Exception:
                log.debug("obs current scene fetch failed", exc_info=True)
                runtime.obs_scene_name = ""
            runtime.obs_scene_last_fetch = now

    # Host battery / AC (one poll for all display.battery keys).
    batt_interval = DEFAULT_BATTERY_INTERVAL_SEC
    has_battery_slot = False
    for _key, kind, params in slots:
        if kind == "battery":
            has_battery_slot = True
            batt_interval = min(batt_interval, battery_interval_seconds_from_params(params))

    if has_battery_slot:
        last_batt = float(getattr(runtime, "battery_last_fetch", 0.0) or 0.0)
        need_batt = (now - last_batt >= batt_interval) or last_batt <= 0.0
        if need_batt:
            try:
                fields = await asyncio.to_thread(read_battery_info)
                if isinstance(fields, dict):
                    runtime.battery_fields = {str(k): str(v) for k, v in fields.items()}
                else:
                    runtime.battery_fields = {}
            except Exception:
                log.debug("battery read failed", exc_info=True)
                runtime.battery_fields = {
                    "battery_percent": "—",
                    "battery_percent_raw": "",
                    "battery_status": "Unknown",
                    "battery_ac": "?",
                }
            runtime.battery_last_fetch = now

    # Home Assistant entity state (one poll per distinct entity_id, shared across all keys).
    ha_sensor_entities_due: set[str] = set()
    for _key, kind, params in slots:
        if kind != "ha_sensor":
            continue
        entity_id = str(params.get("entity_id") or params.get("entity") or "").strip()
        if not entity_id:
            continue
        interval = ha_sensor_interval_seconds_from_params(params)
        last = float(runtime.ha_sensor_last_fetch.get(entity_id, 0.0))
        if (now - last >= interval) or entity_id not in runtime.ha_sensor_by_entity:
            ha_sensor_entities_due.add(entity_id)

    for entity_id in sorted(ha_sensor_entities_due):
        try:
            if ha is None:
                raise RuntimeError("Home Assistant is not configured")
            state = await ha.get_state(entity_id)
            runtime.ha_sensor_by_entity[entity_id] = _ha_sensor_fields(entity_id, state)
        except Exception:
            log.debug("ha_sensor fetch failed for %r", entity_id, exc_info=True)
            runtime.ha_sensor_by_entity[entity_id] = _ha_sensor_fields(entity_id, None)
        runtime.ha_sensor_last_fetch[entity_id] = now

    # Home Assistant weather entity (one poll per distinct entity_id).
    ha_weather_entities_due: set[str] = set()
    for _key, kind, params in slots:
        if kind != "ha_weather":
            continue
        entity_id = str(params.get("entity_id") or params.get("entity") or "").strip()
        if not entity_id:
            continue
        interval = ha_weather_interval_seconds_from_params(params)
        last = float(runtime.ha_weather_last_fetch.get(entity_id, 0.0))
        if (now - last >= interval) or entity_id not in runtime.ha_weather_by_entity:
            ha_weather_entities_due.add(entity_id)

    for entity_id in sorted(ha_weather_entities_due):
        try:
            if ha is None:
                raise RuntimeError("Home Assistant is not configured")
            state = await ha.get_state(entity_id)
            runtime.ha_weather_by_entity[entity_id] = _ha_weather_fields(entity_id, state)
        except Exception:
            log.debug("ha_weather fetch failed for %r", entity_id, exc_info=True)
            runtime.ha_weather_by_entity[entity_id] = _ha_weather_fields(entity_id, None)
        runtime.ha_weather_last_fetch[entity_id] = now

    for key, kind, params in slots:
        if kind == "clock":
            text = format_clock_overlay_text(params)
            if len(text) > 500:
                text = text[:497] + "…"
            if runtime.live_message_text.get(key) != text:
                runtime.live_message_text[key] = text
                changed = True
            continue

        if kind == "twitch_live":
            login = normalize_twitch_login_params(params)
            tmpl = str(params.get("template") or "{twitch_status}\n{twitch_uptime}")
            if not login:
                fields = twitch_offline_fields("—")
            else:
                fields = runtime.twitch_stream_by_login.get(login) or twitch_offline_fields(login)
            mapping = {**page_ctx, **fields}
            text = _substitute_template(tmpl, mapping).strip()
            if len(text) > 500:
                text = text[:497] + "…"
            if runtime.live_message_text.get(key) != text:
                runtime.live_message_text[key] = text
                changed = True
            continue

        if kind == "obs_stream":
            tmpl = str(params.get("template") or "{obs_status}\n{obs_duration}")
            fields = dict(getattr(runtime, "obs_stream_vars", None) or {})
            mapping = {**page_ctx, **fields}
            text = _substitute_template(tmpl, mapping).strip()
            if len(text) > 500:
                text = text[:497] + "…"
            if runtime.live_message_text.get(key) != text:
                runtime.live_message_text[key] = text
                changed = True
            continue

        if kind == "obs_scene":
            tmpl = str(params.get("template") or "{obs_scene}")
            scene = str(getattr(runtime, "obs_scene_name", "") or "—").strip() or "—"
            mapping = {**page_ctx, "obs_scene": scene, "scene": scene}
            text = _substitute_template(tmpl, mapping).strip()
            if len(text) > 500:
                text = text[:497] + "…"
            if runtime.live_message_text.get(key) != text:
                runtime.live_message_text[key] = text
                changed = True
            continue

        if kind == "battery":
            tmpl = str(params.get("template") or "{battery_percent}\n{battery_status}")
            bf = getattr(runtime, "battery_fields", None)
            if not isinstance(bf, dict):
                bf = {}
            mapping = {**page_ctx, **bf}
            text = _substitute_template(tmpl, mapping).strip()
            if len(text) > 500:
                text = text[:497] + "…"
            if runtime.live_message_text.get(key) != text:
                runtime.live_message_text[key] = text
                changed = True
            continue

        if kind == "ha_sensor":
            entity_id = str(params.get("entity_id") or params.get("entity") or "").strip()
            tmpl = str(params.get("template") or "{state}{unit}")
            fields = dict(runtime.ha_sensor_by_entity.get(entity_id) or {"state": "—", "unit": "", "name": entity_id})
            mapping = {**page_ctx, **fields}
            text = _substitute_template(tmpl, mapping).strip()
            if len(text) > 500:
                text = text[:497] + "…"
            if runtime.live_message_text.get(key) != text:
                runtime.live_message_text[key] = text
                changed = True
            continue

        if kind == "ha_weather":
            entity_id = str(params.get("entity_id") or params.get("entity") or "").strip()
            tmpl = str(params.get("template") or "{condition}\n{temperature}{temperature_unit}")
            fields = dict(
                runtime.ha_weather_by_entity.get(entity_id)
                or {
                    "condition": "—",
                    "temperature": "—",
                    "temperature_unit": "",
                    "humidity": "—",
                    "wind_speed": "—",
                    "name": entity_id,
                }
            )
            mapping = {**page_ctx, **fields}
            text = _substitute_template(tmpl, mapping).strip()
            if len(text) > 500:
                text = text[:497] + "…"
            if runtime.live_message_text.get(key) != text:
                runtime.live_message_text[key] = text
                changed = True
            continue

        if kind != "live_message":
            continue

        template = str(params.get("template") or "")
        url = str(params.get("url") or "").strip()
        http_val = ""
        if url:
            http_val = runtime.live_message_http_value.get(key, "")

        mapping = {
            **page_ctx,
            "http": http_val,
            "value": http_val,
        }
        text = _substitute_template(template, mapping).strip()
        if len(text) > 500:
            text = text[:497] + "…"

        if runtime.live_message_text.get(key) != text:
            runtime.live_message_text[key] = text
            changed = True

    return changed


def overlay_text_for_control(
    control_id: str,
    page_index: int,
    live_text: dict[str, str] | None,
) -> str | None:
    if not live_text:
        return None
    if is_page_scoped_control(control_id):
        return live_text.get(f"p{page_index}:{control_id}")
    return live_text.get(f"g:{control_id}")


def preview_storage_key(control_id: str, page_index: int) -> str:
    if is_page_scoped_control(control_id):
        return f"p{page_index}:{control_id}"
    return f"g:{control_id}"
