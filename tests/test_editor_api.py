"""The API the model-driven editor uses: the stored v2 config both ways, previews sized for the model
the editor lays out, starter packs fitted to that model, and every model it can offer."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from PIL import Image

from open_loupedeck.config_io import load_raw_config, save_raw_config
from open_loupedeck.config_state import ConfigState
from open_loupedeck.devices.model import parse_key_id
from open_loupedeck.runtime_refs import AgentRuntimeRefs
from open_loupedeck.web_app import create_web_app


def _client(tmp_path: Path, raw: dict[str, Any]) -> tuple[TestClient, Path]:
    path = tmp_path / "config.yaml"
    save_raw_config(path, raw)
    rt = AgentRuntimeRefs(deck=None, no_device=True)
    return TestClient(create_web_app(path, ConfigState(path), asyncio.Lock(), runtime=rt)), path


V2 = {
    "config_version": 2,
    "device": {"model": "auto"},
    "global": {"button_0": {"action": {"type": "agent.goto_page", "index": 0}, "button_color": "#3b6bff"}},
    "pages": [{"name": "Main", "controls": {"key_0_0": {"text": "A"}, "knob_0": {"rotate": {"duo": "system_volume"}}}}],
}


def _size(resp) -> tuple[int, int]:
    assert resp.status_code == 200, resp.text
    return Image.open(io.BytesIO(resp.content)).size


def test_v2_config_round_trip_and_model_choice(tmp_path: Path) -> None:
    client, path = _client(tmp_path, V2)
    cfg = client.get("/api/config?format=v2").json()
    assert cfg["config_version"] == 2 and "buttons" not in cfg["pages"][0]
    cfg["global"]["key_1_1"] = {"text": "every page"}
    cfg["pages"][0]["controls"]["key_0_0"] = {"text": "B"}
    cfg["device"]["model"] = "virtual_mega"
    assert client.put("/api/config?format=v2", json=cfg).status_code == 200
    stored = load_raw_config(path)
    assert stored["global"]["key_1_1"] == {"text": "every page"}
    assert stored["global"]["button_0"]["button_color"] == "#3b6bff"
    assert stored["pages"][0]["controls"]["key_0_0"] == {"text": "B"}
    assert stored["device"]["model"] == "virtual_mega"
    # The model it names is the one /api/device_model now describes (no device connected).
    dm = client.get("/api/device_model").json()
    assert dm["source"] == "config" and dm["model"]["id"] == "virtual_mega"
    assert {"virtual_15", "virtual_mega", "virtual_mini", "loupedeck_live_s"} <= set(dm["known_models"])


def test_preview_is_sized_for_the_model_the_editor_names(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, V2)
    body = {"entry": {"text": "Hi"}, "control_id": "key_0_0"}
    assert _size(client.post("/api/preview_key", json=body)) == (90, 90)  # Live S (auto, no device)
    assert _size(client.post("/api/preview_key", json={**body, "model": "virtual_mega"})) == (72, 72)
    assert _size(client.post("/api/preview_key", json={**body, "model": "virtual_mini"})) == (96, 96)
    # An unknown model name falls back to the UI's model rather than failing.
    assert _size(client.post("/api/preview_key", json={**body, "model": "nope"})) == (90, 90)


def test_packs_are_fitted_to_the_requested_model(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, V2)
    packs = client.get("/api/packs?lang=en&model=virtual_mini").json()["packs"]
    assert packs and all(p["model"] == "virtual_mini" for p in packs)
    for p in packs:
        for page in p["pages"]:
            for cid in page["controls"]:
                at = parse_key_id(cid)
                assert at is None or (at[0] < 3 and at[1] < 2), (p["id"], cid)
    assert any(p["dropped"] for p in packs)
    default = client.get("/api/packs?lang=en").json()["packs"]
    assert all(p["model"] == "loupedeck_live_s" for p in default)
