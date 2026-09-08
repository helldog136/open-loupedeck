"""Asyncio application + Loupedeck thread callback bridge + optional web UI."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
import threading
from collections.abc import Awaitable, Callable
from itertools import count
from pathlib import Path
from typing import Any

import httpx
from Loupedeck.DeviceManager import DeviceManager
from Loupedeck.Devices.constants import BAUD_RATE
from Loupedeck.Devices.LoupedeckLive import LoupedeckLive

from .actions import ActionContext, run_actions
from .button_render import PRESS_ANIMATION_MAX_DURATION_TICKS
from .config import Settings
from .config_io import raw_to_settings
from .config_paths import default_config_path
from .config_state import ConfigState
from .control_ids import control_ids_for_lookup
from .deck_skin import apply_page_skin, page_needs_animated_skin
from .device_discovery import list_loupedeck_usb_ports, usb_hint_for_port
from .events import NormalizedEvent, normalize_loupedeck_message
from .ha_client import HaClient
from .hardware.live_s_device import LoupedeckLiveS
from .knob_flash import flash_knob_page_name
from .knob_pages import (
    KNOB_ENCODER_IDS,
    actions_for_knob_rotation,
    cycle_knob_page_index,
    knob_page_feedback_label,
    pages_list_for_knob,
)
from .live_message import preview_storage_key, refresh_live_messages
from .logging_setup import bootstrap_logging, load_raw_for_logging
from .loupedeck_patch import set_serial_fatal_callback
from .match import actions_for_event
from .obs_client import ObsSession
from .overlay_hub import OverlayHub
from .page_runtime import PageNavigator, actions_for_page_event
from .plugins import load_plugin_files
from .runtime_refs import AgentRuntimeRefs
from .spotify_client import SpotifyManager

logger = logging.getLogger(__name__)


def _resolve_device_class(model: str, hint: str) -> type[LoupedeckLive] | None:
    m = model.lower()
    if m == "live":
        return LoupedeckLive
    if m == "live_s":
        return LoupedeckLiveS
    if m == "auto":
        if hint == "live_s":
            return LoupedeckLiveS
        if hint == "live":
            return LoupedeckLive
    return None


def _open_deck(settings: Settings) -> LoupedeckLive:
    """Open serial port with correct Live vs Live S driver; prefer USB VID/PID discovery."""

    bauds = [settings.device.baudrate] if settings.device.baudrate is not None else [BAUD_RATE, 256000, 115200]

    model = settings.device.model or "auto"
    candidates: list[tuple[str, type[LoupedeckLive]]] = []
    seen: set[tuple[str, str]] = set()

    def add(path: str, cls: type[LoupedeckLive]) -> None:
        key = (path, cls.__name__)
        if key in seen:
            return
        seen.add(key)
        candidates.append((path, cls))

    if settings.device.path:
        p = settings.device.path
        hint = usb_hint_for_port(p)
        rc = _resolve_device_class(model, hint)
        if rc is not None:
            add(p, rc)
        else:
            add(p, LoupedeckLiveS)
            add(p, LoupedeckLive)
    else:
        usb_list = list_loupedeck_usb_ports()
        if usb_list:
            for path, hint in usb_list:
                rc = _resolve_device_class(model, hint)
                if rc is not None:
                    add(path, rc)
                else:
                    add(path, LoupedeckLiveS)
                    add(path, LoupedeckLive)
        else:
            logger.warning(
                "No USB serial port with Loupedeck vendor ID (0x2ec2) found. "
                "Plug in the device; on Linux use udev + dialout; on Windows install the USB serial driver "
                "if needed; set device.path manually (e.g. COM5, /dev/ttyACM0)."
            )
            for path in DeviceManager.list():
                hint = usb_hint_for_port(path)
                rc = _resolve_device_class(model, hint)
                if rc is not None:
                    add(path, rc)
                else:
                    add(path, LoupedeckLiveS)
                    add(path, LoupedeckLive)

    if not candidates:
        hint = "Set device.path in config (e.g. COM5 on Windows, /dev/ttyACM0 on Linux)."
        if sys.platform != "win32":
            hint += " On Linux you can list ports: ls -l /dev/serial/by-id/"
        raise RuntimeError("No serial ports to try. " + hint)

    last_err: Exception | None = None
    for path, cls in candidates:
        for baud in bauds:
            try:
                deck = cls(path=path, baudrate=baud, timeout=1)
                if deck.is_loupedeck():
                    logger.info("Loupedeck open: %s as %s @ %s baud", path, cls.__name__, baud)
                    return deck
            except Exception as e:
                last_err = e
                logger.debug("Try %s %s @ %s: %s", cls.__name__, path, baud, e)
                continue

    msg = _open_deck_failure_message(last_err)
    raise RuntimeError(msg) from last_err


def _open_deck_failure_message(last_err: Exception | None) -> str:
    base = (
        "No Loupedeck found. Check device.path, device.model, device.baudrate; "
        "stop the official Loupedeck app if it is running."
    )
    if last_err is None:
        return base
    err_s = str(last_err)
    if "Permission denied" in err_s or "Errno 13" in err_s:
        return (
            f"{base}\n\n"
            f"Permission denied on the serial port ({last_err}).\n"
            "- Add your user to group dialout: sudo usermod -aG dialout $USER\n"
            "- Log out and log back in (or reboot), then retry.\n"
            "- Install the udev rule from this repo: udev/99-loupedeck.rules → /etc/udev/rules.d/\n"
            "  then: sudo udevadm control --reload-rules && sudo udevadm trigger\n"
            "  and unplug/replug the Loupedeck.\n"
        )
    return f"{base}\n\nLast error: {last_err}"


def _should_dispatch(ev: NormalizedEvent) -> bool:
    if ev.kind == "button":
        return ev.edge == "down"
    if ev.kind == "touch":
        return ev.edge == "down"
    return ev.kind == "knob"


async def run_agent(
    state: ConfigState,
    lock: asyncio.Lock,
    redraw_skin: Callable[..., Awaitable[None]],
    runtime: AgentRuntimeRefs,
    spotify: SpotifyManager | None = None,
) -> None:
    import open_loupedeck.actions  # noqa: F401 — register builtins

    settings = state.settings()
    logger.info(
        "Agent starting plugins=%s pages=%s",
        len(settings.plugin_modules),
        len(settings.pages or []),
    )
    load_plugin_files(settings.plugin_modules)

    obs: ObsSession | None = None
    if settings.obs:
        logger.info("OBS WebSocket target ws://%s:%s", settings.obs.host, settings.obs.port)
        obs = ObsSession(settings.obs.host, settings.obs.port, settings.obs.password)
    else:
        logger.info("No OBS config; obs.* actions will fail until obs: is set in YAML")
    runtime.obs = obs

    ha_configured = bool(settings.ha and settings.ha.base_url and settings.ha.token)
    if ha_configured:
        logger.info("Home Assistant target %s", settings.ha.base_url)
    else:
        logger.info("No Home Assistant config; ha.* actions will fail until ha: is set in YAML")

    navigator: PageNavigator | None = None
    pages_list = state.raw.get("pages") or []
    if isinstance(pages_list, list) and len(pages_list) > 0:

        def get_pages() -> list[dict[str, Any]]:
            p = state.raw.get("pages") or []
            return p if isinstance(p, list) else []

        def get_index() -> int:
            return state.page_index

        def set_index(i: int) -> None:
            state.page_index = i

        async def on_nav_change() -> None:
            await redraw_skin("deck_page_nav")

        navigator = PageNavigator(get_pages, get_index, set_index, on_nav_change)

    config_dir = state.path.parent.resolve()

    async with httpx.AsyncClient() as http_client:
        ha: HaClient | None = None
        if ha_configured:
            ha = HaClient(http_client, settings.ha.base_url, settings.ha.token)
        runtime.ha = ha

        ctx = ActionContext(
            obs=obs,
            http_client=http_client,
            log=logger,
            pages=navigator,
            config_dir=config_dir,
            spotify=spotify,
            overlay_hub=runtime.overlay_hub,
            ha=ha,
        )

        async def live_message_tick() -> bool:
            async with lock:
                raw = dict(state.raw)
                pi = int(state.page_index)
            return await refresh_live_messages(raw, pi, runtime, http_client, logger, obs, ha)

        async def live_message_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(1)
                    try:
                        if await live_message_tick():
                            await redraw_skin("live_message_refresh")
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("live_message_loop tick")
            except asyncio.CancelledError:
                pass

        try:
            await live_message_tick()
        except Exception:
            logger.exception("initial live_message tick")

        live_task = asyncio.create_task(live_message_loop())

        async def skin_animation_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(0.1)
                    if runtime.no_device or runtime.deck is None:
                        continue
                    try:
                        async with lock:
                            pages = state.raw.get("pages") or []
                            if not isinstance(pages, list) or not pages:
                                continue
                            idx = int(state.page_index) % len(pages)
                            page = pages[idx]
                            gb = state.raw.get("global_buttons")
                            if not isinstance(gb, dict):
                                gb = {}
                        if (
                            not page_needs_animated_skin(runtime.deck, page, gb, config_dir)
                            and not runtime.press_animation_start
                        ):
                            continue
                        runtime.skin_animation_tick += 1
                        if runtime.press_animation_start:
                            cutoff = runtime.skin_animation_tick
                            runtime.press_animation_start = {
                                cid: start
                                for cid, start in runtime.press_animation_start.items()
                                if cutoff - start < PRESS_ANIMATION_MAX_DURATION_TICKS
                            }
                        await redraw_skin("skin_animation")
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("skin_animation_loop tick")
            except asyncio.CancelledError:
                pass

        skin_anim_task = asyncio.create_task(skin_animation_loop())

        loop = asyncio.get_running_loop()

        def _mark_deck_unplugged() -> None:
            runtime.deck_unplugged = True

        def on_serial_fatal() -> None:
            loop.call_soon_threadsafe(_mark_deck_unplugged)

        set_serial_fatal_callback(on_serial_fatal)

        async def handle_raw_message(msg: dict[str, Any]) -> None:
            # Encoder push: only cycles knob_pages (no YAML binding). Ignored if knob has no pages.
            if (
                msg.get("action") == "push"
                and msg.get("state") == "down"
                and str(msg.get("id", "")) in KNOB_ENCODER_IDS
            ):
                kid = str(msg.get("id", ""))
                did_cycle = False
                label = ""
                raw_snap: dict[str, Any] = {}
                model = "auto"
                async with lock:
                    plist = pages_list_for_knob(state.raw, kid)
                    if plist is not None and len(plist) >= 1:
                        cycle_knob_page_index(runtime.knob_page_indices, kid, len(plist))
                        ix = runtime.knob_page_indices[kid]
                        pg = plist[ix]
                        label = knob_page_feedback_label(pg)
                        raw_snap = dict(state.raw)
                        model = state.settings().device.model
                        did_cycle = True
                if did_cycle and runtime.deck is not None:
                    await flash_knob_page_name(runtime.deck, config_dir, raw_snap, model, kid, label, redraw_skin)
                return

            ev = normalize_loupedeck_message(msg)
            if ev is None or not _should_dispatch(ev):
                return
            if ev.kind == "button" and ev.edge == "down":
                logger.debug("Button down id=%s (raw_id=%s)", ev.id, msg.get("id"))
            logger.debug("Dispatch event %s %s edge=%s", ev.kind, ev.id, ev.edge)

            canonical_bid = None
            if ev.kind == "button":
                lookup_ids = control_ids_for_lookup(ev)
                canonical_bid = lookup_ids[0] if lookup_ids else None
            if (
                ev.kind == "button"
                and ev.edge == "down"
                and canonical_bid in ("btn_circle", "btn_1", "btn_2", "btn_3")
                and runtime.deck is not None
                and isinstance(runtime.deck, LoupedeckLiveS)
            ):
                idx = 0 if canonical_bid == "btn_circle" else int(canonical_bid.split("_")[1])
                async with lock:
                    pages = state.raw.get("pages") or []
                    if isinstance(pages, list) and len(pages) > 0:
                        state.page_index = idx % min(len(pages), 4)
                    pi = state.page_index
                logger.debug("Page switch via %s -> index %s", ev.id, pi)
                await redraw_skin("physical_page_button")
                return

            if ev.kind == "knob":
                async with lock:
                    k_acts = actions_for_knob_rotation(
                        state.raw,
                        str(ev.id),
                        str(ev.edge),
                        runtime.knob_page_indices,
                    )
                if k_acts is not None:
                    ctx.obs = obs
                    ctx.pages = navigator
                    if k_acts:
                        await run_actions(ctx, k_acts)
                    return
                return

            async with lock:
                settings_inner = raw_to_settings(dict(state.raw))
                pages_inner = state.raw.get("pages") or []
                page_idx = state.page_index
                twitch_raw = state.raw.get("twitch")

            actions: list[dict[str, Any]] = []
            source_cid: str | None = None
            source_entry: dict[str, Any] | None = None
            if isinstance(pages_inner, list) and len(pages_inner) > 0:
                gb = state.raw.get("global_buttons")
                if not isinstance(gb, dict):
                    gb = {}
                source_cid, actions, source_entry = actions_for_page_event(pages_inner, page_idx, ev, global_buttons=gb)
            if not actions:
                actions = actions_for_event(settings_inner.bindings, ev)

            if (
                ev.kind in ("touch", "button")
                and ev.edge == "down"
                and source_cid is not None
                and isinstance(source_entry, dict)
                and str(source_entry.get("press_animation") or "none").strip().lower() != "none"
            ):
                runtime.press_animation_start[source_cid] = runtime.skin_animation_tick
                # Draw the first press-animation frame right away: some button actions (sound.play,
                # http.request, ...) never trigger a redraw of their own, and waiting for the next
                # skin_animation_loop tick would skip straight past frame 0 (e.g. invert's blink).
                await redraw_skin("press_animation")
            if not actions:
                return
            if source_cid is not None:
                ctx.source_control_id = source_cid
                ctx.source_storage_key = preview_storage_key(source_cid, int(page_idx))
            else:
                ctx.source_control_id = None
                ctx.source_storage_key = None
            ctx.on_action_error = None
            ctx.on_action_success = None
            # Twitch multi-account context (for twitch.* actions).
            accounts: list[dict[str, Any]] = []
            if isinstance(twitch_raw, list):
                accounts = [a for a in twitch_raw if isinstance(a, dict)]
            elif isinstance(twitch_raw, dict) and twitch_raw:
                accounts = [dict(twitch_raw)]
            ctx.twitch_accounts = accounts or None
            ctx.twitch_account = accounts[0] if accounts else None
            if ctx.source_storage_key is not None:
                sk = ctx.source_storage_key
                # Clear any previous red-outline marker on each press/turn; if something fails below,
                # we'll set it again with the latest error.
                runtime.set_control_error(sk, None)

                def _on_action_error(kind: str, _params: dict[str, Any], err: BaseException) -> None:
                    k = (kind or "").strip()
                    msg = str(err).strip() or "error"
                    # Keep the message short for hover tooltips.
                    if len(msg) > 160:
                        msg = msg[:157] + "…"
                    runtime.set_control_error(sk, f"{k} failed: {msg}" if k else msg)

                def _on_action_success(kind: str, _params: dict[str, Any]) -> None:
                    k = (kind or "").strip()
                    if k in ("sound.play", "overlay.show_media", "overlay.play_sound"):
                        runtime.set_control_error(sk, None)

                ctx.on_action_error = _on_action_error
                ctx.on_action_success = _on_action_success
            ctx.obs = obs
            ctx.pages = navigator
            await run_actions(ctx, actions)

        def thread_callback(_deck: Any, msg: dict[str, Any]) -> None:
            def schedule() -> None:
                task = asyncio.create_task(handle_raw_message(msg))

                def _done(t: asyncio.Task[None]) -> None:
                    if t.cancelled():
                        return
                    exc = t.exception()
                    if exc is not None:
                        logger.exception("Unhandled error in Loupedeck handler", exc_info=exc)

                task.add_done_callback(_done)

            loop.call_soon_threadsafe(schedule)

        async def reconnect_loop() -> None:
            while True:
                await asyncio.sleep(2.0)
                if runtime.no_device or runtime.intentional_deck_shutdown:
                    return
                if not runtime.deck_unplugged:
                    continue
                try:
                    new_deck = _open_deck(state.settings())
                except Exception as e:
                    logger.debug("Loupedeck reconnect: not available yet: %s", e)
                    continue
                old = runtime.deck
                runtime.deck = new_deck
                runtime.deck_unplugged = False
                if old is not None and old is not new_deck:
                    with contextlib.suppress(Exception):
                        old.stop()
                try:
                    new_deck.start()
                    if hasattr(new_deck, "set_brightness"):
                        with contextlib.suppress(Exception):
                            new_deck.set_brightness(80)
                    new_deck.set_callback(thread_callback)
                    logger.info(
                        "Loupedeck reconnected (%s, %s)",
                        getattr(new_deck, "path", "?"),
                        type(new_deck).__name__,
                    )
                    await redraw_skin("deck_reconnect")
                except Exception:
                    logger.exception("Loupedeck reconnect setup failed; will retry")
                    runtime.deck_unplugged = True
                    runtime.deck = old
                    with contextlib.suppress(Exception):
                        new_deck.stop()

        reconnect_task: asyncio.Task[None] | None = None
        if not runtime.no_device:
            reconnect_task = asyncio.create_task(reconnect_loop())

        if runtime.deck is not None:
            runtime.deck.start()
            try:
                if hasattr(runtime.deck, "set_brightness"):
                    try:
                        runtime.deck.set_brightness(80)
                    except Exception:
                        logger.debug("Could not set brightness", exc_info=True)
                if navigator is not None:
                    await redraw_skin("agent_startup")
            except Exception:
                logger.exception("Initial skin draw failed")

            runtime.deck.set_callback(thread_callback)

        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        runtime.simulate_raw_message = handle_raw_message
        try:
            await fut
        finally:
            runtime.simulate_raw_message = None
            runtime.intentional_deck_shutdown = True
            set_serial_fatal_callback(None)
            if reconnect_task is not None:
                reconnect_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reconnect_task
            live_task.cancel()
            skin_anim_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await live_task
            with contextlib.suppress(asyncio.CancelledError):
                await skin_anim_task
            if runtime.deck is not None:
                try:
                    runtime.deck.stop()
                except Exception:
                    logger.exception("Error while stopping Loupedeck reader")
            if obs:
                try:
                    await asyncio.shield(obs.close())
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Error while closing OBS WebSocket")


def _parse_web_arg(s: str | None) -> tuple[str, int] | None:
    if not s:
        return None
    if ":" in s:
        host, _, port_s = s.partition(":")
        return host.strip() or "127.0.0.1", int(port_s)
    return "127.0.0.1", int(s)


async def _async_main(
    config_path: Path,
    verbose: bool,
    web: str | None,
    no_device: bool,
    log_dir: Path | None,
    handle: AgentHandle | None = None,
) -> None:
    shutdown_requested = asyncio.Event()

    def _request_shutdown() -> None:
        shutdown_requested.set()

    loop = asyncio.get_running_loop()
    if handle is not None:
        handle._bind(loop, shutdown_requested)
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_shutdown)

    raw = load_raw_for_logging(config_path)
    bootstrap_logging(
        verbose=verbose,
        log_dir_override=log_dir,
        file_enabled=True,
        console_enabled=True,
        level_from_config=None,
        raw=raw,
    )
    state = ConfigState(config_path)
    logger.info("Config file %s (pages=%s)", config_path, len(state.raw.get("pages") or []))
    lock = asyncio.Lock()
    runtime = AgentRuntimeRefs()
    runtime.startup_verbose = verbose
    runtime.log_dir_override = log_dir
    runtime.overlay_hub = OverlayHub()
    runtime.no_device = no_device
    deck: LoupedeckLive | None = None
    if not no_device:
        try:
            deck = _open_deck(state.settings())
        except Exception as e:
            logger.warning("Loupedeck not available (%s). Actions will not run until device works.", e)
            if not web:
                raise SystemExit(1) from e
            # Startup failed (e.g. device not plugged in yet, or its port briefly busy) --
            # let reconnect_loop keep retrying instead of giving up on the device forever.
            runtime.deck_unplugged = True

    runtime.deck = deck

    config_dir = config_path.parent.resolve()
    spotify_mgr = SpotifyManager(
        config_dir / "spotify_tokens.json",
        lambda: dict(state.raw.get("spotify") or {}),
    )
    redraw_skin_lock = asyncio.Lock()
    # Monotonic redraw counter for log correlation only (not errors, not memory).
    redraw_seq = count(1)

    async def redraw_skin(reason: str = "unspecified") -> None:
        """Serialize skin draws so two callers (e.g. Apply + live_message) cannot interleave threads."""

        rid = next(redraw_seq)
        async with redraw_skin_lock:
            logger.debug("redraw_skin #%s start reason=%s", rid, reason)
            d = runtime.deck
            if d is None:
                logger.debug("redraw_skin #%s end (no deck)", rid)
                return
            async with lock:
                pages = state.raw.get("pages") or []
                if not pages or not isinstance(pages, list):
                    logger.debug("redraw_skin #%s end (no pages)", rid)
                    return
                idx = state.page_index % len(pages)
                page = pages[idx]
                gb = state.raw.get("global_buttons")
                if not isinstance(gb, dict):
                    gb = {}
                live_snap = dict(runtime.live_message_text)

            logger.debug(
                "redraw_skin #%s snapshot page_index=%s page=%r overlay_cache_entries=%d "
                "page_button_keys=%d global_keys=%d",
                rid,
                idx,
                page.get("name"),
                len(live_snap),
                len(page.get("buttons") or {}) if isinstance(page.get("buttons"), dict) else 0,
                len(gb),
            )

            def _draw() -> None:
                apply_page_skin(
                    d,
                    page,
                    config_dir,
                    global_buttons=gb,
                    page_index=idx,
                    live_text=live_snap,
                    redraw_id=rid,
                    redraw_reason=reason,
                    animation_frame=runtime.skin_animation_tick,
                    press_animation_start=dict(runtime.press_animation_start),
                    current_tick=runtime.skin_animation_tick,
                )

            await asyncio.to_thread(_draw)
            logger.debug("redraw_skin #%s done reason=%s", rid, reason)

    web_addr = _parse_web_arg(web)
    server: Any = None
    uvicorn_task: asyncio.Task[Any] | None = None

    if web_addr:
        import uvicorn

        from .web_app import create_web_app

        host, port = web_addr

        async def on_refresh_skin() -> None:
            await redraw_skin("web_refresh_skin")

        app = create_web_app(
            config_path,
            state,
            lock,
            on_refresh=on_refresh_skin,
            runtime=runtime,
            spotify=spotify_mgr,
        )

        class _EmbeddedUvicornServer(uvicorn.Server):
            """Avoid registering SIGINT/SIGTERM; asyncio owns signal handling."""

            @contextlib.contextmanager
            def capture_signals(self):
                yield

        cfg = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            log_config=None,
            # Default None = wait indefinitely for keep-alive HTTP (e.g. UI polling /api/status) and WS.
            timeout_graceful_shutdown=5,
            timeout_keep_alive=2,
        )
        server = _EmbeddedUvicornServer(cfg)
        uvicorn_task = asyncio.create_task(server.serve())

    agent_task = asyncio.create_task(run_agent(state, lock, redraw_skin, runtime, spotify_mgr))
    worker_tasks: list[asyncio.Task[Any]] = [agent_task]
    if uvicorn_task is not None:
        worker_tasks.append(uvicorn_task)

    shutdown_task = asyncio.create_task(shutdown_requested.wait())
    wait_set: set[asyncio.Task[Any]] = {shutdown_task, *worker_tasks}
    done, _pending = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)

    if shutdown_task in done:
        logger.info("Shutting down (cancel requested)…")
        if server is not None:
            server.should_exit = True
        if not agent_task.done():
            agent_task.cancel()
        remaining = [t for t in worker_tasks if not t.done()]
        if remaining:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*remaining, return_exceptions=True),
                    timeout=12.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Shutdown timed out; forcing stop.")
                for t in remaining:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*remaining, return_exceptions=True)
        shutdown_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await shutdown_task
        logger.info("Stopped.")
        return

    shutdown_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await shutdown_task

    for finished in done:
        if finished is shutdown_task:
            continue
        exc = finished.exception()
        for t in worker_tasks:
            if t is not finished and not t.done():
                t.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        if exc is not None:
            raise exc
        return


DEFAULT_WEB_ADDR = "127.0.0.1:8765"


class AgentHandle:
    """Cross-thread handle for an agent started via :func:`start_agent_in_background_thread`.

    ``asyncio.Event`` and event loops are not thread-safe to touch directly; this hands the
    calling thread a safe way to request shutdown and wait for the agent thread to finish.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._shutdown_requested: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._bound = threading.Event()

    def _bind(self, loop: asyncio.AbstractEventLoop, shutdown_requested: asyncio.Event) -> None:
        self._loop = loop
        self._shutdown_requested = shutdown_requested
        self._bound.set()

    def request_shutdown(self) -> None:
        """Safe to call from any thread (e.g. a tray icon's "Quit" handler)."""

        if not self._bound.wait(timeout=5.0) or self._loop is None or self._shutdown_requested is None:
            logger.warning("AgentHandle.request_shutdown: agent never finished starting up")
            return
        self._loop.call_soon_threadsafe(self._shutdown_requested.set)

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


def start_agent_in_background_thread(
    config_path: Path,
    *,
    verbose: bool = False,
    web: str | None = DEFAULT_WEB_ADDR,
    no_device: bool = False,
    log_dir: Path | None = None,
) -> AgentHandle:
    """Run the agent (and optional web UI) on a dedicated thread with its own event loop.

    For embedding in a host process that owns the main thread for its own GUI loop
    (system tray icon, native window), instead of the CLI's ``asyncio.run`` in ``main()``.
    """

    handle = AgentHandle()

    def _runner() -> None:
        try:
            asyncio.run(_async_main(config_path, verbose, web, no_device, log_dir, handle=handle))
        except Exception:
            logger.exception("Agent thread crashed")

    thread = threading.Thread(target=_runner, name="open-loupedeck", daemon=True)
    handle._thread = thread
    thread.start()
    return handle


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Loupedeck background agent (Windows, macOS, Linux): OBS, HTTP, sounds, web UI"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="Path to config YAML",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--web",
        nargs="?",
        const=DEFAULT_WEB_ADDR,
        default=None,
        metavar="HOST:PORT",
        help=f"Serve configuration UI (default {DEFAULT_WEB_ADDR} if flag is present)",
    )
    parser.add_argument(
        "--no-device",
        action="store_true",
        help="Do not open Loupedeck (useful with --web for offline editing)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Write open-loupedeck.log here (overrides logging.dir in config)",
    )
    args = parser.parse_args()

    async def runner() -> None:
        await _async_main(args.config, args.verbose, args.web, args.no_device, args.log_dir)

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        logger.info("Interrupted.")


if __name__ == "__main__":
    main()
