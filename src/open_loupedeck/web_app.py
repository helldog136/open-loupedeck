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
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import autostart
from .action_catalog import merged_catalog
from .button_render import key_size_for_control, render_tactile_key_image
from .config_backup import create_rotating_backup, list_backups, restore_backup, wipe_backups
from .config_io import default_raw_config, ensure_minimal_structure, save_raw_config
from .config_paths import ensure_application_dirs
from .config_state import ConfigState
from .control_ids import is_page_scoped_control
from .hardware.live_s_device import LoupedeckLiveS
from .live_message import (
    battery_params_from_entry,
    clock_params_from_entry,
    format_clock_overlay_text,
    ha_sensor_params_from_entry,
    ha_weather_params_from_entry,
    live_message_params_from_entry,
    obs_scene_params_from_entry,
    obs_stream_params_from_entry,
    preview_storage_key,
    prune_stale_live_message_keys,
    twitch_live_params_from_entry,
)
from .logging_setup import reapply_logging_from_config
from .media_library import FONT_FILE_EXT, materialize_external_media, prune_unused_library_media
from .package_paths import package_root
from .runtime_refs import AgentRuntimeRefs
from .simulate_input import build_synthetic_loupedeck_message
from .spotify_client import SpotifyManager

logger = logging.getLogger(__name__)

SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _static_dir() -> Path:
    return package_root() / "static"


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

    @app.middleware("http")
    async def _no_cache(request: Any, call_next: Any) -> Any:
        """This is a local single-user config UI, never a public site: correctness after an app
        update matters far more than caching a few KB of static assets. Without this, a webview's
        disk cache serving a stale index.html/app.js/style.css after an install can look exactly
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
            conn = getattr(rt.deck, "connection", None)
            path = getattr(rt.deck, "path", None)
            usb_ok = conn is not None and bool(getattr(conn, "is_open", False))
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
            deck_layout = "live_s" if isinstance(rt.deck, LoupedeckLiveS) else "live"

        hub = getattr(rt, "overlay_hub", None)
        overlay_paths: dict[str, str] = {"page": "/overlay", "websocket": "/ws/overlay"} if hub is not None else {}

        touch_errors: dict[str, str] = {}
        try:
            prefix = f"p{int(page_index_ui)}:touch_"
            for k, v in (rt.control_error or {}).items():
                if isinstance(k, str) and k.startswith(prefix):
                    # storage_key is "p{page}:touch_N" → expose "touch_N"
                    _, _, cid = k.partition(":")
                    if is_page_scoped_control(cid):
                        touch_errors[cid] = str(v)
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
            raise HTTPException(500, f"Could not open folder: {exc}") from exc
        return JSONResponse({"ok": True, "path": str(folder)})

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
            raise HTTPException(400, "index required")
        try:
            ix = int(raw)
        except (TypeError, ValueError):
            raise HTTPException(400, "index must be an integer") from None
        async with lock:
            pages_list = state.raw.get("pages") or []
            if not isinstance(pages_list, list) or len(pages_list) == 0:
                raise HTTPException(400, "no pages in config")
            state.page_index = ix % len(pages_list)
            out_idx = state.page_index
        if on_refresh:
            try:
                await on_refresh()
            except Exception:
                logger.exception("on_refresh failed after page_index change")
                raise HTTPException(500, "refresh failed") from None
        return JSONResponse({"ok": True, "page_index": out_idx})

    @app.post("/api/simulate_press")
    async def simulate_press(body: dict[str, Any] = Body(...)) -> JSONResponse:
        """Fire the same dispatch path as a hardware press/turn (for testing without the device)."""

        sim = rt.simulate_raw_message
        if sim is None:
            raise HTTPException(503, "Simulate not available (agent not ready)")
        cid = str(body.get("control_id") or "").strip()
        raw_dir = body.get("direction")
        direction: str | None = None
        if raw_dir is not None:
            s = str(raw_dir).strip().lower()
            if s in ("left", "right"):
                direction = s
        msg = build_synthetic_loupedeck_message(cid, direction=direction)
        if msg is None:
            raise HTTPException(
                400,
                "Unsupported control_id (side strips cannot be simulated from the UI)",
            )
        try:
            await sim(msg)
        except Exception as e:
            logger.exception("simulate_press failed")
            raise HTTPException(500, detail=str(e)) from e
        return JSONResponse({"ok": True})

    @app.get("/api/action_catalog")
    async def action_catalog() -> JSONResponse:
        return JSONResponse({"actions": merged_catalog()})

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
                detail="Set spotify.client_id and spotify.redirect_uri (use the form in the UI or YAML)",
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

    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        logger.debug("GET /api/config")
        async with lock:
            raw = ensure_minimal_structure(dict(state.raw))
        return JSONResponse(raw)

    @app.put("/api/config")
    async def put_config(body: dict[str, Any]) -> JSONResponse:
        if not isinstance(body, dict):
            raise HTTPException(400, "JSON object required")
        merged = ensure_minimal_structure(body)
        merged, _ = materialize_external_media(merged, config_dir)
        n_pages = len(merged.get("pages") or []) if isinstance(merged.get("pages"), list) else 0
        logger.debug("PUT /api/config pages=%s path=%s", n_pages, config_path)
        async with lock:
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
            raise HTTPException(400, "name required")

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
                raise HTTPException(500, "refresh failed") from None
        return JSONResponse({"ok": True, **result, "config": fresh})

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
            raise HTTPException(400, "confirm=true required")

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
                raise HTTPException(500, "refresh failed") from None
        return JSONResponse({"ok": True, **result})

    @app.post("/api/refresh_skin")
    async def refresh_skin() -> JSONResponse:
        logger.debug("POST /api/refresh_skin")
        if on_refresh:
            try:
                await on_refresh()
            except Exception as e:
                logger.exception("refresh_skin failed")
                raise HTTPException(500, "refresh failed") from e
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
            raise HTTPException(400, "library= must be images, videos, sounds, or fonts")
        if sub == "fonts":
            name = file.filename or "font.ttf"
            name = SAFE_NAME.sub("_", Path(name).name)
            if not name or name.startswith("."):
                name = "font.ttf"
            suf = Path(name).suffix.lower()
            if suf not in FONT_FILE_EXT:
                raise HTTPException(
                    400,
                    f"Font uploads must be {', '.join(sorted(FONT_FILE_EXT))}",
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
            raise HTTPException(413, f"File too large (max {cap})")
        dest.write_bytes(data)
        rel = f"library/{sub}/{unique}"
        return JSONResponse({"path": rel, "name": unique})

    @app.get("/api/local-file")
    async def local_file(
        path: str = Query(..., description="Path relative to config"),
    ) -> FileResponse:
        logger.debug("GET /api/local-file path=%s", path)
        raw = path.strip().replace("\\", "/")
        if not raw or raw.startswith("/") or ".." in raw.split("/"):
            raise HTTPException(403, "Invalid path")
        p = (config_dir / raw).resolve()
        try:
            p.relative_to(config_dir)
        except ValueError as e:
            raise HTTPException(403, "Invalid path") from e
        if not p.is_file():
            raise HTTPException(404, "Not found")
        mime, _ = mimetypes.guess_type(str(p))
        return FileResponse(p, media_type=mime or "application/octet-stream")

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
            raise HTTPException(400, "body.entry must be an object")
        cid = str(body.get("control_id") or "touch_0")
        size = key_size_for_control(cid)

        def _as_optional_int(v: Any) -> int | None:
            if v is None:
                return None
            with contextlib.suppress(TypeError, ValueError):
                return int(v)
            return None

        animation_frame = _as_optional_int(body.get("animation_frame"))
        press_elapsed_frames = _as_optional_int(body.get("press_elapsed_frames"))

        async with lock:
            ent = dict(entry)
            pages_list = state.raw.get("pages") or []
            n = len(pages_list) if isinstance(pages_list, list) else 0
            pi = int(state.page_index) % n if n else 0
            sk = preview_storage_key(cid, pi)
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
            entry = ent

        def _render():
            return render_tactile_key_image(
                entry,
                config_dir,
                size=size,
                animation_frame=animation_frame,
                press_elapsed_frames=press_elapsed_frames,
            )

        img = await asyncio.to_thread(_render)
        if img is None:
            raise HTTPException(404, "Nothing to render for this entry")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    return app
