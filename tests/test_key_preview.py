"""Server-rendered key preview: modes, offline look, overflow measurement, cache, compatibility."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from open_loupedeck import web_app
from open_loupedeck.button_render import (
    PreviewCache,
    measure_label,
    offline_look,
    preview_cache_key,
    render_key_preview,
)
from open_loupedeck.config_state import ConfigState
from open_loupedeck.live_message import offline_fallback_mode, offline_fallback_text
from open_loupedeck.web_app import create_web_app


@pytest.fixture()
def icon_path(tmp_path: Path) -> str:
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((4, 4, 60, 60), fill=(255, 200, 0, 255))
    p = tmp_path / "ic.png"
    im.save(p)
    return str(p)


@pytest.fixture()
def client(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    state = ConfigState(cfg)
    app = create_web_app(cfg, state, asyncio.Lock())
    return TestClient(app)


def _png(resp) -> Image.Image:
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


def _post(client: TestClient, entry: dict, **extra):
    return client.post("/api/preview_key", json={"entry": entry, "control_id": "touch_0", **extra})


def test_render_returns_key_sized_image(tmp_path: Path):
    img, m = render_key_preview({"text": "Hi"}, tmp_path, mode="text")
    assert img is not None
    assert img.size == (90, 90)
    assert m["fits"] is True


def test_modes_differ(tmp_path: Path, icon_path: str):
    entry = {"text": "Mute", "icon": icon_path}
    imgs = {m: render_key_preview(entry, tmp_path, mode=m)[0] for m in ("text", "icon", "both")}
    assert imgs["text"].tobytes() != imgs["icon"].tobytes()
    assert imgs["text"].tobytes() != imgs["both"].tobytes()
    assert imgs["icon"].tobytes() != imgs["both"].tobytes()


def test_icon_mode_fills_about_two_thirds(tmp_path: Path, icon_path: str):
    img, _ = render_key_preview({"icon": icon_path, "background": "#000000"}, tmp_path, mode="icon")
    bbox = img.convert("RGB").getbbox()
    assert bbox is not None
    side = bbox[2] - bbox[0]
    assert 0.55 * 90 <= side <= 0.70 * 90


def test_text_mode_is_larger_than_default(tmp_path: Path):
    big, mb = render_key_preview({"text": "OK", "background": "#000000"}, tmp_path, mode="text")
    small, ms = render_key_preview({"text": "OK", "background": "#000000"}, tmp_path)
    assert mb["font_size"] > ms["font_size"]
    assert big.convert("RGB").getbbox() != small.convert("RGB").getbbox()


def test_offline_differs_and_is_dimmer(tmp_path: Path):
    entry = {"text": "Scene", "background": "#aa2244"}
    on, _ = render_key_preview(entry, tmp_path, mode="text")
    off, _ = render_key_preview(entry, tmp_path, mode="text", offline=True)
    assert on.tobytes() != off.tobytes()
    assert sum(off.convert("L").tobytes()) < sum(on.convert("L").tobytes())
    assert offline_look(entry)["background"] != entry["background"]


def test_fallback_texts():
    assert offline_fallback_text("dash") == "—"
    assert offline_fallback_text("none") == ""
    assert offline_fallback_text("last", "Gaming") == "Gaming"
    assert offline_fallback_text("last", None) == "—"
    assert offline_fallback_mode({"offline_fallback": "NONE"}) == "none"
    assert offline_fallback_mode({"offline_fallback": "bogus"}) == "dash"
    assert offline_fallback_mode(None) == "dash"


def test_measure_label_overflow_word():
    r = measure_label("Countdown", "text", 90)
    assert r["fits"] is False
    assert "Countdown" in r["clipped_words"]


def test_measure_label_fits_and_lines():
    r = measure_label("Hello World", "text", 90)
    assert r["fits"] is True
    assert r["lines"] == 2
    assert measure_label("Anything", "icon", 90) == {"fits": True, "clipped_words": [], "lines": 0, "font_size": 0}
    assert measure_label("", "text", 90)["lines"] == 0


def test_measure_label_too_many_lines():
    r = measure_label("a b c d e f g h i j k l m n o p q r s t u v w x y z", "text", 90)
    assert r["fits"] is False


def test_endpoint_headers_and_png(client: TestClient):
    resp = _post(client, {"text": "Hello World"}, mode="text")
    assert _png(resp).size == (90, 90)
    assert resp.headers["X-Key-Overflow"] == "0"
    assert resp.headers["X-Key-Lines"] == "2"
    resp = _post(client, {"text": "Countdown"}, mode="text")
    assert resp.headers["X-Key-Overflow"] == "1"


def test_endpoint_backward_compatible_shape(client: TestClient):
    # Old request shape: no mode / offline / live_value.
    resp = _post(client, {"text": "Mute", "background": "#112233"})
    assert _png(resp).size == (90, 90)
    assert resp.headers["X-Key-Overflow"] in ("0", "1")
    assert client.post("/api/preview_key", json={"entry": {}}).status_code == 404
    assert client.post("/api/preview_key", json={"entry": "x"}).status_code == 400
    assert _post(client, {"text": "x"}, mode="bogus").status_code == 400


def test_endpoint_live_offline_and_live_value(client: TestClient):
    entry = {"text": "x", "action": {"type": "display.obs_scene", "offline_fallback": "none"}}
    online = _post(client, entry, live_value="Gaming")
    offline = _post(client, entry, offline=True, live_value="Gaming")
    assert online.content != offline.content
    last = {"text": "x", "action": {"type": "display.obs_scene", "offline_fallback": "last"}}
    a = _post(client, last, offline=True, live_value="Gaming")
    b = _post(client, last, offline=True, live_value="Other")
    assert a.content != b.content


def test_cache_hits_and_animation_bypass(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}
    real = web_app.render_key_preview

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(web_app, "render_key_preview", spy)
    entry = {"text": "Cache me"}
    r1 = _post(client, entry, mode="text")
    r2 = _post(client, {"text": "Cache me"}, mode="text")
    assert r1.content == r2.content
    assert calls["n"] == 1
    _post(client, entry, mode="both")
    assert calls["n"] == 2
    _post(client, entry, mode="text", offline=True)
    assert calls["n"] == 3
    # Animation frames never touch the cache.
    anim = {"text": "Cache me", "idle_animation": "shake"}
    _post(client, anim, animation_frame=1)
    _post(client, anim, animation_frame=1)
    _post(client, entry, press_elapsed_frames=0)
    _post(client, entry, press_elapsed_frames=0)
    assert calls["n"] == 7


def test_preview_cache_lru_and_key(tmp_path: Path):
    c = PreviewCache(maxsize=2)
    c.put("a", (b"1", {}))
    c.put("b", (b"2", {}))
    assert c.get("a") is not None  # refresh a
    c.put("c", (b"3", {}))
    assert c.get("b") is None
    assert c.get("a") is not None and c.get("c") is not None
    k1 = preview_cache_key({"text": "a", "background": "#000"}, tmp_path, (90, 90), "text", False)
    k2 = preview_cache_key({"background": "#000", "text": "a"}, tmp_path, (90, 90), "TEXT", False)
    assert k1 == k2
    assert k1 != preview_cache_key({"text": "a", "background": "#000"}, tmp_path, (90, 90), "text", True)


def test_cache_key_tracks_icon_file_changes(tmp_path: Path, icon_path: str):
    entry = {"icon": icon_path}
    k1 = preview_cache_key(entry, tmp_path, (90, 90), "icon", False)
    p = Path(icon_path)
    st = p.stat()
    import os

    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert preview_cache_key(entry, tmp_path, (90, 90), "icon", False) != k1
