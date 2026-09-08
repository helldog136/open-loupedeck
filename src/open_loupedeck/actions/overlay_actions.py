"""OBS browser overlay: transparent page; show media / play sound via WebSocket."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .registry import ActionContext, register_action

VIDEO_EXT = frozenset({".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"})
IMGLIKE_EXT = frozenset({".gif", ".webp", ".png", ".jpg", ".jpeg"})


def _resolve_asset_path(rel: str, config_dir: Path | None) -> Path:
    if not config_dir:
        raise ValueError("overlay actions require config_dir (agent with config file)")
    raw = rel.strip().replace("\\", "/")
    if not raw or ".." in raw.split("/"):
        raise ValueError("invalid file path")
    base = config_dir.resolve()
    p = (base / raw).resolve()
    p.relative_to(base)
    if not p.is_file():
        raise ValueError(f"file not found: {rel}")
    return p


def _media_kind(suffix: str) -> str:
    s = suffix.lower()
    if s in VIDEO_EXT:
        return "video"
    if s in IMGLIKE_EXT:
        return "image"
    raise ValueError(
        f"unsupported media type {suffix!r}; use a video ({', '.join(sorted(VIDEO_EXT))}) "
        f"or image / gif ({', '.join(sorted(IMGLIKE_EXT))})"
    )


def _optional_int(params: dict[str, Any], *keys: str) -> int | None:
    """First present numeric value among ``keys``, or ``None``. Empty strings are ignored."""

    for k in keys:
        raw = params.get(k)
        if raw is None or raw == "":
            continue
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            continue
    return None


def _gif_one_loop_duration_sec(path: Path) -> float | None:
    """Sum frame delays for one full loop of an animated GIF (Pillow)."""

    try:
        from PIL import Image

        with Image.open(path) as im:
            if not getattr(im, "is_animated", False):
                return None
            total_ms = 0.0
            n = getattr(im, "n_frames", 1)
            for i in range(n):
                im.seek(i)
                total_ms += float(im.info.get("duration", 100))
            sec = total_ms / 1000.0
            return sec if sec > 0 else None
    except Exception:
        return None


def _optional_duration_sec(params: dict[str, Any]) -> float | None:
    raw = params.get("duration_sec")
    if raw is None or raw == "":
        raw = params.get("duration") or params.get("seconds")
    if raw is None or raw == "":
        return None
    v = float(raw)
    if v <= 0:
        raise ValueError("duration_sec must be positive when set")
    return v


def _as_bool(raw: Any, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    if s in ("1", "true", "yes", "on"):
        return True
    return default


@register_action("overlay.show_media")
class OverlayShowMedia:
    """Show video or image on the OBS overlay (1920×1080). Omit ``x`` / ``y`` / ``width`` to center and
    scale to the largest size that fits (contain). Partial overrides: width only → centered; position only
    (both ``x`` and ``y``) with no width → maximized then placed at that top-left corner."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        hub = ctx.overlay_hub
        if hub is None:
            raise RuntimeError("overlay hub not available (web server not running?)")
        rel = params.get("file") or params.get("path")
        if not rel:
            raise ValueError("overlay.show_media requires file (path under config, e.g. library/videos/a.mp4)")
        rel_s = str(rel).strip()
        path = _resolve_asset_path(rel_s, ctx.config_dir)
        kind = _media_kind(path.suffix)
        x = _optional_int(params, "x", "left")
        y = _optional_int(params, "y", "top")
        width = _optional_int(params, "width", "width_px", "w")
        if width is not None and width < 1:
            raise ValueError("width must be at least 1 when set")
        # Default unmuted so video audio is heard in OBS; set muted: true if autoplay is blocked.
        muted = _as_bool(params.get("muted"), False)
        user_d = _optional_duration_sec(params)
        if user_d is not None:
            duration_sec: float | None = user_d
        elif kind == "video":
            duration_sec = None
        elif path.suffix.lower() == ".gif":
            duration_sec = _gif_one_loop_duration_sec(path)
        else:
            duration_sec = None

        await hub.broadcast(
            {
                "cmd": "media",
                "path": rel_s.replace("\\", "/"),
                "kind": kind,
                "x": x,
                "y": y,
                "width": width,
                "muted": muted,
                "duration_sec": duration_sec,
            }
        )


@register_action("overlay.play_sound")
class OverlayPlaySound:
    """Play an audio file in the OBS overlay page (HTML5 Audio)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        hub = ctx.overlay_hub
        if hub is None:
            raise RuntimeError("overlay hub not available (web server not running?)")
        rel = params.get("file") or params.get("path")
        if not rel:
            raise ValueError("overlay.play_sound requires file (e.g. library/sounds/alert.wav)")
        rel_s = str(rel).strip()
        path = _resolve_asset_path(rel_s, ctx.config_dir)
        if path.suffix.lower() not in frozenset({".wav", ".mp3", ".ogg", ".opus", ".flac", ".m4a", ".aac", ".oga"}):
            ctx.log.warning("overlay.play_sound: unusual extension %s — browser may not decode", path.suffix)
        vol = params.get("volume") or params.get("percent")
        volume = 1.0
        if vol is not None:
            volume = float(vol)
            if volume > 1.5:
                volume = volume / 100.0
            volume = max(0.0, min(1.0, volume))
        await hub.broadcast(
            {
                "cmd": "sound",
                "path": rel_s.replace("\\", "/"),
                "volume": volume,
            }
        )


@register_action("overlay.clear")
class OverlayClear:
    """Remove all media elements from the overlay (stops video; sounds are not cancelled)."""

    async def run(self, ctx: ActionContext, params: dict[str, Any]) -> None:
        hub = ctx.overlay_hub
        if hub is None:
            raise RuntimeError("overlay hub not available (web server not running?)")
        await hub.broadcast({"cmd": "clear"})
