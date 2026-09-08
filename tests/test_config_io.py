from __future__ import annotations

from pathlib import Path

import pytest

from open_loupedeck.config_io import (
    ensure_minimal_structure,
    load_raw_config,
    raw_to_settings,
    save_raw_config,
)


def test_load_raw_config_roundtrip(tmp_path: Path):
    path = tmp_path / "config.yaml"
    save_raw_config(path, {"pages": [], "obs": {"host": "127.0.0.1", "port": 4455}})
    loaded = load_raw_config(path)
    assert loaded["obs"]["port"] == 4455


def test_save_raw_config_leaves_no_leftover_temp_file(tmp_path: Path):
    path = tmp_path / "config.yaml"
    save_raw_config(path, {"pages": []})
    leftovers = list(tmp_path.glob("*.tmp-*"))
    assert leftovers == []
    assert path.is_file()


def test_save_raw_config_does_not_corrupt_existing_file_on_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import open_loupedeck.config_io as config_io_module

    path = tmp_path / "config.yaml"
    save_raw_config(path, {"pages": [{"id": 0, "name": "Original"}]})
    original_bytes = path.read_bytes()

    def _boom(*args, **kwargs):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(config_io_module.os, "fsync", _boom)

    with pytest.raises(OSError, match="disk full"):
        save_raw_config(path, {"pages": [{"id": 0, "name": "Corrupted"}]})

    # The real file must be untouched -- the failed write only ever touched the temp file.
    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob("*.tmp-*")) == []


def test_load_raw_config_empty_file_returns_empty_dict(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("")
    assert load_raw_config(path) == {}


def test_load_raw_config_rejects_non_mapping_root(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(TypeError, match="mapping"):
        load_raw_config(path)


def test_raw_to_settings_rejects_non_list_pages():
    with pytest.raises(TypeError, match="pages must be a list"):
        raw_to_settings({"pages": "nope"})


def test_raw_to_settings_rejects_non_list_bindings():
    with pytest.raises(TypeError, match="bindings must be a list"):
        raw_to_settings({"bindings": "nope"})


def test_raw_to_settings_defaults_device_model_to_auto():
    settings = raw_to_settings({})
    assert settings.device.model == "auto"
    assert settings.device.baudrate is None


def test_ensure_minimal_structure_fills_missing_sections():
    out = ensure_minimal_structure({})
    for key in (
        "pages",
        "bindings",
        "plugin_modules",
        "device",
        "obs",
        "ha",
        "logging",
        "global_buttons",
        "knob_pages",
    ):
        assert key in out
    assert out["device"]["model"] == "auto"
    assert out["ha"] == {"base_url": "", "token": ""}


def test_raw_to_settings_parses_ha_section():
    settings = raw_to_settings({"ha": {"base_url": "http://homeassistant.local:8123", "token": "abc"}})
    assert settings.ha is not None
    assert settings.ha.base_url == "http://homeassistant.local:8123"
    assert settings.ha.token == "abc"


def test_raw_to_settings_ha_is_none_when_absent():
    assert raw_to_settings({}).ha is None


def test_ensure_minimal_structure_does_not_mutate_input():
    raw = {"pages": [{"id": 0}]}
    out = ensure_minimal_structure(raw)
    out["pages"].append({"id": 1})
    assert len(raw["pages"]) == 1


def test_ensure_minimal_structure_normalizes_live_s_btn_0_alias():
    raw = {
        "device": {"model": "live_s"},
        "pages": [],
        "global_buttons": {"btn_0": {"button_color": " #ff0000 "}},
    }
    out = ensure_minimal_structure(raw)
    assert "btn_0" not in out["global_buttons"]
    assert out["global_buttons"]["btn_circle"]["button_color"] == "#ff0000"
    # Live S always gets at least one page, with a normalized id/name.
    assert len(out["pages"]) == 1
    assert out["pages"][0]["id"] == 0
    assert out["pages"][0]["name"] == "Page 1"
