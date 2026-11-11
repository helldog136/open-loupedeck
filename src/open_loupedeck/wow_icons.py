"""World of Warcraft icons (``wow:<icon_name>``): on-demand download from Wowhead's CDN, cached on disk.

The icons are Blizzard assets: nothing is bundled with the app. The name is the file name in a Wowhead
icon URL (``https://wow.zamimg.com/images/wow/icons/large/<name>.jpg`` -> ``wow:<name>``).

Cache rules (kept deliberately gentle with the CDN):

* A downloaded icon lives in ``<icon cache dir>/wow/<name>.jpg`` and is **never** re-downloaded (no expiry);
  once cached it works offline.
* A failed download (404, network error, not an image) is remembered for :data:`NEGATIVE_TTL_S` (1 h, in
  memory) so a wrong name or an offline PC does not hit the server again at every render.
* At most :data:`MAX_CONCURRENT` downloads at the same time, with timeouts and a generic User-Agent.
* Above :data:`PRUNE_ABOVE` files the oldest ones (by modification time; a cache hit refreshes it) are
  deleted down to :data:`PRUNE_TO`.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

WOW_NAME_RE = re.compile(r"^[a-z0-9_]+$")
MAX_NAME_LEN = 96
ICON_URL = "https://wow.zamimg.com/images/wow/icons/large/{name}.jpg"
USER_AGENT = "open-loupedeck"
MAX_CONCURRENT = 4
NEGATIVE_TTL_S = 3600.0
PRUNE_ABOVE = 5000
PRUNE_TO = 4500
MAX_BYTES = 1_000_000
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_state_lock = threading.Lock()
_name_locks: dict[str, threading.Lock] = {}
_failed: dict[str, float] = {}  # name -> monotonic time of the failure

# Tests replace these two.
HttpClientFactory = Callable[[], Any]


def _default_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})


client_factory: HttpClientFactory = _default_client
clock: Callable[[], float] = time.monotonic


def normalize_name(raw: str) -> str | None:
    """Icon name from the part after ``wow:`` (lower-cased, trimmed), or ``None`` if it is not a valid name."""

    name = str(raw or "").strip().lower()
    if not name or len(name) > MAX_NAME_LEN or not WOW_NAME_RE.match(name):
        return None
    return name


def icon_url(name: str) -> str:
    return ICON_URL.format(name=name)


def wow_dir(cache_dir: Path) -> Path:
    return Path(cache_dir) / "wow"


def cached_path(cache_dir: Path, name: str) -> Path:
    return wow_dir(cache_dir) / f"{name}.jpg"


def _name_lock(name: str) -> threading.Lock:
    with _state_lock:
        return _name_locks.setdefault(name, threading.Lock())


def _recently_failed(name: str) -> bool:
    with _state_lock:
        t = _failed.get(name)
        if t is None:
            return False
        if clock() - t < NEGATIVE_TTL_S:
            return True
        del _failed[name]
        return False


def _mark_failed(name: str) -> None:
    with _state_lock:
        _failed[name] = clock()


def _read_cached(path: Path) -> bytes | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    with contextlib.suppress(OSError):
        os.utime(path, None)  # LRU-ish: icons in use survive pruning
    return data


def _is_image(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:
        return False


def prune(cache_dir: Path, above: int = PRUNE_ABOVE, keep: int = PRUNE_TO) -> int:
    """Delete the oldest cached icons when there are more than ``above``; return how many were removed."""

    folder = wow_dir(cache_dir)
    try:
        files = [(p.stat().st_mtime, p) for p in folder.glob("*.jpg")]
    except OSError:
        return 0
    if len(files) <= above:
        return 0
    files.sort(key=lambda x: x[0])
    removed = 0
    for _, p in files[: len(files) - keep]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    logger.info("Pruned %d cached WoW icons", removed)
    return removed


def _download(name: str) -> bytes | None:
    url = icon_url(name)
    with _slots:
        try:
            with client_factory() as client:
                r = client.get(url)
        except Exception as exc:
            logger.warning("WoW icon download failed (%s): %s", name, exc)
            return None
    if r.status_code != 200:
        logger.info("WoW icon %s not available (HTTP %s)", name, r.status_code)
        return None
    data = r.content
    if not data or len(data) > MAX_BYTES or not _is_image(data):
        logger.info("WoW icon %s: unexpected response", name)
        return None
    return data


def get_icon_bytes(name: str, cache_dir: Path) -> bytes | None:
    """JPEG bytes of the icon: from the disk cache, else downloaded once. ``None`` when unavailable."""

    if normalize_name(name) != name:
        return None
    path = cached_path(cache_dir, name)
    data = _read_cached(path)
    if data is not None:
        return data
    if _recently_failed(name):
        return None
    with _name_lock(name):
        data = _read_cached(path)  # another thread may have just fetched it
        if data is not None:
            return data
        if _recently_failed(name):
            return None
        data = _download(name)
        if data is None:
            _mark_failed(name)
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError:
            logger.debug("Could not write WoW icon cache %s", path, exc_info=True)
        else:
            prune(cache_dir)
        return data


def load_wow_image(name: str, cache_dir: Path, size: tuple[int, int]) -> Image.Image | None:
    """Icon fitted (aspect kept, centered) into a transparent ``size`` RGBA canvas, or ``None``."""

    data = get_icon_bytes(name, cache_dir)
    if data is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            src = im.convert("RGBA")
    except Exception:
        logger.warning("Cached WoW icon %s is unreadable; removing it", name)
        with contextlib.suppress(OSError):
            cached_path(cache_dir, name).unlink()
        return None
    w, h = size
    scale = min(w / src.width, h / src.height)
    new = (max(1, round(src.width * scale)), max(1, round(src.height * scale)))
    fitted = src.resize(new, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(fitted, ((w - new[0]) // 2, (h - new[1]) // 2))
    return canvas


def cache_stats(cache_dir: Path) -> dict[str, int]:
    files = list(wow_dir(cache_dir).glob("*.jpg"))
    total = 0
    for p in files:
        with contextlib.suppress(OSError):
            total += p.stat().st_size
    return {"files": len(files), "bytes": total}


def clear_cache(cache_dir: Path) -> int:
    """Delete every cached WoW icon and forget failures; return how many files were removed."""

    removed = 0
    folder = wow_dir(cache_dir)
    for p in list(folder.glob("*")):
        if p.is_file():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    with _state_lock:
        _failed.clear()
    return removed
