"""Rotating file backups next to the main YAML config."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

BACKUP_SUBDIR = "open-loupedeck-backups"


def backup_dir_for(config_path: Path) -> Path:
    return config_path.parent.resolve() / BACKUP_SUBDIR


def backup_slots(config_path: Path, max_keep: int) -> list[Path]:
    base = config_path.name
    d = backup_dir_for(config_path)
    return [d / f"{base}.bak{i}" for i in range(1, max_keep + 1)]


def create_rotating_backup(config_path: Path, max_keep: int = 3) -> dict[str, Any]:
    """
    Copy the current config file into ``.bak1`` (newest). Previous ``.bak1`` becomes ``.bak2``,
    etc.; the oldest slot is dropped. Does not modify the main config file.
    """

    path = config_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    d = backup_dir_for(path)
    d.mkdir(parents=True, exist_ok=True)
    slots = backup_slots(path, max_keep)
    oldest = slots[max_keep - 1]
    if oldest.is_file():
        oldest.unlink()
    for i in range(max_keep - 1, 0, -1):
        src = slots[i - 1]
        dst = slots[i]
        if src.is_file():
            src.rename(dst)
    data = path.read_bytes()
    slots[0].write_bytes(data)
    files = [{"name": p.name, "path": str(p)} for p in slots if p.is_file()]
    return {"ok": True, "written": str(slots[0]), "files": files}


def list_backups(config_path: Path, max_keep: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in backup_slots(config_path.resolve(), max_keep):
        if not p.is_file():
            continue
        st = p.stat()
        out.append(
            {
                "name": p.name,
                "path": str(p),
                "bytes": st.st_size,
                "mtime": st.st_mtime,
            }
        )
    return out


def restore_backup(config_path: Path, name: str, max_keep: int = 3) -> dict[str, Any]:
    """Overwrite the main config with the contents of backup slot ``name`` (e.g. ``config.yaml.bak1``).

    ``name`` must exactly match one of the real backup slot filenames (never taken as a raw path)
    so this can't be used to read/write anything outside the backup directory. Writes atomically
    (temp file + ``os.replace``), same guarantee as ``config_io.save_raw_config``.
    """

    path = config_path.resolve()
    slots = {p.name: p for p in backup_slots(path, max_keep)}
    src = slots.get(name)
    if src is None or not src.is_file():
        raise FileNotFoundError(f"No such backup: {name!r}")
    data = src.read_bytes()
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"ok": True, "restored_from": name}


def wipe_backups(config_path: Path, max_keep: int = 3) -> dict[str, Any]:
    """Delete all rotating backup slot files (``.bak1`` …). Does not read or modify the main config file."""

    path = config_path.resolve()
    removed: list[str] = []
    for p in backup_slots(path, max_keep):
        if p.is_file():
            p.unlink()
            removed.append(str(p))
    return {"ok": True, "removed": removed, "count": len(removed)}
