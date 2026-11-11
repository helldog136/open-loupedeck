"""``wow:<name>`` icons: spec parsing, on-disk cache, negative cache, pruning, rendering and the clear endpoint.

No test touches the network: ``wow_icons.client_factory`` is replaced by a fake HTTP client.
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from open_loupedeck import icon_loader, media_library, wow_icons
from open_loupedeck.config_state import ConfigState
from open_loupedeck.web_app import create_web_app


def _jpeg(color: tuple[int, int, int] = (200, 30, 30), size: tuple[int, int] = (56, 56)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


class FakeClient:
    """Stands in for httpx.Client: records URLs and answers from a ``{name: status|bytes|Exception}`` table."""

    def __init__(self, table: dict[str, object], calls: list[str]) -> None:
        self.table, self.calls = table, calls

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str) -> httpx.Response:
        self.calls.append(url)
        name = url.rsplit("/", 1)[-1].removesuffix(".jpg")
        answer = self.table.get(name, 404)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, bytes):
            return httpx.Response(200, content=answer)
        return httpx.Response(int(answer), content=b"not found")  # type: ignore[arg-type]


@pytest.fixture()
def net(monkeypatch: pytest.MonkeyPatch):
    """Fake network + controllable clock; failures from earlier tests are forgotten."""

    calls: list[str] = []
    table: dict[str, object] = {}
    now = [1000.0]
    monkeypatch.setattr(wow_icons, "client_factory", lambda: FakeClient(table, calls))
    monkeypatch.setattr(wow_icons, "clock", lambda: now[0])
    wow_icons._failed.clear()

    class Net:
        pass

    n = Net()
    n.calls, n.table, n.now = calls, table, now  # type: ignore[attr-defined]
    yield n
    wow_icons._failed.clear()


# --- spec parsing -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("wow:inv_misc_rune_01", "wow:inv_misc_rune_01"),
        ("WOW:Inv_Misc_Rune_01", "wow:inv_misc_rune_01"),
        ("  wow:ability_warrior_charge ", "wow:ability_warrior_charge"),
        ("wow:a", "wow:a"),
    ],
)
def test_valid_wow_spec(raw: str, key: str) -> None:
    parsed = icon_loader.icon_url_from_spec(raw)
    assert parsed == (key, f"https://wow.zamimg.com/images/wow/icons/large/{key[4:]}.jpg")
    assert icon_loader.looks_like_icon_uri(raw)
    assert not icon_loader.icon_is_tintable(raw)  # coloured raster: never recoloured with the key's text colour


@pytest.mark.parametrize(
    "raw",
    ["wow:", "wow: ", "wow:a b", "wow:a-b", "wow:../etc/passwd", "wow:a/b", "wow:a.jpg", "wow:é", "wow:" + "a" * 200],
)
def test_invalid_wow_spec(raw: str) -> None:
    assert icon_loader.icon_url_from_spec(raw) is None
    assert wow_icons.normalize_name(raw[4:]) is None


def test_existing_prefixes_unchanged() -> None:
    assert icon_loader.icon_url_from_spec("lucide:bell") == (
        "lucide:bell",
        f"https://cdn.jsdelivr.net/npm/lucide-static@{icon_loader._LUCIDE_VER}/icons/bell.svg",
    )
    assert icon_loader.icon_url_from_spec("si:twitch")[0] == "si:twitch:ffffff"
    assert icon_loader.icon_url_from_spec("library/images/x.png") is None


def test_media_library_leaves_wow_uris_alone(tmp_path: Path) -> None:
    raw, changed = media_library._materialize_image_value("wow:inv_misc_rune_01", tmp_path)
    assert (raw, changed) == ("wow:inv_misc_rune_01", False)


# --- cache --------------------------------------------------------------------------------------


def test_download_once_then_cache_hit_even_offline(tmp_path: Path, net) -> None:
    net.table["inv_misc_rune_01"] = _jpeg()
    first = wow_icons.get_icon_bytes("inv_misc_rune_01", tmp_path)
    assert first and first[:2] == b"\xff\xd8"
    assert (tmp_path / "wow" / "inv_misc_rune_01.jpg").is_file()
    assert net.calls == ["https://wow.zamimg.com/images/wow/icons/large/inv_misc_rune_01.jpg"]

    # Offline from now on, and a long time later: still served from disk, never re-downloaded.
    net.table["inv_misc_rune_01"] = httpx.ConnectError("offline")
    net.now[0] += 10 * 365 * 24 * 3600
    assert wow_icons.get_icon_bytes("inv_misc_rune_01", tmp_path) == first
    assert len(net.calls) == 1


def test_404_is_negatively_cached_for_an_hour(tmp_path: Path, net) -> None:
    assert wow_icons.get_icon_bytes("nope_icon", tmp_path) is None
    assert wow_icons.get_icon_bytes("nope_icon", tmp_path) is None
    assert len(net.calls) == 1
    assert not (tmp_path / "wow" / "nope_icon.jpg").exists()

    net.now[0] += wow_icons.NEGATIVE_TTL_S - 1
    assert wow_icons.get_icon_bytes("nope_icon", tmp_path) is None
    assert len(net.calls) == 1

    net.now[0] += 2  # TTL elapsed -> one new attempt, which can now succeed
    net.table["nope_icon"] = _jpeg()
    assert wow_icons.get_icon_bytes("nope_icon", tmp_path) is not None
    assert len(net.calls) == 2


def test_network_error_and_non_image_are_negatively_cached(tmp_path: Path, net) -> None:
    net.table["offline_one"] = httpx.ConnectError("offline")
    net.table["html_one"] = b"<html>not an image</html>"
    assert wow_icons.get_icon_bytes("offline_one", tmp_path) is None
    assert wow_icons.get_icon_bytes("html_one", tmp_path) is None
    assert wow_icons.get_icon_bytes("offline_one", tmp_path) is None
    assert wow_icons.get_icon_bytes("html_one", tmp_path) is None
    assert len(net.calls) == 2
    assert not (tmp_path / "wow").exists() or not list((tmp_path / "wow").glob("*"))


def test_invalid_name_never_hits_the_network(tmp_path: Path, net) -> None:
    assert wow_icons.get_icon_bytes("../evil", tmp_path) is None
    assert wow_icons.get_icon_bytes("Has_Caps", tmp_path) is None  # callers normalise first
    assert net.calls == []


def test_concurrent_requests_for_one_icon_download_once(tmp_path: Path, net) -> None:
    net.table["same_icon"] = _jpeg()
    results: list[bytes | None] = []
    threads = [
        threading.Thread(target=lambda: results.append(wow_icons.get_icon_bytes("same_icon", tmp_path)))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8 and all(results)
    assert len(net.calls) == 1


def test_downloads_are_bounded_to_four_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active = [0]
    peak = [0]
    lock = threading.Lock()
    data = _jpeg()

    class Slow:
        def __enter__(self) -> Slow:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def get(self, url: str) -> httpx.Response:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return httpx.Response(200, content=data)

    monkeypatch.setattr(wow_icons, "client_factory", lambda: Slow())
    threads = [threading.Thread(target=wow_icons.get_icon_bytes, args=(f"icon_{i}", tmp_path)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wow_icons.MAX_CONCURRENT == 4
    assert 1 < peak[0] <= 4


def test_default_client_is_polite() -> None:
    client = wow_icons._default_client()
    try:
        assert client.headers["user-agent"] == "open-loupedeck"
        assert client.timeout.read is not None and client.timeout.connect is not None
    finally:
        client.close()


def test_prune_removes_oldest_above_limit(tmp_path: Path) -> None:
    folder = tmp_path / "wow"
    folder.mkdir()
    for i in range(12):
        p = folder / f"icon_{i:02d}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    assert wow_icons.prune(tmp_path, above=12, keep=8) == 0  # not above the limit
    (folder / "icon_99.jpg").write_bytes(b"x")
    os.utime(folder / "icon_99.jpg", (5000, 5000))
    assert wow_icons.prune(tmp_path, above=12, keep=8) == 5
    left = sorted(p.name for p in folder.glob("*.jpg"))
    assert len(left) == 8
    assert "icon_00.jpg" not in left and "icon_04.jpg" not in left  # the oldest are gone
    assert "icon_99.jpg" in left and "icon_11.jpg" in left


def test_download_triggers_prune(tmp_path: Path, net, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wow_icons, "PRUNE_ABOVE", 3)
    monkeypatch.setattr(wow_icons, "PRUNE_TO", 2)
    # prune() takes its defaults at definition time, so wrap it with the patched limits
    real = wow_icons.prune
    monkeypatch.setattr(wow_icons, "prune", lambda d: real(d, above=3, keep=2))
    for i in range(6):
        net.table[f"icon_{i}"] = _jpeg()
        wow_icons.get_icon_bytes(f"icon_{i}", tmp_path)
        os.utime(tmp_path / "wow" / f"icon_{i}.jpg", (100 + i, 100 + i))
    assert len(list((tmp_path / "wow").glob("*.jpg"))) <= 3


def test_cache_hit_refreshes_age(tmp_path: Path, net) -> None:
    net.table["kept"] = _jpeg()
    wow_icons.get_icon_bytes("kept", tmp_path)
    p = tmp_path / "wow" / "kept.jpg"
    os.utime(p, (1000, 1000))
    wow_icons.get_icon_bytes("kept", tmp_path)
    assert p.stat().st_mtime > 1_000_000


def test_clear_cache_removes_files_and_forgets_failures(tmp_path: Path, net) -> None:
    net.table["good"] = _jpeg()
    wow_icons.get_icon_bytes("good", tmp_path)
    wow_icons.get_icon_bytes("bad", tmp_path)  # 404 -> remembered
    assert wow_icons.cache_stats(tmp_path)["files"] == 1
    assert wow_icons.clear_cache(tmp_path) == 1
    assert wow_icons.cache_stats(tmp_path) == {"files": 0, "bytes": 0}
    net.table["bad"] = _jpeg()
    assert wow_icons.get_icon_bytes("bad", tmp_path) is not None  # retried at once after the clear


# --- rendering ----------------------------------------------------------------------------------


def test_load_icon_image_renders_wow_icon_in_requested_size(tmp_path: Path, net) -> None:
    net.table["inv_misc_rune_01"] = _jpeg((10, 200, 10))
    img = icon_loader.load_icon_image("wow:inv_misc_rune_01", tmp_path, (90, 60))
    assert img is not None and img.size == (90, 60) and img.mode == "RGBA"
    assert img.getpixel((45, 30))[:3] != (0, 0, 0)  # the icon is in the middle
    assert img.getpixel((2, 30))[3] == 0  # aspect kept: transparent bands on the sides of a wide canvas


def test_load_icon_image_missing_icon_is_none(tmp_path: Path, net) -> None:
    assert icon_loader.load_icon_image("wow:does_not_exist", tmp_path, (64, 64)) is None


def test_key_renders_with_wow_icon(tmp_path: Path, net) -> None:
    from open_loupedeck.button_render import render_key_preview

    net.table["inv_misc_rune_01"] = _jpeg((10, 200, 10))
    entry = {"text": "Hearth", "icon": "wow:inv_misc_rune_01", "mode": "both", "background": "#000000"}
    import open_loupedeck.button_render as br

    original = br.default_icon_cache_dir
    br.default_icon_cache_dir = lambda: tmp_path  # type: ignore[assignment]
    try:
        img, _ = render_key_preview(entry, tmp_path, size=(90, 90), mode="both", offline=False)
    finally:
        br.default_icon_cache_dir = original  # type: ignore[assignment]
    assert img is not None
    colors = img.convert("RGB").getcolors(maxcolors=1_000_000) or []
    greens = sum(n for n, (r, g, _b) in colors if g > 150 and r < 80)
    assert greens > 100  # the (green) icon is drawn


# --- endpoint -----------------------------------------------------------------------------------


def test_clear_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "icons"
    (cache / "wow").mkdir(parents=True)
    (cache / "wow" / "a.jpg").write_bytes(b"x")
    (cache / "wow" / "b.jpg").write_bytes(b"x")
    (cache / "keep.png").write_bytes(b"x")
    monkeypatch.setattr("open_loupedeck.web_app.default_icon_cache_dir", lambda: cache)
    cfg = tmp_path / "config.yaml"
    client = TestClient(create_web_app(cfg, ConfigState(cfg), asyncio.Lock()))
    r = client.post("/api/wow_icons/clear")
    assert r.status_code == 200 and r.json() == {"ok": True, "removed": 2}
    assert (cache / "keep.png").exists() and not list((cache / "wow").glob("*.jpg"))
