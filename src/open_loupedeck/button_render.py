"""Render tactile key surfaces (text ± background image) for Loupedeck RGB buffers.

Design rule (see the plan / project memory): any feature that puts text on a physical key must
be (1) previewable in the config UI before it is ever sent to the device, and (2) fully
customizable -- font, size, solid color or 2-stop gradient, solid or gradient background, a
continuous "idle" animation, and a one-shot "press" animation. This module is where that
contract is implemented; ``/api/preview_key`` in ``web_app.py`` renders through the exact same
code path so the UI preview always matches the device.
"""

from __future__ import annotations

import colorsys
import contextlib
import logging
import math
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFile, ImageFont, ImageOps

from .icon_loader import load_icon_image, looks_like_icon_uri
from .key_media_cache import (
    VIDEO_EXTENSIONS,
    is_video_path,
    resolve_config_media_path,
    resolve_graphic_load_path,
)
from .logging_setup import default_icon_cache_dir

ImageFile.LOAD_TRUNCATED_IMAGES = True

logger = logging.getLogger(__name__)

# Raster / GIF / video paths on ``overlay.show_media`` double as key graphics when ``image``/``icon`` are unset.
_OVERLAY_GRAPHIC_SUFFIXES = frozenset({".gif", ".png", ".jpg", ".jpeg", ".webp"}) | VIDEO_EXTENSIONS

DEFAULT_KEY_SIZE = (90, 90)
STRIP_SIZE = (60, 270)

# A one-shot press animation plays over this many ~100ms skin_animation_loop ticks (app.py).
# slide_reappear packs two movements (out, then back in) into its window, so it gets more ticks
# than the single-phase effects to avoid feeling rushed.
PRESS_ANIMATION_DURATION_TICKS = 4
_PRESS_ANIMATION_DURATION_OVERRIDES = {"slide_reappear": 8}
PRESS_ANIMATION_MAX_DURATION_TICKS = max(PRESS_ANIMATION_DURATION_TICKS, *_PRESS_ANIMATION_DURATION_OVERRIDES.values())

IDLE_ANIMATION_TYPES = frozenset({"none", "shake", "pulse", "gradient_rotate", "color_cycle"})
PRESS_ANIMATION_TYPES = frozenset({"none", "flash", "invert", "zoom_text", "slide_reappear"})
PRESS_SLIDE_DIRECTIONS = frozenset({"left", "right", "up", "down"})


def _press_animation_duration_ticks(press_type: str) -> int:
    return _PRESS_ANIMATION_DURATION_OVERRIDES.get(press_type, PRESS_ANIMATION_DURATION_TICKS)


def _press_progress(press_type: str, press_elapsed_frames: int) -> float:
    duration = _press_animation_duration_ticks(press_type)
    return max(0.0, min(1.0, press_elapsed_frames / duration))


# Split layout (graphic top / text bottom): shifts for on-device vs layout alignment.
SPLIT_GRAPHIC_OFFSET_Y = 10
SPLIT_TEXT_BAND_OFFSET_Y = -20

# Inset icons/images from the key rectangle; on-device keys show a smaller “window” than 90×90.
_GRAPHIC_PAD_MIN = 4
_GRAPHIC_PAD_MAX = 14
_GRAPHIC_PAD_FRAC_NUM = 9  # min side * num / 100


def _graphic_padding(w: int, h: int) -> int:
    """Symmetric padding (px) so graphics do not fill the full bitmap (matches visible key area)."""

    m = min(w, h)
    return max(_GRAPHIC_PAD_MIN, min(_GRAPHIC_PAD_MAX, m * _GRAPHIC_PAD_FRAC_NUM // 100))


def _font_candidates() -> tuple[str, ...]:
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        return (
            str(Path(windir) / "Fonts" / "segoeui.ttf"),
            str(Path(windir) / "Fonts" / "arial.ttf"),
            str(Path(windir) / "Fonts" / "calibri.ttf"),
        )
    if sys.platform == "darwin":
        return (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        )
    return (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    )


def _parse_color(raw: str | None, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not raw:
        return fallback
    s = str(raw).strip()
    if s.startswith("#") and len(s) == 7:
        try:
            return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), 255)
        except ValueError:
            pass
    try:
        from PIL import ImageColor

        rgba = ImageColor.getrgb(s)
        if len(rgba) == 3:
            return (*rgba, 255)
        return rgba  # type: ignore[return-value]
    except Exception:
        return fallback


def _make_gradient_rgba(
    size: tuple[int, int],
    color_from: tuple[int, int, int, int],
    color_to: tuple[int, int, int, int],
    angle_deg: float,
) -> Image.Image:
    """2-stop linear gradient, ``size``, rotated to ``angle_deg`` (0 = top-to-bottom)."""

    w, h = size
    diag = int(math.hypot(w, h)) + 2
    grad_l = Image.linear_gradient("L").resize((diag, diag))
    rotated = grad_l.rotate(angle_deg % 360, resample=Image.Resampling.BICUBIC)
    left = (rotated.width - w) // 2
    top = (rotated.height - h) // 2
    cropped = rotated.crop((left, top, left + w, top + h))
    rgba = ImageOps.colorize(cropped, black=color_from[:3], white=color_to[:3]).convert("RGBA")
    avg_alpha = (color_from[3] + color_to[3]) // 2
    if avg_alpha < 255:
        rgba.putalpha(Image.new("L", size, avg_alpha))
    return rgba


def _hsv_color(hue_deg: float, alpha: int) -> tuple[int, int, int, int]:
    r, g, b = colorsys.hsv_to_rgb((hue_deg % 360) / 360.0, 1.0, 1.0)
    return (round(r * 255), round(g * 255), round(b * 255), alpha)


def _composite_fill_through_mask(
    img: Image.Image,
    mask: Image.Image,
    fg: tuple[int, int, int, int],
    gradient: Image.Image | None,
    offset: tuple[int, int] = (0, 0),
    alpha_scale: float = 1.0,
) -> None:
    """Paste a solid color or gradient onto ``img`` wherever ``mask`` (an 'L' image) is set.

    ``offset`` shifts the mask (used for the ``shake`` idle animation and the ``slide_reappear``
    press animation); ``alpha_scale`` dims the whole fill (used for the ``pulse`` idle animation).
    """

    w, h = img.size
    if offset != (0, 0):
        shifted = Image.new("L", (w, h), 0)
        shifted.paste(mask, offset)
        mask = shifted
    if alpha_scale < 1.0:
        mask = mask.point(lambda a: int(a * alpha_scale))

    if fg[3] < 255 and gradient is None:
        # Faint dark halo around the glyphs so semi-transparent text stays legible over graphics
        # (dilate the mask by 1px in each direction, then a soft dark fill through that halo).
        halo = mask
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shifted = Image.new("L", (w, h), 0)
            shifted.paste(mask, (dx, dy))
            halo = ImageChops.lighter(halo, shifted)
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, min(200, fg[3] + 60)))
        img.paste(shadow, (0, 0), halo)

    fill_img = gradient if gradient is not None else Image.new("RGBA", (w, h), fg)
    img.paste(fill_img, (0, 0), mask)


def _resolve_font_path(raw: str | None, config_dir: Path) -> str | None:
    """Absolute path to a usable font file, or ``None``."""

    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    p = resolve_config_media_path(s, config_dir)
    if p is not None and p.is_file():
        return str(p.resolve())
    p2 = Path(s).expanduser()
    if p2.is_file():
        return str(p2.resolve())
    return None


def _load_font(size: int, resolved_font_path: str | None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if resolved_font_path:
        try:
            return ImageFont.truetype(resolved_font_path, size=size)
        except Exception:
            logger.debug("Could not load font %s", resolved_font_path, exc_info=True)
    for path in _font_candidates():
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                logger.debug("Could not load font %s", path, exc_info=True)
                continue
    return ImageFont.load_default()


def _wrap_lines(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    draw: ImageDraw.ImageDraw,
    max_width: int,
) -> list[str]:
    """Word-wrap within each line; newline characters start a new line (no merging across ``\\n``)."""

    text = text.replace("\r", "")
    out: list[str] = []
    for block in text.split("\n"):
        words = block.split()
        if not words:
            continue
        line = words[0]
        for word in words[1:]:
            test = f"{line} {word}"
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                line = test
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def _draw_multiline_center(
    img: Image.Image,
    text: str,
    fg: tuple[int, int, int, int],
    resolved_font_path: str | None,
    font_size_cap: int | None,
    *,
    gradient: Image.Image | None = None,
    offset: tuple[int, int] = (0, 0),
    alpha_scale: float = 1.0,
) -> None:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    margin = max(4, min(w, h) // 14)
    max_w = w - 2 * margin
    max_h = h - 2 * margin
    cap = font_size_cap or min(22, h // 3, w // 4)

    for fs in range(min(cap, 28), 7, -1):
        font = _load_font(fs, resolved_font_path)
        lines = _wrap_lines(text, font, draw, max_w)
        heights = []
        widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            heights.append(bbox[3] - bbox[1])
            widths.append(bbox[2] - bbox[0])
        gap = 2
        total_h = sum(heights) + gap * max(0, len(lines) - 1)
        if total_h <= max_h and (not widths or max(widths) <= max_w):
            y = (h - total_h) // 2
            for i, line in enumerate(lines):
                bbox = draw.textbbox((0, 0), line, font=font)
                lw = bbox[2] - bbox[0]
                x = (w - lw) // 2
                draw.text((x, y), line, font=font, fill=255)
                y += heights[i] + gap
            _composite_fill_through_mask(img, mask, fg, gradient, offset, alpha_scale)
            return
    logger.warning("Text did not fit on key: %r", text[:40])


def _draw_multiline_bottom_band(
    img: Image.Image,
    text: str,
    fg: tuple[int, int, int, int],
    resolved_font_path: str | None,
    font_size_cap: int | None,
    y_top: int,
    y_bottom: int,
    *,
    gradient: Image.Image | None = None,
    offset: tuple[int, int] = (0, 0),
    alpha_scale: float = 1.0,
) -> None:
    """Draw wrapped text bottom-aligned in the horizontal band [y_top, y_bottom]."""

    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    margin_x = max(2, min(w, h) // 14)
    margin_bot = max(2, min(w, h) // 16)
    inner_top = y_top + 1
    inner_bottom = min(y_bottom, h) - margin_bot
    max_w = w - 2 * margin_x
    max_h = max(4, inner_bottom - inner_top)
    cap = font_size_cap or min(14, max_h // 2, w // 4)

    for fs in range(min(cap, 22), 6, -1):
        font = _load_font(fs, resolved_font_path)
        lines = _wrap_lines(text, font, draw, max_w)
        if not lines:
            return
        heights = []
        widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            heights.append(bbox[3] - bbox[1])
            widths.append(bbox[2] - bbox[0])
        gap = 1
        total_h = sum(heights) + gap * max(0, len(lines) - 1)
        if total_h <= max_h and (not widths or max(widths) <= max_w):
            y = inner_bottom - total_h
            y = max(y, inner_top)
            for i, line in enumerate(lines):
                bbox = draw.textbbox((0, 0), line, font=font)
                lw = bbox[2] - bbox[0]
                x = (w - lw) // 2
                draw.text((x, y), line, font=font, fill=255)
                y += heights[i] + gap
            _composite_fill_through_mask(img, mask, fg, gradient, offset, alpha_scale)
            return
    logger.warning("Text did not fit in bottom band: %r", text[:40])


def _load_gif_frame_rgba(path: Path, animation_frame: int | None) -> Image.Image | None:
    """Decode one GIF frame as RGBA (``seek`` + ``load`` before convert avoids stale buffers)."""

    with Image.open(path) as im:
        n = int(getattr(im, "n_frames", 1) or 1)
        if n > 1:
            im.seek((animation_frame if animation_frame is not None else 0) % n)
        im.load()
        return im.convert("RGBA").copy()


def _load_graphic_rgba(
    raw_img: str,
    config_dir: Path,
    icon_cache_dir: Path | None,
    raster_size: tuple[int, int],
    animation_frame: int | None = None,
) -> Image.Image | None:
    rs = str(raw_img).strip()
    if looks_like_icon_uri(rs):
        ic_dir = icon_cache_dir if icon_cache_dir is not None else default_icon_cache_dir()
        return load_icon_image(rs, ic_dir, raster_size)
    path = resolve_graphic_load_path(rs, config_dir)
    if path and path.is_file():
        try:
            if path.suffix.lower() == ".gif":
                rgba = _load_gif_frame_rgba(path, animation_frame)
                if rgba is None:
                    return None
                return ImageOps.fit(rgba, raster_size, method=Image.Resampling.LANCZOS)
            with Image.open(path) as im:
                im.load()
                rgba = im.convert("RGBA")
                return ImageOps.fit(rgba.copy(), raster_size, method=Image.Resampling.LANCZOS)
        except Exception:
            logger.exception("Could not load key image %s", path)
            return None
    resolved = resolve_config_media_path(rs, config_dir)
    if resolved is not None and resolved.is_file() and is_video_path(resolved):
        if shutil.which("ffmpeg") is None:
            logger.warning(
                "Video on key needs ffmpeg to build a preview GIF (file is OK: %s). "
                "Install ffmpeg and restart, or set image/icon to a PNG/GIF instead.",
                raw_img,
            )
        else:
            logger.warning(
                "Could not use video as key graphic (see earlier ffmpeg errors): %s",
                raw_img,
            )
        return None
    logger.warning("Key image path not found: %s", raw_img)
    return None


def _overlay_show_media_path(entry: dict[str, Any]) -> str | None:
    """``file`` / ``path`` from the first ``overlay.show_media`` action (singular or list)."""

    def from_act(a: Any) -> str | None:
        if not isinstance(a, dict) or str(a.get("type") or "") != "overlay.show_media":
            return None
        v = a.get("file") or a.get("path")
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    a1 = entry.get("action")
    if isinstance(a1, dict):
        hit = from_act(a1)
        if hit:
            return hit
    acts = entry.get("actions")
    if isinstance(acts, list):
        for a in acts:
            if isinstance(a, dict):
                hit = from_act(a)
                if hit:
                    return hit
    return None


def _implicit_graphic_from_overlay(entry: dict[str, Any]) -> str | None:
    for key in ("image", "icon"):
        v = entry.get(key)
        if v is not None and str(v).strip():
            return None
    raw = _overlay_show_media_path(entry)
    if not raw:
        return None
    suf = Path(raw.split("?", 1)[0].split("#", 1)[0]).suffix.lower()
    if suf in _OVERLAY_GRAPHIC_SUFFIXES:
        return raw
    return None


def effective_graphic_source(entry: dict[str, Any]) -> str | None:
    """File / icon URI used as the key bitmap: explicit ``image``/``icon``, else overlay media path."""

    for key in ("image", "icon"):
        v = entry.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return _implicit_graphic_from_overlay(entry)


def _graphic_text_layout_mode(entry: dict[str, Any]) -> str:
    """
    How to combine a graphic (``image`` / ``icon``) with text.

    - ``split`` (default): graphic in the top band, text in the bottom band.
    - ``overlay``: full-key graphic with text centered on top.

    Aliases: ``overlay`` / ``overlap`` / ``on_graphic``; ``split`` / ``vertical`` / ``stacked`` (vertical sections).
    """

    raw = (
        str(entry.get("graphic_text_layout") or entry.get("text_graphic_layout") or "")
        .strip()
        .lower()
        .replace("-", "_")
    )
    overlay = frozenset({"overlay", "overlap", "on_graphic", "stacked_on_graphic", "center"})
    split = frozenset({"split", "vertical", "sections", "top_bottom", "icon_top", "stacked"})
    if raw in overlay:
        return "overlay"
    if raw in split:
        return "split"
    return "split"


def _idle_animation_type(entry: dict[str, Any]) -> str:
    v = str(entry.get("idle_animation") or "none").strip().lower()
    return v if v in IDLE_ANIMATION_TYPES else "none"


def _press_animation_type(entry: dict[str, Any]) -> str:
    v = str(entry.get("press_animation") or "none").strip().lower()
    return v if v in PRESS_ANIMATION_TYPES else "none"


def _idle_speed(entry: dict[str, Any]) -> float:
    raw = entry.get("idle_animation_speed")
    if raw is None or raw == "":
        return 1.0
    try:
        s = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return max(0.1, min(10.0, s))


def _gradient_spec_from_entry(
    entry: dict[str, Any],
    from_key: str,
    to_key: str,
    angle_key: str,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], float] | None:
    """``(color_from, color_to, angle)`` if both endpoint colors are set, else None."""

    raw_from = entry.get(from_key)
    raw_to = entry.get(to_key)
    if not raw_from or not raw_to:
        return None
    color_from = _parse_color(raw_from, (255, 255, 255, 255))
    color_to = _parse_color(raw_to, (255, 255, 255, 255))
    try:
        angle = float(entry.get(angle_key) or 0.0)
    except (TypeError, ValueError):
        angle = 0.0
    return color_from, color_to, angle


def _resolve_text_fill(
    entry: dict[str, Any],
    size: tuple[int, int],
    fg: tuple[int, int, int, int],
    animation_frame: int | None,
    press_elapsed_frames: int | None,
) -> tuple[tuple[int, int, int, int], Image.Image | None, tuple[int, int], float]:
    """Text fill for the current frame: ``(fg, gradient_or_None, offset, alpha_scale)``.

    A press animation (if one is currently playing on this key) takes priority over the idle
    animation -- idle effects pause for the ~400ms the press flourish plays, then resume.
    """

    text_grad = _gradient_spec_from_entry(entry, "text_gradient_from", "text_gradient_to", "text_gradient_angle")
    offset = (0, 0)
    alpha_scale = 1.0
    gradient_img: Image.Image | None = None

    if press_elapsed_frames is not None:
        press_type = _press_animation_type(entry)
        if press_type == "slide_reappear":
            p = _press_progress(press_type, press_elapsed_frames)
            frac = (p / 0.5) if p < 0.5 else (1 - (p - 0.5) / 0.5)
            direction = str(entry.get("press_animation_direction") or "left").strip().lower()
            if direction not in PRESS_SLIDE_DIRECTIONS:
                direction = "left"
            w, h = size
            if direction == "left":
                offset = (-round(w * frac), 0)
            elif direction == "right":
                offset = (round(w * frac), 0)
            elif direction == "up":
                offset = (0, -round(h * frac))
            else:  # down
                offset = (0, round(h * frac))
        # flash/invert/zoom_text/none need no text-mask change: zoom scales the font size cap
        # (see _effective_font_size_cap); flash/invert are whole-key post-effects (see below).
    else:
        idle_type = _idle_animation_type(entry)
        if idle_type != "none":
            phase = (animation_frame or 0) * _idle_speed(entry)
            if idle_type == "shake":
                amp = max(1.0, min(size) * 0.035)
                offset = (round(math.sin(phase * 0.6) * amp), round(math.cos(phase * 0.9) * amp * 0.6))
            elif idle_type == "pulse":
                alpha_scale = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(phase * 0.5))
            elif idle_type == "color_cycle":
                fg = _hsv_color(phase * 6, fg[3])
            elif idle_type == "gradient_rotate" and text_grad is not None:
                color_from, color_to, base_angle = text_grad
                gradient_img = _make_gradient_rgba(size, color_from, color_to, base_angle + phase * 6)

    if gradient_img is None and text_grad is not None:
        color_from, color_to, angle = text_grad
        gradient_img = _make_gradient_rgba(size, color_from, color_to, angle)

    return fg, gradient_img, offset, alpha_scale


def _effective_font_size_cap(
    raw_cap: Any,
    entry: dict[str, Any],
    press_elapsed_frames: int | None,
) -> Any:
    """Scale the font-size cap up for the ``zoom_text`` press animation, else pass through unchanged."""

    if press_elapsed_frames is None or _press_animation_type(entry) != "zoom_text":
        return raw_cap
    p = _press_progress("zoom_text", press_elapsed_frames)
    scale = 1.0 + 0.3 * (1.0 - p)
    base_val = int(raw_cap) if raw_cap else 18
    return max(6, round(base_val * scale))


def _resolve_background(
    entry: dict[str, Any],
    size: tuple[int, int],
    bg: tuple[int, int, int, int],
    animation_frame: int | None,
) -> Image.Image:
    bg_grad = _gradient_spec_from_entry(
        entry, "background_gradient_from", "background_gradient_to", "background_gradient_angle"
    )
    if bg_grad is None:
        return Image.new("RGBA", size, bg)

    color_from, color_to, angle = bg_grad
    if _idle_animation_type(entry) == "gradient_rotate":
        angle = angle + (animation_frame or 0) * _idle_speed(entry) * 6
    return _make_gradient_rgba(size, color_from, color_to, angle)


def _apply_whole_key_press_effect(
    base: Image.Image,
    entry: dict[str, Any],
    press_elapsed_frames: int | None,
) -> Image.Image:
    """``flash`` / ``invert`` act on the fully-composed key image, not just the text layer."""

    if press_elapsed_frames is None:
        return base
    press_type = _press_animation_type(entry)
    if press_type not in ("flash", "invert"):
        return base
    if press_type == "flash":
        # Smooth glow, brightest at the moment of the press, fading out.
        envelope = 1.0 - _press_progress(press_type, press_elapsed_frames)
        flash_rgb = _parse_color(entry.get("press_flash_color"), (255, 255, 255, 255))[:3]
        overlay = Image.new("RGBA", base.size, (*flash_rgb, round(200 * envelope)))
        return Image.alpha_composite(base, overlay)
    # A single-tick blink rather than a fade: distinct from flash's smooth glow, and short enough
    # that repeated presses read as repeated blinks instead of one continuously-inverted key (see
    # the immediate redraw_skin("press_animation") in app.py, which makes sure this first tick is
    # never skipped even when the button's own action doesn't otherwise trigger a redraw).
    if press_elapsed_frames == 0:
        inverted = ImageOps.invert(base.convert("RGB")).convert("RGBA")
        inverted.putalpha(base.getchannel("A"))
        return inverted
    return base


def render_tactile_key_image(
    entry: dict[str, Any],
    config_dir: Path,
    size: tuple[int, int] = DEFAULT_KEY_SIZE,
    icon_cache_dir: Path | None = None,
    *,
    animation_frame: int | None = None,
    press_elapsed_frames: int | None = None,
) -> Image.Image | None:
    """
    Build a PIL image for one key.

    - ``text`` / ``label``: with a graphic, layout is controlled by ``graphic_text_layout`` (see
      ``_graphic_text_layout_mode``); with no graphic, text is centered on the key.
    - ``graphic_text_layout``: ``split`` (graphic top / text bottom) or ``overlay`` (text on full
      graphic). Same for both ``image`` and ``icon`` sources.
    - ``image`` / ``icon``: optional graphic (``image`` wins if both set). File path or icon URI
      (``si:``, ``heroicons:``, ``lucide:``, ``mdi:``, ``https://`` SVG).
    - ``background`` / ``text_color``: solid fill colors (default dark navy / white).
    - ``background_gradient_from``/``_to``/``_angle``, ``text_gradient_from``/``_to``/``_angle``:
      optional 2-stop linear gradients that replace the solid ``background``/``text_color`` fill.
    - ``idle_animation`` (``none``/``shake``/``pulse``/``gradient_rotate``/``color_cycle``) +
      ``idle_animation_speed``: continuous animation while the key is not being pressed, driven by
      ``animation_frame`` (see ``skin_animation_loop`` in ``app.py``).
    - ``press_animation`` (``none``/``flash``/``invert``/``zoom_text``/``slide_reappear``): a
      one-shot effect (~400ms; ``slide_reappear`` runs longer since it packs two movements into
      its window) driven by ``press_elapsed_frames`` (ticks since the key was pressed; ``None``
      when no press animation is currently playing on this key).
    - ``press_animation_direction`` (``left``/``right``/``up``/``down``, default ``left``): which
      way ``slide_reappear`` slides out before sliding back in.
    - ``press_flash_color``: color for the ``flash`` press animation (default white).
    - ``font_size``: optional maximum font size cap.
    - ``font_file``: optional path to a .ttf
    - ``graphic_inset`` / ``image_inset``: optional extra inset in pixels per edge (0–24); default is
      computed from key size so images are not drawn full-bleed on the device.
    - If ``image``/``icon`` are unset, a GIF/video/raster on ``overlay.show_media`` (``file``/``path``)
      is used as the key graphic automatically.
    """

    text = (entry.get("text") or entry.get("label") or "").strip()
    raw_img = effective_graphic_source(entry)
    has_bg_grad = (
        _gradient_spec_from_entry(
            entry, "background_gradient_from", "background_gradient_to", "background_gradient_angle"
        )
        is not None
    )
    has_bg_only = (bool(entry.get("background")) or has_bg_grad) and not text and not raw_img

    if not text and not raw_img and not has_bg_only:
        return None

    w, h = size
    bg = _parse_color(entry.get("background"), (26, 26, 46, 255))
    fg = _parse_color(entry.get("text_color"), (255, 255, 255, 255))
    ff_resolved = _resolve_font_path(entry.get("font_file"), config_dir)
    font_size_cap = _effective_font_size_cap(entry.get("font_size"), entry, press_elapsed_frames)
    text_fg, text_gradient, text_offset, text_alpha_scale = _resolve_text_fill(
        entry, size, fg, animation_frame, press_elapsed_frames
    )

    base = _resolve_background(entry, size, bg, animation_frame)

    gap = max(1, min(w, h) // 24)
    text_band = max(min(int(h * 0.32), max(20, h // 3)), 11)
    if text_band + gap >= h - 4:
        text_band = max(10, h // 4)
    icon_h = max(1, h - text_band - gap)

    layout_overlay = bool(text and raw_img and _graphic_text_layout_mode(entry) == "overlay")

    pad = _graphic_padding(w, h)
    for key in ("graphic_inset", "image_inset"):
        raw_pad = entry.get(key)
        if raw_pad is not None:
            with contextlib.suppress(TypeError, ValueError):
                pad = max(0, min(24, int(raw_pad)))
            break

    graphic: Image.Image | None = None
    paste_xy = (0, 0)
    inner_w, inner_h = w, h
    if raw_img:
        rs = str(raw_img).strip()
        if not text or layout_overlay:
            inner_w = max(1, w - 2 * pad)
            inner_h = max(1, h - 2 * pad)
        else:
            inner_w = max(1, w - 2 * pad)
            inner_h = max(8, icon_h - 2 * pad - SPLIT_GRAPHIC_OFFSET_Y)
        paste_xy = (pad, pad)
        graphic = _load_graphic_rgba(
            rs,
            config_dir,
            icon_cache_dir,
            (inner_w, inner_h),
            animation_frame=animation_frame,
        )

    if text and graphic is not None:
        if layout_overlay:
            fitted = graphic.convert("RGBA")
            if fitted.size != (inner_w, inner_h):
                fitted = ImageOps.fit(fitted, (inner_w, inner_h), method=Image.Resampling.LANCZOS)
            base.paste(fitted, paste_xy, fitted)
            _draw_multiline_center(
                base,
                text,
                text_fg,
                ff_resolved,
                font_size_cap,
                gradient=text_gradient,
                offset=text_offset,
                alpha_scale=text_alpha_scale,
            )
        else:
            top_graphic = graphic.convert("RGBA")
            if top_graphic.size != (inner_w, inner_h):
                top_graphic = ImageOps.fit(top_graphic, (inner_w, inner_h), method=Image.Resampling.LANCZOS)
            gx, gy = paste_xy
            base.paste(top_graphic, (gx, gy + SPLIT_GRAPHIC_OFFSET_Y), top_graphic)
            ty_top = icon_h + gap + SPLIT_TEXT_BAND_OFFSET_Y
            ty_bottom = h + SPLIT_TEXT_BAND_OFFSET_Y
            ty_top = max(0, min(ty_top, h - 6))
            ty_bottom = max(ty_top + 4, min(ty_bottom, h))
            _draw_multiline_bottom_band(
                base,
                text,
                text_fg,
                ff_resolved,
                font_size_cap,
                y_top=ty_top,
                y_bottom=ty_bottom,
                gradient=text_gradient,
                offset=text_offset,
                alpha_scale=text_alpha_scale,
            )
    elif graphic is not None:
        fitted = graphic.convert("RGBA")
        if fitted.size != (inner_w, inner_h):
            fitted = ImageOps.fit(fitted, (inner_w, inner_h), method=Image.Resampling.LANCZOS)
        base.paste(fitted, paste_xy, fitted)
    elif text:
        _draw_multiline_center(
            base,
            text,
            text_fg,
            ff_resolved,
            font_size_cap,
            gradient=text_gradient,
            offset=text_offset,
            alpha_scale=text_alpha_scale,
        )

    return _apply_whole_key_press_effect(base, entry, press_elapsed_frames)


def key_size_for_control(control_id: str) -> tuple[int, int]:
    if control_id in ("strip_left", "strip_right", "left", "right"):
        return STRIP_SIZE
    return DEFAULT_KEY_SIZE
