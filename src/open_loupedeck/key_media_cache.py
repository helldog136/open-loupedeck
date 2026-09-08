"""Cache compact GIFs from video files for touch-key graphics (device-friendly, no video decode on each frame)."""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

from .icon_loader import looks_like_icon_uri

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".ogv"})


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def key_video_gif_cache_relpath(video_path: Path) -> str:
    """Config-relative POSIX path to the derived key GIF for this video (matches ``ensure_video_key_gif``)."""

    stat = video_path.stat()
    payload = f"v1|{video_path.resolve()}|{stat.st_mtime_ns}|90|8|2.5".encode()
    h = hashlib.sha256(payload).hexdigest()[:32]
    return f"library/generated/key_video_gif/{h}.gif"


def resolve_config_media_path(raw: str | None, config_dir: Path) -> Path | None:
    """Resolve a config-relative media path to an existing file.

    Supports older or hand-edited YAML: backslashes, and relative paths that omit the ``library/``
    prefix (e.g. ``videos/a.mp4`` → ``library/videos/a.mp4``). Only explicit absolute paths in YAML
    may resolve outside ``config_dir`` (legacy imports).
    """

    if not raw:
        return None
    cfg = config_dir.resolve()
    s = str(raw).strip().replace("\\", "/")
    if not s:
        return None
    low = s.lower()
    if low.startswith(("http://", "https://", "file://")):
        return None

    def _under_config(r: Path) -> bool:
        try:
            r.relative_to(cfg)
            return True
        except ValueError:
            return False

    expanded = Path(s).expanduser()
    if expanded.is_absolute():
        try:
            r = expanded.resolve()
        except OSError:
            return None
        return r if r.is_file() else None

    rel = str(expanded).lstrip("./")
    attempts: list[Path] = [cfg / Path(rel)]
    if not rel.startswith(("library/", "assets/")):
        attempts.extend(
            [
                cfg / "library" / Path(rel),
                cfg / "library/images" / Path(rel),
                cfg / "library/videos" / Path(rel),
                cfg / "library/sounds" / Path(rel),
                cfg / "library/fonts" / Path(rel),
                cfg / "assets" / Path(rel),
            ]
        )
    tried: set[str] = set()
    for cand in attempts:
        key = str(cand)
        if key in tried:
            continue
        tried.add(key)
        try:
            r = cand.resolve()
        except OSError:
            continue
        if not r.is_file() or not _under_config(r):
            continue
        return r
    return None


def animated_gif_frame_count(path: Path) -> int:
    """Return number of frames in a GIF (1 for non-GIF or on error)."""

    if path.suffix.lower() != ".gif":
        return 1
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(getattr(im, "n_frames", 1) or 1)
    except Exception:
        logger.debug("animated_gif_frame_count failed for %s", path, exc_info=True)
        return 1


def raw_graphic_needs_skin_animation(raw: str, config_dir: Path) -> bool:
    """True if this key graphic should be driven by the skin animation loop (video or multi-frame GIF)."""

    rs = str(raw).strip()
    if not rs or looks_like_icon_uri(rs):
        return False
    path = resolve_config_media_path(rs, config_dir)
    if path is None or not path.is_file():
        return False
    if is_video_path(path):
        return shutil.which("ffmpeg") is not None
    if path.suffix.lower() == ".gif":
        return animated_gif_frame_count(path) > 1
    return False


def ensure_video_key_gif(video_path: Path, config_dir: Path) -> Path | None:
    """Build or return a cached looping GIF (small, short) suitable for key bitmaps."""

    if not video_path.is_file():
        return None
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.debug(
            "ffmpeg not in PATH; cannot build key GIF from %s (caller logs user-facing hint)",
            video_path.name,
        )
        return None
    out = config_dir / key_video_gif_cache_relpath(video_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(".part.gif")
    vf = (
        "fps=8,scale=90:90:force_original_aspect_ratio=decrease,"
        "pad=90:90:(ow-iw)/2:(oh-ih)/2:black,"
        "split[s0][s1];[s0]palettegen=max_colors=64:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=3"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-t",
        "2.5",
        "-an",
        "-vf",
        vf,
        "-loop",
        "0",
        str(tmp),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=120)
    except Exception:
        logger.exception("ffmpeg could not build key GIF from %s", video_path)
        tmp.unlink(missing_ok=True)
        return None
    try:
        tmp.replace(out)
    except OSError:
        logger.exception("Could not finalize key GIF %s", out)
        tmp.unlink(missing_ok=True)
        return None
    return out


def resolve_graphic_load_path(raw_img: str, config_dir: Path) -> Path | None:
    """Path to open in PIL: videos become a cached GIF; other files unchanged."""

    rs = str(raw_img).strip()
    path = resolve_config_media_path(rs, config_dir)
    if path is None:
        return None
    if is_video_path(path):
        gif = ensure_video_key_gif(path, config_dir)
        return gif
    return path
