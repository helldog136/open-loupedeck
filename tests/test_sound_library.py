"""Sound library: safe paths, listing, rename, delete and the /api/sounds endpoints."""

from __future__ import annotations

import asyncio
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_loupedeck import sound_library as lib
from open_loupedeck import sound_player as sp
from open_loupedeck.config_state import ConfigState
from open_loupedeck.web_app import create_web_app


def _wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * seconds))


@pytest.fixture()
def env(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    null = sp.NullBackend()
    sp.set_player(sp.SoundPlayer(null))
    client = TestClient(create_web_app(cfg, ConfigState(cfg), asyncio.Lock()))
    d = tmp_path / "library" / "sounds"
    d.mkdir(parents=True, exist_ok=True)
    yield client, d, null, tmp_path
    sp.set_player(None)


@pytest.mark.parametrize(
    "bad",
    [
        "../config.yaml",
        "..\\x.wav",
        "library/sounds/../../config.yaml",
        "/etc/passwd.wav",
        "C:/x.wav",
        "a/b.wav",
        "",
        ".",
        "..",
        ".hidden.wav",
        "x.exe",
    ],
)
def test_resolve_rejects_unsafe(tmp_path: Path, bad: str) -> None:
    (tmp_path / "library" / "sounds").mkdir(parents=True)
    with pytest.raises(lib.SoundPathError):
        lib.resolve_library_file(tmp_path, bad, must_exist=False)


def test_resolve_accepts_plain_and_prefixed(tmp_path: Path) -> None:
    d = tmp_path / "library" / "sounds"
    d.mkdir(parents=True)
    (d / "a.wav").write_bytes(b"x")
    assert lib.resolve_library_file(tmp_path, "a.wav") == d.resolve() / "a.wav"
    assert lib.resolve_library_file(tmp_path, "library/sounds/a.wav") == d.resolve() / "a.wav"
    with pytest.raises(FileNotFoundError):
        lib.resolve_library_file(tmp_path, "nope.wav")


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    d = tmp_path / "library" / "sounds"
    d.mkdir(parents=True)
    outside = tmp_path / "secret.wav"
    outside.write_bytes(b"x")
    try:
        (d / "link.wav").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(lib.SoundPathError):
        lib.resolve_library_file(tmp_path, "link.wav")


def test_list_sounds_duration(env) -> None:
    client, d, _, _ = env
    _wav(d / "beep.wav", 0.5)
    (d / "notes.txt").write_text("x")
    (d / "clip.ogg").write_bytes(b"OggS")
    # CBR 128 kbps mp3 frame header, 16000 bytes -> 1.0 s
    (d / "tune.mp3").write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 15996)
    body = client.get("/api/sounds").json()
    by = {s["name"]: s for s in body["sounds"]}
    assert set(by) == {"beep.wav", "clip.ogg", "tune.mp3"}
    assert by["beep.wav"]["duration"] == 0.5 and by["beep.wav"]["file"] == "library/sounds/beep.wav"
    assert by["tune.mp3"]["duration"] == 1.0
    assert by["clip.ogg"]["duration"] is None and by["clip.ogg"]["size"] == 4


def test_preview_and_stop(env) -> None:
    client, d, null, _ = env
    _wav(d / "beep.wav")
    r = client.post("/api/sounds/preview", json={"file": "library/sounds/beep.wav", "volume": 20})
    assert r.status_code == 200 and null.started[-1].volume == 20
    client.post("/api/sounds/preview", json={"file": "beep.wav"})
    assert [p.running for p in null.started] == [False, True]  # preview restarts
    assert client.post("/api/sounds/stop").json()["stopped"] == 1
    assert not null.started[-1].running


def test_endpoints_reject_traversal(env) -> None:
    client, d, null, root = env
    (root / "config.yaml").write_text("x")
    for bad in ("../../config.yaml", "..%2Fconfig.yaml", "library/sounds/../../config.yaml", "/etc/hosts"):
        assert client.post("/api/sounds/preview", json={"file": bad}).status_code in (400, 404)
        assert client.post("/api/sounds/delete", json={"file": bad}).status_code in (400, 404)
        assert client.post("/api/sounds/rename", json={"file": bad, "name": "x"}).status_code in (400, 404)
    _wav(d / "a.wav")
    # rename target can never leave the library, whatever the new name contains
    r = client.post("/api/sounds/rename", json={"file": "a.wav", "name": "../../evil"})
    assert r.status_code == 200
    assert r.json()["file"].startswith("library/sounds/") and "/" not in r.json()["file"][len("library/sounds/") :]
    assert (root / "config.yaml").exists() and not null.started


def test_rename_and_delete(env) -> None:
    client, d, _, _ = env
    _wav(d / "a.wav")
    _wav(d / "b.wav")
    r = client.post("/api/sounds/rename", json={"file": "library/sounds/a.wav", "name": "Air horn"})
    assert r.json()["file"] == "library/sounds/Air horn.wav" and (d / "Air horn.wav").exists()
    assert client.post("/api/sounds/rename", json={"file": "b.wav", "name": "Air horn"}).status_code == 409
    assert client.post("/api/sounds/rename", json={"file": "b.wav", "name": "  "}).status_code == 400
    assert client.post("/api/sounds/delete", json={"file": "b.wav"}).status_code == 200
    assert not (d / "b.wav").exists()
    assert client.post("/api/sounds/delete", json={"file": "b.wav"}).status_code == 404


def test_library_sounds_survive_config_cleanup(env) -> None:
    from open_loupedeck.media_library import prune_unused_library_media

    _, d, _, root = env
    _wav(d / "kept.wav")
    prune_unused_library_media({"pages": []}, root)
    assert (d / "kept.wav").exists()
