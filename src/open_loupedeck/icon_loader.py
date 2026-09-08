"""Fetch and rasterize SVG icons (Simple Icons, Heroicons, Lucide, MDI) for key graphics."""

from __future__ import annotations

import hashlib
import io
import logging
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

# Heroicons 2.x on jsDelivr (pinned minor for stable paths)
_HEROICONS_BASE = "https://cdn.jsdelivr.net/npm/heroicons@2.1.5"
_LUCIDE_VER = "0.446.0"
_MDI_VER = "7.4.47"

_SLUG_SAFE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _svg_to_rgba(svg_bytes: bytes, width: int, height: int) -> Image.Image:
    import resvg_py

    png = bytes(resvg_py.svg_to_bytes(svg_string=svg_bytes.decode("utf-8"), width=width, height=height))
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _cache_path(cache_dir: Path, key: str, w: int, h: int) -> Path:
    hsh = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return cache_dir / f"{hsh}_{w}x{h}.png"


def _parse_simpleicons(rest: str) -> tuple[str, str] | None:
    """Return (slug, hex_color) or None."""
    rest = rest.strip()
    if not rest:
        return None
    if "/" in rest:
        slug, color = rest.split("/", 1)
        slug, color = slug.strip(), color.strip().lstrip("#")
        if len(color) == 6 and all(c in "0123456789abcdefABCDEF" for c in color):
            return slug, color.lower()
        return None
    return rest, "ffffff"


def icon_url_from_spec(raw: str) -> tuple[str, str] | None:
    """
    If ``raw`` is a supported icon URI, return (cache_key, https URL).

    Prefixes:
    - ``si:`` / ``simpleicons:`` — cdn.simpleicons.org (slug or slug/RRGGBB)
    - ``heroicons:`` — path under heroicons npm, e.g. ``24/solid/heart``
    - ``lucide:`` — icon slug, e.g. ``bell``
    - ``mdi:`` — Material Design Icons slug, e.g. ``heart``
    - ``https://`` / ``http://`` — direct SVG URL
    """
    s = raw.strip()
    low = s.lower()

    if low.startswith("simpleicons:"):
        slug_color = _parse_simpleicons(s.split(":", 1)[1])
        if not slug_color:
            return None
        slug, color = slug_color
        if not _SLUG_SAFE.match(slug):
            logger.warning("Invalid Simple Icons slug: %r", slug)
            return None
        url = f"https://cdn.simpleicons.org/{quote(slug, safe='')}/{color}"
        return (f"si:{slug}:{color}", url)

    if low.startswith("si:"):
        slug_color = _parse_simpleicons(s[3:])
        if not slug_color:
            return None
        slug, color = slug_color
        if not _SLUG_SAFE.match(slug):
            logger.warning("Invalid Simple Icons slug: %r", slug)
            return None
        url = f"https://cdn.simpleicons.org/{quote(slug, safe='')}/{color}"
        return (f"si:{slug}:{color}", url)

    if low.startswith("heroicons:"):
        path = s.split(":", 1)[1].strip().lstrip("/")
        if not path:
            return None
        if not path.endswith(".svg"):
            path = path + ".svg"
        # prevent path traversal
        if ".." in path or path.startswith("/"):
            logger.warning("Invalid heroicons path: %r", path)
            return None
        url = f"{_HEROICONS_BASE}/{path}"
        return (f"heroicons:{path}", url)

    if low.startswith("lucide:"):
        slug = s.split(":", 1)[1].strip()
        if not slug or not _SLUG_SAFE.match(slug):
            logger.warning("Invalid lucide slug: %r", slug)
            return None
        url = f"https://cdn.jsdelivr.net/npm/lucide-static@{_LUCIDE_VER}/icons/{slug}.svg"
        return (f"lucide:{slug}", url)

    if low.startswith("mdi:"):
        slug = s.split(":", 1)[1].strip()
        if not slug or not _SLUG_SAFE.match(slug):
            logger.warning("Invalid mdi slug: %r", slug)
            return None
        url = f"https://cdn.jsdelivr.net/npm/@mdi/svg@{_MDI_VER}/svg/{slug}.svg"
        return (f"mdi:{slug}", url)

    if low.startswith(("https://", "http://")):
        if ".svg" not in low and "svg" not in low:
            # still try (server may return SVG)
            pass
        return (f"url:{s}", s)

    return None


def load_icon_image(
    raw: str,
    cache_dir: Path,
    size: tuple[int, int],
    timeout: float = 20.0,
) -> Image.Image | None:
    """
    Download SVG (or use cache), rasterize to ``size``, return RGBA image.
    """
    parsed = icon_url_from_spec(raw)
    if not parsed:
        return None
    cache_key, url = parsed
    w, h = size
    cache_dir.mkdir(parents=True, exist_ok=True)
    cpath = _cache_path(cache_dir, cache_key + "|" + url, w, h)
    if cpath.is_file():
        try:
            logger.debug("Icon cache hit %s", cpath.name)
            return Image.open(cpath).convert("RGBA")
        except Exception:
            logger.debug("Stale icon cache, refetching", exc_info=True)

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            body = r.content
            ct = (r.headers.get("content-type") or "").lower()
    except Exception:
        logger.exception("Icon HTTP fetch failed: %s", url)
        return None

    if "svg" not in ct and not body.strip().startswith(b"<"):
        logger.warning("Unexpected icon response (not SVG?) url=%s content-type=%s", url, ct)
    try:
        img = _svg_to_rgba(body, w, h)
    except Exception:
        logger.exception("SVG rasterize failed. url=%s", url)
        return None

    try:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        tmp = cpath.with_suffix(".tmp")
        img.save(tmp, format="PNG")
        tmp.replace(cpath)
    except Exception:
        logger.debug("Could not write icon cache %s", cpath, exc_info=True)

    logger.info("Loaded icon %s -> %sx%s", cache_key, w, h)
    return img


def looks_like_icon_uri(raw: str) -> bool:
    return icon_url_from_spec(raw) is not None
