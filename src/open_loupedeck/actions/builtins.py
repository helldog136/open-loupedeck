"""Built-in actions: OBS, HTTP, local sound, shell commands."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

import httpx

from ..platform_volume import (
    SYSTEM_VOLUME_MAX_PERCENT,
    delta_output_volume,
    mute_output,
    set_output_volume_percent,
)
from .registry import ActionContext, register_action

logger = logging.getLogger(__name__)


@register_action("obs.set_scene")
class ObsSetScene:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        scene = params.get("scene")
        if not scene:
            raise ValueError("obs.set_scene requires 'scene'")
        obs = ctx.obs
        if obs is None:
            raise RuntimeError("OBS is not configured (obs section missing in config)")
        target = str(scene)
        await obs.set_current_program_scene(target)
        # Explicit verification: some setups can ack without actually switching (permissions/race).
        cur = await obs.get_current_program_scene()
        if cur and cur != target:
            raise RuntimeError(f"OBS did not switch scene (current={cur!r}, target={target!r})")


@register_action("obs.toggle_mute")
class ObsToggleMute:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        name = params.get("input_name") or params.get("input")
        if not name:
            raise ValueError("obs.toggle_mute requires input_name")
        obs = ctx.obs
        if obs is None:
            raise RuntimeError("OBS is not configured")
        await obs.toggle_input_mute(str(name))


def _obs_input_name(params: dict[str, Any]) -> str:
    name = params.get("input_name") or params.get("input")
    if not name:
        raise ValueError("obs input action requires input_name (audio source name in OBS)")
    return str(name)


def _mul_to_percent(mul: float) -> float:
    """Map OBS inputVolumeMul to an approximate 0–100 slider value."""

    m = float(mul)
    if m <= 1.0:
        return max(0.0, min(100.0, m * 100.0))
    return 100.0


def _percent_to_mul(pct: float) -> float:
    return max(0.0, min(1.0, float(pct) / 100.0))


@register_action("obs.input_volume_set")
class ObsInputVolumeSet:
    """Set an OBS audio source volume (0–100%, same idea as system volume)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        raw = params.get("percent")
        if raw is None:
            raw = params.get("volume")
        if raw is None:
            raise ValueError("obs.input_volume_set requires percent (0–100)")
        obs = ctx.obs
        if obs is None:
            raise RuntimeError("OBS is not configured")
        pct = max(0.0, min(100.0, float(raw)))
        name = _obs_input_name(params)
        await obs.set_input_volume_mul(name, _percent_to_mul(pct))


@register_action("obs.input_volume_delta")
class ObsInputVolumeDelta:
    """Raise or lower an OBS audio source volume by N percentage points (0–100 scale)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        raw = params.get("delta") if params.get("delta") is not None else params.get("step")
        if raw is None:
            raise ValueError("obs.input_volume_delta requires delta (e.g. 5 or -5)")
        delta = float(raw)
        if delta == 0:
            return
        obs = ctx.obs
        if obs is None:
            raise RuntimeError("OBS is not configured")
        name = _obs_input_name(params)
        data = await obs.get_input_volume(name)
        mul = float(data.get("inputVolumeMul") or 0)
        pct = _mul_to_percent(mul)
        new_pct = max(0.0, min(100.0, pct + delta))
        await obs.set_input_volume_mul(name, _percent_to_mul(new_pct))


def _ha_client(ctx: ActionContext) -> Any:
    ha = ctx.ha
    if ha is None:
        raise RuntimeError("Home Assistant is not configured (ha section missing in config)")
    return ha


def _ha_entity_id(params: dict[str, Any]) -> str:
    entity_id = params.get("entity_id") or params.get("entity")
    if not entity_id:
        raise ValueError("entity_id is required (e.g. light.living_room)")
    return str(entity_id)


def _ha_service_data(params: dict[str, Any]) -> dict[str, Any]:
    data = params.get("data")
    return dict(data) if isinstance(data, dict) else {}


@register_action("ha.turn_on")
class HaTurnOn:
    """Generic ``homeassistant.turn_on``: works for lights, switches, fans, scenes, etc.

    Optional ``data`` (JSON object) is forwarded as extra service fields — e.g. for a light:
    ``{"brightness_pct": 60, "rgb_color": [255, 120, 0]}``.
    """

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        ha = _ha_client(ctx)
        entity_id = _ha_entity_id(params)
        await ha.call_service("homeassistant", "turn_on", entity_id, _ha_service_data(params))


@register_action("ha.turn_off")
class HaTurnOff:
    """Generic ``homeassistant.turn_off``: works for lights, switches, fans, scenes, etc."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        ha = _ha_client(ctx)
        entity_id = _ha_entity_id(params)
        await ha.call_service("homeassistant", "turn_off", entity_id, _ha_service_data(params))


@register_action("ha.toggle")
class HaToggle:
    """Generic ``homeassistant.toggle``: works for lights, switches, fans, etc."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        ha = _ha_client(ctx)
        entity_id = _ha_entity_id(params)
        await ha.call_service("homeassistant", "toggle", entity_id, _ha_service_data(params))


@register_action("ha.run_script")
class HaRunScript:
    """Runs a Home Assistant script by object id (``my_script``) or full entity id (``script.my_script``)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        ha = _ha_client(ctx)
        script = params.get("script") or params.get("entity_id")
        if not script:
            raise ValueError("ha.run_script requires 'script' (object id or script.<id> entity id)")
        entity_id = str(script) if str(script).startswith("script.") else f"script.{script}"
        await ha.call_service("script", "turn_on", entity_id, _ha_service_data(params))


@register_action("ha.call_service")
class HaCallService:
    """Fully generic Home Assistant service call: any domain/service, e.g. automation.trigger,
    scene.turn_on, cover.open_cover, climate.set_temperature."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        ha = _ha_client(ctx)
        domain = params.get("domain")
        service = params.get("service")
        if not domain or not service:
            raise ValueError("ha.call_service requires 'domain' and 'service'")
        entity_id = params.get("entity_id") or params.get("entity")
        target = str(entity_id) if entity_id else None
        await ha.call_service(str(domain), str(service), target, _ha_service_data(params))


@register_action("http.request")
class HttpRequest:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        url = params.get("url")
        if not url:
            raise ValueError("http.request requires url")
        method = str(params.get("method", "GET")).upper()
        headers = params.get("headers") or {}
        body = params.get("body")
        json_body = params.get("json")
        timeout = float(params.get("timeout", 15.0))
        client: httpx.AsyncClient = ctx.http_client
        if json_body is not None:
            r = await client.request(method, str(url), headers=headers, json=json_body, timeout=timeout)
        else:
            r = await client.request(method, str(url), headers=headers, content=body, timeout=timeout)
        r.raise_for_status()
        logger.debug("HTTP %s %s -> %s", method, url, r.status_code)


def _resolve_sound_file(path: str, config_dir: Path | None) -> str:
    raw = Path(path).expanduser()
    if raw.is_absolute():
        return str(raw)
    if config_dir is not None:
        base = Path(config_dir)
        cand = (base / raw).resolve()
        if cand.is_file():
            return str(cand)
    return str(raw)


@register_action("sound.volume_set")
class SoundVolumeSet:
    """Set default output volume (Linux: pactl/wpctl; macOS: AppleScript; Windows: pycaw)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        raw = params.get("percent")
        if raw is None:
            raw = params.get("volume")
        if raw is None:
            raise ValueError(f"sound.volume_set requires percent (0–{int(SYSTEM_VOLUME_MAX_PERCENT)})")
        percent = float(raw)
        await set_output_volume_percent(params, percent)


@register_action("sound.volume_delta")
class SoundVolumeDelta:
    """Raise or lower default output volume by N percent points."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        raw = params.get("delta") if params.get("delta") is not None else params.get("step")
        if raw is None:
            raise ValueError("sound.volume_delta requires delta (e.g. 5 or -5)")
        delta = float(raw)
        await delta_output_volume(params, delta)


@register_action("sound.mute_toggle")
class SoundMuteToggle:
    """Toggle, mute, or unmute the default output."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        mode = str(params.get("mode", "toggle")).strip().lower()
        if mode not in ("toggle", "mute", "unmute", "on", "off"):
            raise ValueError("sound.mute_toggle mode must be toggle, mute, or unmute")
        await mute_output(params, mode)
        logger.debug("sound.mute_toggle %s", mode)


@register_action("sound.play")
class SoundPlay:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        path = params.get("file") or params.get("path")
        if not path:
            raise ValueError("sound.play requires file")
        resolved = _resolve_sound_file(str(path), ctx.config_dir)
        player = str(params.get("player", "auto"))
        cmd = _resolve_player_command(player, resolved)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            msg = err.decode(errors="replace") if err else ""
            raise RuntimeError(f"sound player exited {proc.returncode}: {msg}")


def _resolve_player_command(player: str, path: str) -> list[str]:
    if player == "auto":
        names: list[str] = []
        if sys.platform == "darwin":
            names.append("afplay")
        names.extend(["mpv", "paplay", "aplay", "ffplay"])
        for name in names:
            p = shutil.which(name)
            if p:
                if name == "mpv":
                    return [p, "--no-video", "--really-quiet", path]
                if name == "ffplay":
                    return [p, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                return [p, path]
        extra = " On Windows/macOS install mpv or FFmpeg (ffplay), or on macOS rely on afplay."
        raise RuntimeError("No supported player found (mpv, ffplay, paplay, aplay, afplay)." + extra)
    exe = shutil.which(player) or player
    return [exe, path]


@register_action("display.live_message")
class DisplayLiveMessage:
    """Label is updated by the agent from template/HTTP; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("display.clock")
class DisplayClock:
    """Local time + date on two lines; updated by the agent; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("display.twitch_live")
class DisplayTwitchLive:
    """Twitch Helix stream status on the key; updated by the agent; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("display.obs_stream")
class DisplayObsStream:
    """OBS stream output status on the key; updated by the agent; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("display.obs_scene")
class DisplayObsScene:
    """Current OBS program scene name; updated by the agent; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("display.battery")
class DisplayBattery:
    """Host battery level / AC; updated by the agent; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("display.ha_sensor")
class DisplayHaSensor:
    """Home Assistant entity state on the key; updated by the agent; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("display.ha_weather")
class DisplayHaWeather:
    """Home Assistant weather entity on the key; updated by the agent; button press has no effect."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        return None


@register_action("agent.next_page")
class AgentNextPage:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        nav = ctx.pages
        if nav is None:
            raise RuntimeError("agent.next_page requires pages in config")
        await nav.next_page()


@register_action("agent.prev_page")
class AgentPrevPage:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        nav = ctx.pages
        if nav is None:
            raise RuntimeError("agent.prev_page requires pages in config")
        await nav.prev_page()


@register_action("agent.goto_page")
class AgentGotoPage:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        nav = ctx.pages
        if nav is None:
            raise RuntimeError("agent.goto_page requires pages in config")
        idx = params.get("index")
        name = params.get("name")
        page_id = params.get("id") if params.get("id") is not None else params.get("page_id")
        if idx is None and name is None and page_id is None:
            raise ValueError("agent.goto_page needs index, name, or id")
        await nav.goto_page(
            index=int(idx) if idx is not None else None,
            name=str(name) if name is not None else None,
            page_id=str(page_id) if page_id is not None else None,
        )


@register_action("command.run")
class CommandRun:
    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        argv = params.get("argv")
        shell = params.get("shell")
        if argv and shell:
            raise ValueError("command.run: use either argv or shell, not both")
        if shell:
            proc = await asyncio.create_subprocess_shell(
                str(shell),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        elif argv:
            proc = await asyncio.create_subprocess_exec(
                *[str(x) for x in argv],
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            raise ValueError("command.run requires argv (list) or shell (string)")
        _, err = await proc.communicate()
        if proc.returncode != 0:
            msg = err.decode(errors="replace") if err else ""
            raise RuntimeError(f"command exited {proc.returncode}: {msg}")
