"""The sound library (``library/sounds`` in the config directory): listing, safe path handling, rename, delete.

Every name coming from the web UI goes through :func:`resolve_library_file`, which only accepts a plain file
name (optionally prefixed with ``library/sounds/``) that stays inside the library directory.
"""

from __future__ import annotations

import re
import struct
import wave
from pathlib import Path
from typing import Any

SOUND_EXTENSIONS = frozenset({".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aac", ".wma"})
LIBRARY_REL = "library/sounds"
_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._ -]+")


class SoundPathError(ValueError):
    """The requested file name is not a plain file inside the sound library."""


def library_dir(config_dir: Path) -> Path:
    return Path(config_dir).resolve() / "library" / "sounds"


def resolve_library_file(config_dir: Path, name: Any, *, must_exist: bool = True) -> Path:
    """Absolute path of a library sound; raises :class:`SoundPathError` for anything outside the library."""

    raw = str(name or "").strip().replace("\\", "/")
    if raw.startswith(LIBRARY_REL + "/"):
        raw = raw[len(LIBRARY_REL) + 1 :]
    if not raw or "/" in raw or raw in (".", "..") or "\x00" in raw or ":" in raw or raw.startswith("."):
        raise SoundPathError("invalid sound path")
    lib = library_dir(config_dir)
    p = (lib / raw).resolve()
    if p.parent != lib:
        raise SoundPathError("invalid sound path")
    if p.suffix.lower() not in SOUND_EXTENSIONS:
        raise SoundPathError("not an audio file")
    if must_exist and not p.is_file():
        raise FileNotFoundError(raw)
    return p


_MP3_BITRATES_V1_L3 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_MP3_BITRATES_V2_L3 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)


def _mp3_duration(path: Path, size: int) -> float | None:
    """Approximate MP3 duration from the first frame header (exact for CBR files)."""

    with path.open("rb") as f:
        head = f.read(10)
        skip = 0
        if head[:3] == b"ID3" and len(head) == 10:
            skip = 10 + ((head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14 | (head[8] & 0x7F) << 7 | (head[9] & 0x7F))
        f.seek(skip)
        buf = f.read(65536)
    for i in range(max(0, len(buf) - 4)):
        if buf[i] != 0xFF or (buf[i + 1] & 0xE0) != 0xE0:
            continue
        b1, b2 = buf[i + 1], buf[i + 2]
        version, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
        if version == 1 or layer != 1:  # reserved version / not layer III
            continue
        table = _MP3_BITRATES_V1_L3 if version == 3 else _MP3_BITRATES_V2_L3
        kbps = table[(b2 >> 4) & 0xF]
        if not kbps:
            continue
        return max(0.0, (size - skip - i) * 8 / (kbps * 1000))
    return None


def audio_duration(path: Path) -> float | None:
    """Seconds, when cheaply readable (wav exactly, mp3 estimated); ``None`` otherwise."""

    try:
        ext = path.suffix.lower()
        if ext == ".wav":
            with wave.open(str(path), "rb") as w:
                rate = w.getframerate()
                return w.getnframes() / rate if rate else None
        if ext == ".mp3":
            return _mp3_duration(path, path.stat().st_size)
    except (OSError, EOFError, wave.Error, struct.error):
        return None
    return None


def list_sounds(config_dir: Path) -> list[dict[str, Any]]:
    lib = library_dir(config_dir)
    out: list[dict[str, Any]] = []
    if not lib.is_dir():
        return out
    for p in sorted(lib.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.suffix.lower() not in SOUND_EXTENSIONS or p.name.startswith("."):
            continue
        dur = audio_duration(p)
        out.append(
            {
                "file": f"{LIBRARY_REL}/{p.name}",
                "name": p.name,
                "size": p.stat().st_size,
                "duration": round(dur, 2) if dur is not None else None,
                "ext": p.suffix.lower(),
            }
        )
    return out


def rename_sound(config_dir: Path, name: Any, new_stem: Any) -> Path:
    """Rename keeping the extension; ``new_stem`` is sanitised and made unique."""

    src = resolve_library_file(config_dir, name)
    stem = _SAFE_STEM.sub("_", Path(str(new_stem or "")).stem if "." in str(new_stem or "") else str(new_stem or ""))
    stem = stem.strip(" ._-")
    if not stem:
        raise SoundPathError("empty name")
    dest = resolve_library_file(config_dir, stem + src.suffix.lower(), must_exist=False)
    if dest.exists() and dest != src:
        raise FileExistsError(dest.name)
    src.rename(dest)
    return dest


def delete_sound(config_dir: Path, name: Any) -> None:
    resolve_library_file(config_dir, name).unlink()
