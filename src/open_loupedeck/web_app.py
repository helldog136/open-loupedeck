"""Browser UI to edit pages, buttons, actions, and upload images."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import mimetypes
import re
import subprocess
import sys
import uuid
import webbrowser
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import autostart, sound_library, sound_player, wow_icons
from .action_catalog import merged_catalog
from .button_render import (
    PreviewCache,
    key_size_for_control,
    preview_cache_key,
    render_key_preview,
)
from .config_backup import create_rotating_backup, list_backups, restore_backup, wipe_backups
from .config_io import default_raw_config, ensure_minimal_structure, save_raw_config
from .config_migrate import UI_MODEL_KEY, config_version, from_ui_view, to_ui_view
from .config_paths import ensure_application_dirs
from .config_state import ConfigState
from .control_ids import control_to_legacy_id, to_control_id
from .deck_brightness import make_deck_brightness, parse_hhmm
from .devices.base import device_model_of
from .devices.model import DeviceModel, control_kind_from_id
from .devices.registry import config_model, default_model, force_model, known_models, model_by_name
from .devices.virtual.transport import handle_virtual_socket, virtual_backend_of
from .i18n import available_languages, get_language, messages_for, resolve_language, set_language_from_raw, t
from .knob_duos import list_duos
from .knob_roles import validate_knobs_config
from .live_message import (
    battery_params_from_entry,
    clock_params_from_entry,
    format_clock_overlay_text,
    ha_sensor_params_from_entry,
    ha_weather_params_from_entry,
    live_message_params_from_entry,
    obs_scene_params_from_entry,
    obs_stream_params_from_entry,
    offline_fallback_mode,
    offline_fallback_text,
    preview_storage_key,
    prune_stale_live_message_keys,
    twitch_live_params_from_entry,
)
from .logging_setup import default_icon_cache_dir, reapply_logging_from_config
from .look_defaults import proposed_entry, resolve_look
from .media_library import FONT_FILE_EXT, materialize_external_media, prune_unused_library_media
from .package_paths import package_root
from .packs import list_packs
from .runtime_refs import AgentRuntimeRefs
from .simulate_input import build_synthetic_event
from .spotify_client import SpotifyManager
from .twitch_api import DEFAULT_CLIENT_ID, TwitchManager

logger = logging.getLogger(__name__)

SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")

# The config UI is native ES modules (static/js/*.js), which browsers only execute when served with a
# JavaScript MIME type. On Windows, mimetypes reads the registry, where some installers map .js to
# text/plain -- that would leave the UI blank. Pin the standard type.
mimetypes.add_type("text/javascript", ".js")


def _static_dir() -> Path:
    return package_root() / "static"


def ui_model(raw: dict[str, Any], deck: Any = None) -> DeviceModel:
    """Model the current UI lays the deck out for: ``device.model``, else the connected device's
    (``auto``), else the Live S. The legacy-shaped config the UI edits uses its key grid."""

    dev = raw.get("device") if isinstance(raw.get("device"), dict) else {}
    return model_by_name(str(dev.get("model") or "auto")) or device_model_of(deck) or default_model()


def config_for_ui(raw: dict[str, Any], deck: Any = None) -> dict[str, Any]:
    """The config as the current web UI edits it (legacy ids/shape, see ``config_migrate``)."""

    return to_ui_view(raw, ui_model(raw, deck))


def config_from_ui(body: dict[str, Any]) -> dict[str, Any]:
    """A config PUT by a client: version 2 as is; a legacy / UI-view body is converted."""

    if config_version(body) >= 2:
        out = dict(body)
        out.pop(UI_MODEL_KEY, None)
        return out
    return from_ui_view(body)


def _twitch_accounts_from(raw: dict[str, Any]) -> list[dict[str, Any]]:
    t = raw.get("twitch")
    if isinstance(t, list):
        return [a for a in t if isinstance(a, dict)]
    return [dict(t)] if isinstance(t, dict) and t else []


def create_web_app(
    config_path: Path,
    state: ConfigState,
    lock: asyncio.Lock,
    on_refresh: Callable[[], Awaitable[None]] | None = None,
    runtime: AgentRuntimeRefs | None = None,
    spotify: SpotifyManager | None = None,
) -> FastAPI:
    app = FastAPI(title="Open-Loupedeck", version="0.2.0")
    rt: AgentRuntimeRefs = runtime or AgentRuntimeRefs()
    if spotify is not None:
        sp = spotify
    else:
        sp = SpotifyManager(
            config_path.parent / "spotify_tokens.json",
            lambda: dict(state.raw.get("spotify") or {}),
        )
    ensure_application_dirs(config_path)
    config_dir = config_path.parent.resolve()
    if rt.twitch is None:
        rt.twitch = TwitchManager(config_dir / "twitch_tokens.json", lambda: _twitch_accounts_from(state.raw))
    tw: TwitchManager = rt.twitch
    if rt.deck_brightness is None:
        rt.deck_brightness = make_deck_brightness(state, rt)

    @app.middleware("http")
    async def _no_cache(request: Any, call_next: Any) -> Any:
        """This is a local single-user config UI, never a public site: correctness after an app
        update matters far more than caching a few KB of static assets. Without this, a webview's
        disk cache serving a stale index.html, JS module or style.css after an install can look exactly
        like "the fix didn't take" even though the new file is right there on disk."""

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        p = _static_dir() / "index.html"
        if not p.is_file():
            return "<h1>Missing static/index.html</h1>"
        return p.read_text(encoding="utf-8")

    static = _static_dir()
    if static.is_dir():
        app.mount("/assets/ui", StaticFiles(directory=str(static)), name="ui_static")

    @app.get("/overlay", response_class=HTMLResponse)
    async def overlay_page() -> str:
        """Transparent fullscreen page for OBS Browser Source (1920×1080); driven by WebSocket."""

        p = _static_dir() / "overlay.html"
        if not p.is_file():
            return "<!DOCTYPE html><html><body><p>Missing static/overlay.html</p></body></html>"
        return p.read_text(encoding="utf-8")

    @app.websocket("/ws/overlay")
    async def ws_overlay(ws: WebSocket) -> None:
        hub = rt.overlay_hub
        if hub is None:
            await ws.close(code=1011)
            return
        await hub.handle_connection(ws)

    @app.websocket("/ws/virtual")
    async def ws_virtual(ws: WebSocket) -> None:
        await handle_virtual_socket(ws, lambda: rt.deck)

    @app.get("/api/virtual/state")
    async def api_virtual_state() -> JSONResponse:
        """Snapshot of the virtual device (model, images as base64 PNG, LEDs, brightness)."""

        vb = virtual_backend_of(rt.deck)
        if vb is None:
            raise HTTPException(status_code=404, detail="No virtual device is running (start with --virtual)")
        return JSONResponse(vb.snapshot())

    @app.post("/api/virtual/model")
    async def api_virtual_model(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Switch the running virtual device to another virtual model (this run only, config untouched)."""

        vb = virtual_backend_of(rt.deck)
        if vb is None:
            raise HTTPException(status_code=409, detail="No virtual device is running (start with --virtual)")
        wanted = model_by_name(str(body.get("model") or ""))
        if wanted is None or wanted.family != "virtual":
            raise HTTPException(status_code=400, detail="Unknown virtual model")
        if wanted.id != vb.model.id:
            force_model(wanted.id)
            vb.request_unplug()  # the agent's reconnect loop opens the new model
        return JSONResponse({"ok": True, "model": wanted.id})

    @app.get("/api/locales")
    async def api_locales() -> JSONResponse:
        async with lock:
            setting = str(state.raw.get("language") or "auto")
        return JSONResponse(
            {
                "languages": available_languages(),
                "current": get_language(),
                "setting": setting,
                "detected": resolve_language("auto"),
            }
        )

    @app.put("/api/language")
    async def put_language(body: dict[str, Any] = Body(...)) -> JSONResponse:
        value = str(body.get("language") or "").strip()
        known = {d["code"] for d in available_languages()}
        if value != "auto" and value not in known:
            raise HTTPException(400, t("error.unknown_language"))
        async with lock:
            raw = ensure_minimal_structure(dict(state.raw))
            raw["language"] = value
            save_raw_config(config_path, raw)
            state.replace_raw(raw)
        current = set_language_from_raw(raw)
        return JSONResponse({"ok": True, "setting": value, "current": current})

    def _brightness_payload() -> dict[str, Any]:
        ctl = rt.deck_brightness
        return {
            "level": ctl.level,
            "night": dict(ctl.night),
            "effective": ctl.effective_level(),
            "night_active": ctl.night_active(),
        }

    @app.get("/api/brightness")
    async def get_brightness() -> JSONResponse:
        return JSONResponse(_brightness_payload())

    @app.put("/api/brightness")
    async def put_brightness(body: dict[str, Any] = Body(...)) -> JSONResponse:
        ctl = rt.deck_brightness
        if "level" in body:
            lv = body["level"]
            if isinstance(lv, bool) or not isinstance(lv, (int, float)) or not 0 <= lv <= 100:
                raise HTTPException(400, t("error.invalid_brightness_level"))
        night = body.get("night")
        if night is not None:
            if not isinstance(night, dict):
                raise HTTPException(400, t("error.invalid_brightness_night"))
            for key in ("from", "to"):
                if key in night and parse_hhmm(night[key]) is None:
                    raise HTTPException(400, t("error.invalid_brightness_time"))
            lv = night.get("level")
            if "level" in night and (isinstance(lv, bool) or not isinstance(lv, (int, float)) or not 0 <= lv <= 100):
                raise HTTPException(400, t("error.invalid_brightness_level"))
        if "level" in body:
            ctl.set(body["level"], period="day")
        if night is not None:
            ctl.update_night(night)
        ctl.apply()
        return JSONResponse({"ok": True, **_brightness_payload()})

    @app.get("/api/locale/{code}")
    async def api_locale(code: str) -> JSONResponse:
        known = {d["code"] for d in available_languages()}
        if code not in known:
            raise HTTPException(404, t("error.not_found"))
        return JSONResponse(messages_for(code))

    @app.get("/api/status")
    async def api_status() -> JSONResponse:
        async with lock:
            st = state.settings()
            pages_raw = state.raw.get("pages") or []
            page_count = len(pages_raw) if isinstance(pages_raw, list) else 0
            page_index_ui = int(state.page_index) % page_count if page_count > 0 else 0

        if rt.no_device:
            usb = {
                "connected": False,
                "disabled": True,
                "detail": "Disabled (--no-device)",
                "path": None,
            }
        elif rt.deck is None:
            p = (st.device.path or "").strip() or None
            usb = {
                "connected": False,
                "disabled": False,
                "detail": "No device opened",
                "path": p,
            }
        else:
            path = getattr(rt.deck, "path", None)
            usb_ok = bool(getattr(rt.deck, "is_open", False))
            usb = {
                "connected": usb_ok,
                "disabled": False,
                "detail": str(path) if path else "",
                "path": str(path) if path else None,
            }

        obs_block: dict[str, Any]
        if st.obs is None:
            obs_block = {
                "configured": False,
                "connected": False,
                "url": None,
                "detail": "Not in config",
            }
        elif rt.obs is None:
            obs_block = {
                "configured": True,
                "connected": False,
                "url": f"ws://{st.obs.host}:{st.obs.port}",
                "detail": "Starting…",
            }
        else:
            connected = await rt.obs.probe(timeout=5.0)
            obs_block = {
                "configured": True,
                "connected": connected,
                "url": rt.obs.url,
                "detail": rt.obs.url,
            }

        ha_block: dict[str, Any]
        if st.ha is None or not st.ha.base_url or not st.ha.token:
            ha_block = {
                "configured": False,
                "connected": False,
                "url": None,
                "detail": "Not in config",
            }
        elif rt.ha is None:
            ha_block = {
                "configured": True,
                "connected": False,
                "url": st.ha.base_url,
                "detail": "Starting…",
            }
        else:
            connected = await rt.ha.probe(timeout=5.0)
            ha_block = {
                "configured": True,
                "connected": connected,
                "url": rt.ha.base_url,
                "detail": rt.ha.base_url,
            }

        deck_layout: str | None = None
        if rt.deck is not None:
            dm = device_model_of(rt.deck)
            deck_layout = dm.config_name if dm is not None else "live"

        hub = getattr(rt, "overlay_hub", None)
        overlay_paths: dict[str, str] = {"page": "/overlay", "websocket": "/ws/overlay"} if hub is not None else {}

        touch_errors: dict[str, str] = {}
        control_errors: dict[str, str] = {}
        try:
            async with lock:
                view_model = ui_model(state.raw, rt.deck)
            prefix = f"p{int(page_index_ui)}:"
            for k, v in (rt.control_error or {}).items():
                if not isinstance(k, str):
                    continue
                # storage keys: "p{page}:<control id>" (page binding) / "g:<control id>" (global)
                if k.startswith((prefix, "g:")):
                    _, _, cid = k.partition(":")
                    control_errors.setdefault(cid, str(v))
                    lid = control_to_legacy_id(cid, view_model) if control_kind_from_id(cid) == "key" else None
                    if lid is not None and k.startswith(prefix):
                        touch_errors[lid] = str(v)  # the current UI's key ids
        except Exception:
            logger.debug("status: touch_errors build failed", exc_info=True)

        return JSONResponse(
            {
                "usb": usb,
                "obs": obs_block,
                "ha": ha_block,
                "page_index": page_index_ui,
                "page_count": page_count,
                "deck_layout": deck_layout,
                "overlay": overlay_paths,
                "touch_errors": touch_errors,
                "control_errors": control_errors,
            }
        )

    @app.get("/api/device_model")
    async def api_device_model() -> JSONResponse:
        """Descriptor of the connected device, else of the configured ``device.model`` (``auto``: none)."""

        async with lock:
            configured = state.settings().device.model or "auto"
        dm = device_model_of(rt.deck)
        source: str | None = "device" if dm is not None else None
        if dm is None:
            dm = model_by_name(configured)
            source = "config" if dm is not None else None
        # What the config is written for (``auto`` -> Live S): its key grid gives the coordinates.
        cm = config_model(configured)
        return JSONResponse(
            {
                "source": source,
                "connected": rt.deck is not None and bool(getattr(rt.deck, "is_open", False)),
                "configured_model": configured,
                "config_model": cm.id,
                "known_models": [m.id for m in known_models()],
                "models": {m.id: m.to_dict() for m in known_models()},
                "model": dm.to_dict() if dm is not None else None,
            }
        )

    @app.post("/api/open_config_folder")
    async def open_config_folder() -> JSONResponse:
        """Open the config directory in the OS file manager (local, user-initiated action)."""

        folder = config_dir

        def _open() -> None:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])

        try:
            await asyncio.to_thread(_open)
        except Exception as exc:
            raise HTTPException(500, t("error.open_folder", error=exc)) from exc
        return JSONResponse({"ok": True, "path": str(folder)})

    @app.post("/api/wow_icons/clear")
    async def clear_wow_icons() -> JSONResponse:
        """Delete the downloaded World of Warcraft icons (they are fetched again on demand)."""

        removed = await asyncio.to_thread(wow_icons.clear_cache, default_icon_cache_dir())
        preview_cache.clear()
        return JSONResponse({"ok": True, "removed": removed})

    @app.get("/api/autostart")
    async def get_autostart() -> JSONResponse:
        enabled = await asyncio.to_thread(autostart.is_enabled)
        return JSONResponse({"enabled": enabled})

    @app.post("/api/autostart")
    async def post_autostart(body: dict[str, Any] = Body(...)) -> JSONResponse:
        enabled = bool(body.get("enabled"))
        await asyncio.to_thread(autostart.set_enabled, enabled)
        return JSONResponse({"enabled": enabled})

    @app.post("/api/page_index")
    async def post_page_index(body: dict[str, Any]) -> JSONResponse:
        """Set the agent's active page (same as hardware next/prev); refreshes the deck skin."""

        raw = body.get("index")
        if raw is None:
            raise HTTPException(400, t("error.index_required"))
        try:
            ix = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, t("error.index_integer")) from None
        async with lock:
            pages_list = state.raw.get("pages") or []
            if not isinstance(pages_list, list) or len(pages_list) == 0:
                raise HTTPException(400, t("error.no_pages"))
            state.page_index = ix % len(pages_list)
            out_idx = state.page_index
        if on_refresh:
            try:
                await on_refresh()
            except Exception:
                logger.exception("on_refresh failed after page_index change")
                raise HTTPException(500, t("error.refresh_failed")) from None
        return JSONResponse({"ok": True, "page_index": out_idx})

    @app.post("/api/simulate_press")
    async def simulate_press(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Fire the same dispatch path as a hardware press/turn (for testing without the device)."""

        sim = rt.simulate_event
        if sim is None:
            raise HTTPException(503, t("error.simulate_unavailable"))
        cid = str(body.get("control_id") or "").strip()
        raw_dir = body.get("direction")
        direction: str | None = None
        if raw_dir is not None:
            s = str(raw_dir).strip().lower()
            if s in ("left", "right"):
                direction = s
        async with lock:
            sim_model = ui_model(state.raw, rt.deck)  # legacy ids from the UI use its grid
        ev = build_synthetic_event(cid, direction=direction, model=sim_model)
        if ev is None:
            raise HTTPException(
                400,
                t("error.unsupported_control"),
            )
        try:
            await sim(ev)
        except Exception as e:
            logger.exception("simulate_press failed")
            raise HTTPException(500, detail=str(e)) from e
        return JSONResponse({"ok": True})

    @app.get("/api/action_catalog")
    async def action_catalog(
        lang: str | None = Query(None, description="Language code; default = the app's current language"),
    ) -> JSONResponse:
        code = resolve_language(lang) if lang else get_language()
        return JSONResponse({"lang": code, "actions": merged_catalog(code)})

    @app.get("/api/packs")
    async def starter_packs(
        lang: str | None = Query(None, description="Language code; default = the app's current language"),
        model: str | None = Query(None, description="Model id the packs are fitted to; default = the UI's model"),
    ) -> JSONResponse:
        code = resolve_language(lang) if lang else get_language()
        async with lock:
            pm = model_by_name(model) or ui_model(state.raw, rt.deck)
        return JSONResponse({"lang": code, "packs": list_packs(code, pm)})

    @app.get("/api/knob_duos")
    async def knob_duos(
        lang: str | None = Query(None, description="Language code; default = the app's current language"),
    ) -> JSONResponse:
        code = resolve_language(lang) if lang else get_language()
        return JSONResponse({"lang": code, "duos": list_duos(code)})

    @app.post("/api/resolve_look")
    async def post_resolve_look(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Final look (label/icon/colours/mode + proposed|modified source) of a key entry."""

        entry = body.get("entry")
        if not isinstance(entry, dict):
            raise HTTPException(400, "body.entry must be an object")
        lang = body.get("lang")
        return JSONResponse(resolve_look(entry, str(lang) if lang else None))

    @app.get("/api/spotify/status")
    async def spotify_status() -> JSONResponse:
        configured = sp.is_configured()
        connected = sp.has_tokens()
        user: str | None = None
        if configured and connected:
            try:
                async with httpx.AsyncClient() as client:
                    me = await sp.get_me(client)
                user = str(me.get("display_name") or me.get("id") or "") or None
            except Exception:
                logger.debug("spotify status: could not load profile", exc_info=True)
        return JSONResponse(
            {
                "configured": configured,
                "connected": connected,
                "user": user,
            }
        )

    @app.post("/api/spotify/config")
    async def spotify_save_config(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Merge ``client_id`` / ``redirect_uri`` into config ``spotify`` block."""

        out_block: dict[str, Any] = {}
        async with lock:
            raw = ensure_minimal_structure(dict(state.raw))
            block = raw.get("spotify")
            if not isinstance(block, dict):
                block = {}
            for k in ("client_id", "redirect_uri"):
                if k in body and body[k] is not None:
                    block[k] = str(body[k]).strip()
            raw["spotify"] = block
            out_block = dict(block)
            save_raw_config(config_path, raw)
            state.replace_raw(raw)
        return JSONResponse({"ok": True, "spotify": out_block})

    @app.get("/api/spotify/login")
    async def spotify_login() -> RedirectResponse:
        if not sp.is_configured():
            raise HTTPException(
                status_code=400,
                detail=t("error.spotify_not_configured"),
            )
        try:
            url, _state = sp.build_authorize_url()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return RedirectResponse(url=url, status_code=302)

    @app.get("/api/spotify/callback")
    async def spotify_callback(
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> RedirectResponse:
        if error:
            return RedirectResponse(
                url=f"/?spotify_error={quote(error, safe='')}",
                status_code=302,
            )
        if not code or not state:
            return RedirectResponse(url="/?spotify_error=missing_code", status_code=302)
        verifier = sp.pop_verifier_for_state(state)
        if not verifier:
            return RedirectResponse(url="/?spotify_error=invalid_or_expired_state", status_code=302)
        try:
            await sp.exchange_code(code, verifier)
        except Exception as e:
            return RedirectResponse(
                url=f"/?spotify_error={quote(str(e), safe='')}",
                status_code=302,
            )
        return RedirectResponse(url="/?spotify=connected", status_code=302)

    @app.post("/api/spotify/disconnect")
    async def spotify_disconnect() -> JSONResponse:
        sp.clear_tokens()
        return JSONResponse({"ok": True})

    def _twitch_account(ix: Any) -> dict[str, Any]:
        """Account ``ix`` of the config's twitch list; index 0 (built-in app) if none configured."""

        accounts = _twitch_accounts_from(state.raw)
        try:
            i = int(ix)
        except (TypeError, ValueError):
            raise HTTPException(400, t("error.account_index_required")) from None
        if accounts:
            if not 0 <= i < len(accounts):
                raise HTTPException(400, t("error.unknown_twitch_account"))
            return accounts[i]
        if i != 0:
            raise HTTPException(400, t("error.unknown_twitch_account"))
        return {}

    @app.get("/api/twitch/status")
    async def twitch_status() -> JSONResponse:
        accounts = _twitch_accounts_from(state.raw) or [{}]
        rows = [{"index": i, "connected": tw.is_connected(a), "login": tw.login_for(a)} for i, a in enumerate(accounts)]
        return JSONResponse({"builtin_app": bool(DEFAULT_CLIENT_ID), "accounts": rows})

    @app.post("/api/twitch/device/start")
    async def twitch_device_start(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Begin the Twitch login: returns the code and opens twitch.tv's approval page."""

        account = _twitch_account(body.get("index"))
        try:
            async with httpx.AsyncClient() as client:
                info = await tw.start_device_flow(client, account)
        except RuntimeError as e:
            raise HTTPException(400, str(e)) from e
        uri = str(info.get("verification_uri") or "")
        if uri.startswith("https://www.twitch.tv/"):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(webbrowser.open, uri)
        return JSONResponse(info)

    @app.post("/api/twitch/device/poll")
    async def twitch_device_poll(body: dict[str, Any] = Body(...)) -> JSONResponse:
        account = _twitch_account(body.get("index"))
        try:
            async with httpx.AsyncClient() as client:
                return JSONResponse(await tw.poll_device_flow(client, account))
        except Exception as e:
            logger.exception("twitch device poll failed")
            return JSONResponse({"status": "error", "detail": str(e)})

    @app.post("/api/twitch/disconnect")
    async def twitch_disconnect(body: dict[str, Any] = Body(...)) -> JSONResponse:
        tw.disconnect(_twitch_account(body.get("index")))
        return JSONResponse({"ok": True})

    @app.get("/api/config")
    async def get_config(
        format: str | None = Query(None, description="v2 = the stored config_version 2 shape; default = UI view"),
    ) -> JSONResponse:
        """The config. By default in the legacy shape the current UI edits (``config_migrate``);
        ``?format=v2`` returns the stored ``config_version: 2`` document."""

        logger.debug("GET /api/config format=%s", format)
        async with lock:
            raw = ensure_minimal_structure(dict(state.raw))
            if (format or "").lower() != "v2":
                raw = config_for_ui(raw, rt.deck)
        return JSONResponse(raw)

    @app.put("/api/config")
    async def put_config(body: dict[str, Any]) -> JSONResponse:
        """Save a config: ``config_version: 2`` as is, or a legacy / UI-view one (migrated)."""

        if not isinstance(body, dict):
            raise HTTPException(400, t("error.json_object_required"))
        try:
            merged = ensure_minimal_structure(config_from_ui(body))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        knob_errors = validate_knobs_config(merged)
        if knob_errors:
            raise HTTPException(400, t("error.invalid_knobs", details="; ".join(knob_errors[:10])))
        merged, _ = materialize_external_media(merged, config_dir)
        n_pages = len(merged.get("pages") or []) if isinstance(merged.get("pages"), list) else 0
        logger.debug("PUT /api/config pages=%s path=%s", n_pages, config_path)
        async with lock:
            # The UI language is owned by PUT /api/language; a stale full-config autosave from
            # another tab/module must not silently revert it.
            merged["language"] = state.raw.get("language") or "auto"
            # Same for the dismissed onboarding: once done it stays done.
            merged["onboarding_done"] = bool(state.raw.get("onboarding_done")) or bool(merged.get("onboarding_done"))
            # Same for the screen brightness: it is owned by /api/brightness (live controller).
            if rt.deck_brightness is not None:
                merged.update(rt.deck_brightness.snapshot())
            save_raw_config(config_path, merged)
            state.replace_raw(merged)
            prune_stale_live_message_keys(dict(state.raw), rt)
            new_settings = state.settings()
            # The live OBS/HA clients are built once at agent startup from whatever the config
            # said then; without this, editing host/port/password (or base_url/token) here saves
            # to disk but the running session keeps using the old values -- and for OBS, an
            # already-authenticated WebSocket doesn't even notice the password changed, so it
            # keeps reporting "connected" while every action silently fails.
            if rt.obs is not None and new_settings.obs is not None:
                await rt.obs.update_credentials(new_settings.obs.host, new_settings.obs.port, new_settings.obs.password)
            if rt.ha is not None and new_settings.ha is not None:
                rt.ha.update_credentials(new_settings.ha.base_url, new_settings.ha.token)
        set_language_from_raw(merged)
        try:
            reapply_logging_from_config(
                merged,
                verbose=rt.startup_verbose,
                log_dir_override=rt.log_dir_override,
            )
        except Exception:
            logger.exception("reapply logging after PUT /api/config")
        # Do not push graphics to the device here; use POST /api/refresh_skin after explicit Apply in the UI.
        return JSONResponse({"ok": True})

    @app.post("/api/config/backup")
    async def post_config_backup() -> JSONResponse:
        async with lock:

            def _go() -> dict[str, Any]:
                return create_rotating_backup(config_path, max_keep=3)

            try:
                result = await asyncio.to_thread(_go)
            except FileNotFoundError as e:
                raise HTTPException(404, str(e)) from e
        return JSONResponse(result)

    @app.get("/api/config/backups")
    async def get_config_backups() -> JSONResponse:
        rows = list_backups(config_path, max_keep=3)
        return JSONResponse({"backups": rows})

    @app.post("/api/config/backups/restore")
    async def post_config_backups_restore(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Overwrite the live config with one of the rotating `.bak*` files, then reload it."""

        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, t("error.name_required"))

        async with lock:

            def _restore() -> dict[str, Any]:
                return restore_backup(config_path, name, max_keep=3)

            try:
                result = await asyncio.to_thread(_restore)
            except FileNotFoundError as e:
                raise HTTPException(404, str(e)) from e
            state.reload_from_disk()
            prune_stale_live_message_keys(dict(state.raw), rt)
            fresh = dict(state.raw)
            fresh_view = config_for_ui(fresh, rt.deck)
            if rt.deck_brightness is not None:
                rt.deck_brightness.load_from_raw(fresh)
                rt.deck_brightness.apply()

        set_language_from_raw(fresh)
        try:
            reapply_logging_from_config(
                fresh,
                verbose=rt.startup_verbose,
                log_dir_override=rt.log_dir_override,
            )
        except Exception:
            logger.exception("reapply logging after POST /api/config/backups/restore")
        logger.warning("POST /api/config/backups/restore from=%s path=%s", name, config_path)
        if on_refresh:
            try:
                await on_refresh()
            except Exception:
                logger.exception("on_refresh failed after config restore")
                raise HTTPException(500, t("error.refresh_failed")) from None
        return JSONResponse({"ok": True, **result, "config": fresh_view})

    @app.post("/api/config/backups/wipe")
    async def post_config_backups_wipe() -> JSONResponse:
        """
        Persist the current in-memory config to disk, then delete all rotating ``.bak*`` files.
        Only the main YAML remains as the single source of truth.
        """

        async with lock:
            merged = ensure_minimal_structure(dict(state.raw))
            merged, _ = materialize_external_media(merged, config_dir)
            save_raw_config(config_path, merged)
            state.replace_raw(merged)
            prune_stale_live_message_keys(dict(state.raw), rt)

            def _wipe() -> dict[str, Any]:
                return wipe_backups(config_path, max_keep=3)

            result = await asyncio.to_thread(_wipe)
        set_language_from_raw(merged)
        try:
            reapply_logging_from_config(
                merged,
                verbose=rt.startup_verbose,
                log_dir_override=rt.log_dir_override,
            )
        except Exception:
            logger.exception("reapply logging after POST /api/config/backups/wipe")
        logger.info("POST /api/config/backups/wipe removed=%s path=%s", result.get("count"), config_path)
        return JSONResponse(result)

    @app.post("/api/config/reset")
    async def post_config_reset(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Reset deck layout (touch pages) to defaults; preserve other config (e.g. Spotify)."""

        if not isinstance(body, dict) or not body.get("confirm"):
            raise HTTPException(400, t("error.confirm_required"))

        async with lock:
            current = ensure_minimal_structure(dict(state.raw))
            defaults = ensure_minimal_structure(default_raw_config())
            # Only reset the touch-page layout. Keep Spotify/auth/tokens and other user settings.
            current["pages"] = defaults.get("pages") or []
            raw = ensure_minimal_structure(current)
            prune_unused_library_media(raw, config_dir)
            save_raw_config(config_path, raw)
            state.replace_raw(raw)
            state.page_index = 0
            prune_stale_live_message_keys(dict(state.raw), rt)

        # Wipe rotating backups outside the lock (disk IO).
        def _wipe() -> dict[str, Any]:
            return wipe_backups(config_path, max_keep=3)

        result = await asyncio.to_thread(_wipe)
        logger.warning("POST /api/config/reset restored default pages path=%s", config_path)
        if on_refresh:
            try:
                await on_refresh()
            except Exception:
                logger.exception("on_refresh failed after config reset")
                raise HTTPException(500, t("error.refresh_failed")) from None
        return JSONResponse({"ok": True, **result})

    @app.post("/api/refresh_skin")
    async def refresh_skin() -> JSONResponse:
        logger.debug("POST /api/refresh_skin")
        if on_refresh:
            try:
                await on_refresh()
            except Exception as e:
                logger.exception("refresh_skin failed")
                raise HTTPException(500, t("error.refresh_failed")) from e
        return JSONResponse({"ok": True})

    @app.post("/api/upload")
    async def upload(
        file: UploadFile = File(...),
        library: str = Query(
            "images",
            description="library/images, videos, sounds, or fonts",
        ),
    ) -> JSONResponse:
        lib = (library or "images").strip().lower().replace("\\", "/")
        if lib in ("image", "images"):
            sub = "images"
        elif lib in ("video", "videos"):
            sub = "videos"
        elif lib in ("sound", "sounds", "audio"):
            sub = "sounds"
        elif lib in ("font", "fonts"):
            sub = "fonts"
        else:
            raise HTTPException(400, t("error.bad_library"))
        if sub == "fonts":
            name = file.filename or "font.ttf"
            name = SAFE_NAME.sub("_", Path(name).name)
            if not name or name.startswith("."):
                name = "font.ttf"
            suf = Path(name).suffix.lower()
            if suf not in FONT_FILE_EXT:
                raise HTTPException(
                    400,
                    t("error.font_extensions", extensions=", ".join(sorted(FONT_FILE_EXT))),
                )
        else:
            name = file.filename or "image.png"
            name = SAFE_NAME.sub("_", Path(name).name)
            if not name or name.startswith("."):
                name = "image.png"
        unique = f"{uuid.uuid4().hex[:8]}_{name}"
        img_dir = config_dir / "library" / sub
        img_dir.mkdir(parents=True, exist_ok=True)
        dest = img_dir / unique
        data = await file.read()
        max_bytes = 512 * 1024 * 1024 if sub == "videos" else 12 * 1024 * 1024
        if len(data) > max_bytes:
            cap = "512MB" if sub == "videos" else "12MB"
            raise HTTPException(413, t("error.file_too_large", max=cap))
        dest.write_bytes(data)
        rel = f"library/{sub}/{unique}"
        return JSONResponse({"path": rel, "name": unique})

    # ---- sound library (library/sounds): list / preview on this PC / stop / rename / delete ----

    def _sound_file(name: Any) -> Path:
        try:
            return sound_library.resolve_library_file(config_dir, name)
        except sound_library.SoundPathError:
            raise HTTPException(400, t("error.invalid_path")) from None
        except FileNotFoundError:
            raise HTTPException(404, t("error.not_found")) from None

    @app.get("/api/sounds")
    async def list_sounds() -> JSONResponse:
        items = await asyncio.to_thread(sound_library.list_sounds, config_dir)
        return JSONResponse(
            {
                "sounds": items,
                "platform": sys.platform,
                "windows_extensions": sorted(sound_player.WINDOWS_EXTENSIONS),
            }
        )

    @app.post("/api/sounds/preview")
    async def preview_sound(body: dict[str, Any] = Body(...)) -> JSONResponse:
        p = _sound_file(body.get("file"))
        try:
            await asyncio.to_thread(
                sound_player.get_player().play,
                str(p),
                body.get("volume", 100),
                "restart",
                "__preview__",
            )
        except Exception as e:
            logger.warning("sound preview failed: %s", e)
            raise HTTPException(500, str(e)) from e
        return JSONResponse({"ok": True})

    @app.post("/api/sounds/stop")
    async def stop_sounds() -> JSONResponse:
        n = await asyncio.to_thread(sound_player.get_player().stop_all)
        return JSONResponse({"ok": True, "stopped": n})

    @app.post("/api/sounds/rename")
    async def rename_sound(body: dict[str, Any] = Body(...)) -> JSONResponse:
        _sound_file(body.get("file"))
        try:
            dest = sound_library.rename_sound(config_dir, body.get("file"), body.get("name"))
        except sound_library.SoundPathError:
            raise HTTPException(400, t("error.invalid_path")) from None
        except FileExistsError:
            raise HTTPException(409, t("error.sound_exists")) from None
        return JSONResponse({"ok": True, "file": f"{sound_library.LIBRARY_REL}/{dest.name}"})

    @app.post("/api/sounds/delete")
    async def delete_sound(body: dict[str, Any] = Body(...)) -> JSONResponse:
        _sound_file(body.get("file"))
        sound_library.delete_sound(config_dir, body.get("file"))
        return JSONResponse({"ok": True})

    @app.get("/api/local-file")
    async def local_file(
        path: str = Query(..., description="Path relative to config"),
    ) -> FileResponse:
        logger.debug("GET /api/local-file path=%s", path)
        raw = path.strip().replace("\\", "/")
        if not raw or raw.startswith("/") or ".." in raw.split("/"):
            raise HTTPException(403, t("error.invalid_path"))
        p = (config_dir / raw).resolve()
        try:
            p.relative_to(config_dir)
        except ValueError as e:
            raise HTTPException(403, t("error.invalid_path")) from e
        if not p.is_file():
            raise HTTPException(404, t("error.not_found"))
        mime, _ = mimetypes.guess_type(str(p))
        return FileResponse(p, media_type=mime or "application/octet-stream")

    preview_cache = PreviewCache()

    def _wow_icon_pending(entry: dict[str, Any]) -> bool:
        spec = str(entry.get("icon") or entry.get("image") or "").strip()
        if not spec.lower().startswith("wow:"):
            return False
        name = wow_icons.normalize_name(spec[4:])
        return name is not None and not wow_icons.cached_path(default_icon_cache_dir(), name).is_file()

    @app.post("/api/preview_key")
    async def preview_key(
        body: dict[str, Any] = Body(...),
    ) -> Response:
        """PNG matching on-device render (same layout as ``render_tactile_key_image``).

        ``animation_frame`` / ``press_elapsed_frames`` (optional ints) let the UI preview idle and
        press animations exactly as they'll play on the device: poll with an increasing
        ``animation_frame`` while a key with ``idle_animation`` is open, or step
        ``press_elapsed_frames`` through 0..3 for a "preview press" button.
        """

        entry = body.get("entry")
        if not isinstance(entry, dict):
            raise HTTPException(400, t("error.entry_object"))
        async with lock:
            # The editor names the model it lays out (its key size); else the UI's model.
            pv_model = model_by_name(str(body.get("model") or "")) or ui_model(state.raw, rt.deck)
        raw_cid = str(body.get("control_id") or "key_0_0")
        cid = to_control_id(raw_cid, pv_model) or raw_cid
        size = pv_model.image_size(cid) or key_size_for_control(cid)

        def _as_optional_int(v: Any) -> int | None:
            if v is None:
                return None
            with contextlib.suppress(TypeError, ValueError):
                return int(v)
            return None

        animation_frame = _as_optional_int(body.get("animation_frame"))
        press_elapsed_frames = _as_optional_int(body.get("press_elapsed_frames"))
        mode = str(body.get("mode") or "").strip().lower() or None
        if mode is not None and mode not in ("text", "icon", "both"):
            raise HTTPException(400, "body.mode must be one of text, icon, both")
        offline = body.get("offline") is True
        lang = str(body.get("lang") or "").strip() or None
        live_value = body.get("live_value")
        live_value = None if live_value is None else str(live_value)

        async with lock:
            ent = dict(entry)
            pages_list = state.raw.get("pages") or []
            n = len(pages_list) if isinstance(pages_list, list) else 0
            pi = int(state.page_index) % n if n else 0
            sk = preview_storage_key(cid, pi, state.raw)
            if live_message_params_from_entry(ent):
                ov = rt.live_message_text.get(sk)
                if ov is not None:
                    ent["text"] = ov
            elif twitch_live_params_from_entry(ent):
                ov = rt.live_message_text.get(sk)
                if ov is not None:
                    ent["text"] = ov
                else:
                    ent["text"] = "Twitch (loading)"
            elif obs_stream_params_from_entry(ent):
                ov = rt.live_message_text.get(sk)
                if ov is not None:
                    ent["text"] = ov
                else:
                    ent["text"] = "OBS stream (loading)"
            elif obs_scene_params_from_entry(ent):
                ov = rt.live_message_text.get(sk)
                if ov is not None:
                    ent["text"] = ov
                else:
                    ent["text"] = "OBS scene (loading)"
            elif battery_params_from_entry(ent):
                ov = rt.live_message_text.get(sk)
                if ov is not None:
                    ent["text"] = ov
                else:
                    ent["text"] = "Battery (loading)"
            elif ha_sensor_params_from_entry(ent):
                ov = rt.live_message_text.get(sk)
                if ov is not None:
                    ent["text"] = ov
                else:
                    ent["text"] = "HA sensor (loading)"
            elif ha_weather_params_from_entry(ent):
                ov = rt.live_message_text.get(sk)
                if ov is not None:
                    ent["text"] = ov
                else:
                    ent["text"] = "HA weather (loading)"
            else:
                cparams = clock_params_from_entry(ent)
                if cparams is not None:
                    ent["text"] = format_clock_overlay_text(cparams)
            is_live = any(
                f(entry)
                for f in (
                    live_message_params_from_entry,
                    twitch_live_params_from_entry,
                    obs_stream_params_from_entry,
                    obs_scene_params_from_entry,
                    battery_params_from_entry,
                    ha_sensor_params_from_entry,
                    ha_weather_params_from_entry,
                    clock_params_from_entry,
                )
            )
            if is_live:
                if live_value is not None:
                    ent["text"] = live_value
                if offline:
                    act = ent.get("action")
                    fb = offline_fallback_mode(act if isinstance(act, dict) else ent)
                    ent["text"] = offline_fallback_text(fb, live_value or str(ent.get("text") or ""))
            # Merge the proposed look here so the cache key carries the (language-dependent) label.
            entry = proposed_entry(ent, lang) or ent

        def _render() -> tuple[bytes, dict[str, Any]]:
            img, measure = render_key_preview(
                entry,
                config_dir,
                size=size,
                mode=mode,
                offline=offline,
                animation_frame=animation_frame,
                press_elapsed_frames=press_elapsed_frames,
            )
            if img is None:
                return b"", measure
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), measure

        # Animated previews (idle/press frames) are never cached: every frame is different.
        cacheable = animation_frame is None and press_elapsed_frames is None
        ckey = preview_cache_key(entry, config_dir, size, mode, offline) if cacheable else ""
        cached = preview_cache.get(ckey) if cacheable else None
        if cached is None:
            cached = await asyncio.to_thread(_render)
            # A WoW icon that could not be downloaded (offline...) must not be frozen into the cache.
            if cacheable and not _wow_icon_pending(entry):
                preview_cache.put(ckey, cached)
        png, measure = cached
        if not png:
            raise HTTPException(404, t("error.nothing_to_render"))
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "X-Key-Overflow": "0" if measure["fits"] else "1",
                "X-Key-Lines": str(measure["lines"]),
                "Access-Control-Expose-Headers": "X-Key-Overflow, X-Key-Lines",
            },
        )

    return app
