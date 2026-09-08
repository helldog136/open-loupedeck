"""Copy image, video, and sound files referenced by the config into ``library/`` under the config directory.

Touch key graphics (``image`` / ``icon`` URIs), ``sound.play``, ``overlay.show_media``, and
``overlay.play_sound`` paths are normalized on load/save (see ``materialize_external_media``).
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from .icon_loader import looks_like_icon_uri
from .key_media_cache import (
    is_video_path,
    key_video_gif_cache_relpath,
    resolve_config_media_path,
)
from .knob_pages import walk_knob_pages_for_media

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")

# Same extension sets as ``overlay_actions`` (``overlay.show_media``).
_OVERLAY_VIDEO_EXT = frozenset({".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"})
_OVERLAY_IMGLIKE_EXT = frozenset({".gif", ".webp", ".png", ".jpg", ".jpeg"})
FONT_FILE_EXT = frozenset({".ttf", ".otf", ".ttc"})


def _norm(s: str) -> str:
    return s.replace("\\", "/").strip()


def _is_managed_media_ref(s: str) -> bool:
    """Path is already stored under our config tree (no copy needed)."""

    p = _norm(s)
    return p.startswith(
        (
            "assets/",
            "library/images/",
            "library/sounds/",
            "library/videos/",
            "library/fonts/",
            "library/generated/",
        )
    )


def _safe_filename(name: str) -> str:
    n = Path(name).name
    n = _SAFE_NAME.sub("_", n)
    return n if n and not n.startswith(".") else "file.bin"


def _resolve_existing_file(raw: str, config_dir: Path) -> Path | None:
    """Same rules as key graphics: legacy relative paths and ``library/`` shortcuts."""

    return resolve_config_media_path(raw, config_dir)


def _copy_to_library(
    src: Path,
    config_dir: Path,
    subdir: str,
) -> str:
    dest_dir = config_dir / "library" / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    unique = f"{uuid.uuid4().hex[:8]}_{_safe_filename(src.name)}"
    dest = dest_dir / unique
    shutil.copy2(src, dest)
    rel = dest.relative_to(config_dir).as_posix()
    logger.info("Copied media into config library: %s -> %s", src, rel)
    return rel


def _materialize_image_value(raw: str, config_dir: Path) -> tuple[str, bool]:
    s = raw.strip()
    if not s or looks_like_icon_uri(s) or _is_managed_media_ref(s):
        return raw, False
    path = _resolve_existing_file(s, config_dir)
    if path is None:
        logger.warning("Image path not found, not copying: %s", raw)
        return raw, False
    try:
        path.relative_to(config_dir.resolve())
    except ValueError:
        rel = _copy_to_library(path, config_dir, "images")
        return rel, True
    # Inside config dir but not under assets/ or library/ — duplicate into library/images
    rel_self = path.relative_to(config_dir.resolve()).as_posix()
    if _is_managed_media_ref(rel_self):
        return rel_self.replace("\\", "/"), False
    rel = _copy_to_library(path, config_dir, "images")
    return rel, True


def _materialize_font_value(raw: str, config_dir: Path) -> tuple[str, bool]:
    s = raw.strip()
    if not s or looks_like_icon_uri(s) or _is_managed_media_ref(s):
        return raw, False
    path = _resolve_existing_file(s, config_dir)
    if path is None:
        logger.warning("Font path not found, not copying: %s", raw)
        return raw, False
    suf = path.suffix.lower()
    if suf not in FONT_FILE_EXT:
        logger.warning("Unsupported font extension %s — not copying %s", suf, raw)
        return raw, False
    try:
        path.relative_to(config_dir.resolve())
    except ValueError:
        rel = _copy_to_library(path, config_dir, "fonts")
        return rel, True
    rel_self = path.relative_to(config_dir.resolve()).as_posix()
    if _is_managed_media_ref(rel_self):
        return rel_self.replace("\\", "/"), False
    rel = _copy_to_library(path, config_dir, "fonts")
    return rel, True


def _materialize_sound_value(raw: str, config_dir: Path) -> tuple[str, bool]:
    s = raw.strip()
    if not s or _is_managed_media_ref(s):
        return raw, False
    path = _resolve_existing_file(s, config_dir)
    if path is None:
        logger.warning("Sound path not found, not copying: %s", raw)
        return raw, False
    try:
        path.relative_to(config_dir.resolve())
    except ValueError:
        rel = _copy_to_library(path, config_dir, "sounds")
        return rel, True
    rel_self = path.relative_to(config_dir.resolve()).as_posix()
    if _is_managed_media_ref(rel_self):
        return rel_self.replace("\\", "/"), False
    rel = _copy_to_library(path, config_dir, "sounds")
    return rel, True


def _overlay_library_subdir(path: Path) -> str | None:
    suf = path.suffix.lower()
    if suf in _OVERLAY_VIDEO_EXT:
        return "videos"
    if suf in _OVERLAY_IMGLIKE_EXT:
        return "images"
    logger.warning("Unknown overlay media extension %s — not copying %s", suf, path)
    return None


def _materialize_overlay_media_value(raw: str, config_dir: Path) -> tuple[str, bool]:
    """Copy video/image files for ``overlay.show_media`` into ``library/videos`` or ``library/images``."""

    s = raw.strip()
    if not s or looks_like_icon_uri(s) or _is_managed_media_ref(s):
        return raw, False
    path = _resolve_existing_file(s, config_dir)
    if path is None:
        logger.warning("Overlay media path not found, not copying: %s", raw)
        return raw, False
    subdir = _overlay_library_subdir(path)
    if subdir is None:
        return raw, False
    cfg = config_dir.resolve()
    try:
        path.relative_to(cfg)
    except ValueError:
        rel = _copy_to_library(path, config_dir, subdir)
        return rel, True
    rel_self = path.relative_to(cfg).as_posix().replace("\\", "/")
    if rel_self.startswith(f"library/{subdir}/"):
        return rel_self, False
    rel = _copy_to_library(path, config_dir, subdir)
    return rel, True


def _process_action_dict(action: dict[str, Any], config_dir: Path) -> bool:
    changed = False
    typ = str(action.get("type") or "")

    if typ == "sound.play":
        for key in ("file", "path"):
            if key not in action or not action[key]:
                continue
            new_v, c = _materialize_sound_value(str(action[key]), config_dir)
            if c:
                action[key] = new_v
                changed = True
        return changed

    if typ == "overlay.play_sound":
        for key in ("file", "path"):
            if key not in action or not action[key]:
                continue
            new_v, c = _materialize_sound_value(str(action[key]), config_dir)
            if c:
                action[key] = new_v
                changed = True
        return changed

    if typ == "overlay.show_media":
        for key in ("file", "path"):
            if key not in action or not action[key]:
                continue
            new_v, c = _materialize_overlay_media_value(str(action[key]), config_dir)
            if c:
                action[key] = new_v
                changed = True
        return changed

    return False


_FILE_ACTION_TYPES = frozenset({"sound.play", "overlay.play_sound", "overlay.show_media"})


def _deep_process_file_actions(obj: Any, config_dir: Path) -> bool:
    """Catch file paths on actions nested outside the usual pages/global_buttons/bindings/knob_pages shape."""

    changed = False
    if isinstance(obj, dict):
        if obj.get("type") in _FILE_ACTION_TYPES:
            changed |= _process_action_dict(obj, config_dir)
        for v in obj.values():
            changed |= _deep_process_file_actions(v, config_dir)
    elif isinstance(obj, list):
        for item in obj:
            changed |= _deep_process_file_actions(item, config_dir)
    return changed


def _process_button_entry(entry: dict[str, Any], config_dir: Path) -> bool:
    changed = False
    for img_key in ("image", "icon"):
        if img_key not in entry or not entry[img_key]:
            continue
        new_v, c = _materialize_image_value(str(entry[img_key]), config_dir)
        if c:
            entry[img_key] = new_v
            changed = True
    if entry.get("font_file"):
        new_v, c = _materialize_font_value(str(entry["font_file"]), config_dir)
        if c:
            entry["font_file"] = new_v
            changed = True
    if "action" in entry and isinstance(entry["action"], dict):
        changed |= _process_action_dict(entry["action"], config_dir)
    acts = entry.get("actions")
    if isinstance(acts, list):
        for a in acts:
            if isinstance(a, dict):
                changed |= _process_action_dict(a, config_dir)
    return changed


def _process_binding(binding: dict[str, Any], config_dir: Path) -> bool:
    changed = False
    if "action" in binding and isinstance(binding["action"], dict):
        changed |= _process_action_dict(binding["action"], config_dir)
    acts = binding.get("actions")
    if isinstance(acts, list):
        for a in acts:
            if isinstance(a, dict):
                changed |= _process_action_dict(a, config_dir)
    return changed


def collect_referenced_library_rel_paths(raw: Any, config_dir: Path) -> set[str]:
    """All ``library/images|videos|sounds|fonts`` and ``assets`` files, plus derived key-video
    GIFs, referenced by ``raw``."""

    cfg = config_dir.resolve()
    keep: set[str] = set()

    def visit(s: str) -> None:
        t = s.strip()
        if not t or len(t) > 2048:
            return
        if looks_like_icon_uri(t):
            return
        if t.startswith(("http://", "https://", "file://")):
            return
        p = resolve_config_media_path(t, config_dir)
        if p is None or not p.is_file():
            return
        if is_video_path(p):
            with contextlib.suppress(OSError):
                keep.add(key_video_gif_cache_relpath(p))
        try:
            rel = p.relative_to(cfg).as_posix().replace("\\", "/")
        except ValueError:
            return
        for prefix in (
            "library/images/",
            "library/videos/",
            "library/sounds/",
            "library/fonts/",
            "assets/",
        ):
            if rel.startswith(prefix):
                keep.add(rel)
                return

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, str):
            visit(obj)

    walk(raw)
    return keep


def _prune_key_video_gif_cache(config_dir: Path, keep: set[str]) -> int:
    d = config_dir / "library" / "generated" / "key_video_gif"
    if not d.is_dir():
        return 0
    removed = 0
    for f in d.iterdir():
        if f.name.endswith((".part.gif", ".tmp.gif")):
            try:
                f.unlink()
                removed += 1
            except OSError:
                logger.debug("Could not remove temp cache file %s", f, exc_info=True)
            continue
        if not f.is_file() or f.suffix.lower() != ".gif":
            continue
        rel = f.relative_to(config_dir).as_posix().replace("\\", "/")
        if rel not in keep:
            try:
                f.unlink()
                removed += 1
                logger.info("Removed unreferenced key-video GIF cache %s", rel)
            except OSError:
                logger.exception("Could not remove %s", f)
    return removed


def prune_unused_library_media(raw: Any, config_dir: Path) -> int:
    """Delete media files under the config tree that are not referenced anywhere in ``raw``.

    Covers ``library/images``, ``library/videos``, ``library/sounds``, ``library/fonts``, ``assets``, and
    ``library/generated/key_video_gif``. Call after saving or loading normalized config.
    """

    config_dir = config_dir.resolve()
    keep = collect_referenced_library_rel_paths(raw, config_dir)
    removed = _prune_key_video_gif_cache(config_dir, keep)
    for sub in ("library/images", "library/videos", "library/sounds", "library/fonts", "assets"):
        d = config_dir / sub
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            rel = f.relative_to(config_dir).as_posix().replace("\\", "/")
            if rel not in keep:
                try:
                    f.unlink()
                    removed += 1
                    logger.info("Removed unreferenced library file %s", rel)
                except OSError:
                    logger.exception("Could not remove %s", f)
    return removed


def materialize_external_media(raw: dict[str, Any], config_dir: Path) -> tuple[dict[str, Any], bool]:
    """
    Deep-copy ``raw`` and copy any external (or non-library) image/sound files into
    ``library/images`` and ``library/sounds`` under ``config_dir``. Update paths to
    relative POSIX paths under the config directory.

    Returns ``(new_raw, any_change)``.
    """

    out = deepcopy(raw)
    config_dir = config_dir.resolve()
    changed = False

    gb = out.get("global_buttons")
    if isinstance(gb, dict):
        for entry in gb.values():
            if isinstance(entry, dict):
                changed |= _process_button_entry(entry, config_dir)

    pages = out.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            buttons = page.get("buttons")
            if not isinstance(buttons, dict):
                continue
            for entry in buttons.values():
                if isinstance(entry, dict):
                    changed |= _process_button_entry(entry, config_dir)

    bindings = out.get("bindings")
    if isinstance(bindings, list):
        for b in bindings:
            if isinstance(b, dict):
                changed |= _process_binding(b, config_dir)

    def _visit_knob_act(act: dict[str, Any]) -> None:
        nonlocal changed
        changed |= _process_action_dict(act, config_dir)

    kp = out.get("knob_pages")
    if isinstance(kp, dict):
        walk_knob_pages_for_media(kp, _visit_knob_act)

    changed |= _deep_process_file_actions(out, config_dir)

    try:
        n_pruned = prune_unused_library_media(out, config_dir)
        if n_pruned:
            logger.info("Library cleanup removed %s unreferenced file(s)", n_pruned)
    except Exception:
        logger.exception("prune_unused_library_media failed")

    return out, changed
