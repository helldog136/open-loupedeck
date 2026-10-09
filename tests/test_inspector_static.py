"""The key inspector's static front-end: modules and stylesheet are served, index.html mounts it, every
``t("inspector.…")`` key it uses exists in every locale, and the knob extension point is exported."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_loupedeck.config_state import ConfigState
from open_loupedeck.package_paths import package_root
from open_loupedeck.web_app import create_web_app

STATIC = package_root() / "static"
INSPECTOR = STATIC / "js" / "inspector"
LOCALES = package_root() / "locales"
MODULES = [
    "index.js",
    "key-view.js",
    "appearance.js",
    "advanced.js",
    "page-button-view.js",
    "entry.js",
    "edit.js",
    "controls.js",
    "dom.js",
    "preview.js",
    "panel.js",
    "clipboard.js",
]
T_KEY = re.compile(r"""\bt\(\s*["'`](inspector\.[a-z0-9_.]+)["'`]""")


@pytest.fixture()
def client(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    return TestClient(create_web_app(cfg, ConfigState(cfg), asyncio.Lock()))


def test_inspector_modules_and_css_are_served(client: TestClient) -> None:
    for name in MODULES:
        resp = client.get(f"/assets/ui/js/inspector/{name}")
        assert resp.status_code == 200, name
        assert resp.headers["content-type"].split(";")[0] in {"text/javascript", "application/javascript"}, name
    css = client.get("/assets/ui/css/inspector.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")


def test_old_editor_modules_are_gone() -> None:
    assert not (INSPECTOR / "editor.js").exists()
    assert not (INSPECTOR / "look-fields.js").exists()


def test_index_mounts_the_inspector(client: TestClient) -> None:
    html = client.get("/").text
    assert '<link rel="stylesheet" href="/assets/ui/css/inspector.css" />' in html
    assert 'id="keyEditorBlock"' in html
    assert 'id="btnApply"' not in html  # no Apply button: every change applies live


def test_extension_point_is_exported() -> None:
    src = (INSPECTOR / "index.js").read_text(encoding="utf-8")
    assert "export function registerInspectorView(" in src
    assert '"knob:open"' in src and '"control:open"' in src


def test_every_inspector_string_key_exists_in_every_locale() -> None:
    used: set[str] = set()
    for path in [*INSPECTOR.glob("*.js"), STATIC / "js" / "action-fields.js", STATIC / "js" / "key-sequence.js"]:
        # keys built from a template (`inspector.live.fallback.${v}`) end with "." here: skip them
        used |= {k for k in T_KEY.findall(path.read_text(encoding="utf-8")) if not k.endswith(".")}
    assert used, "no inspector keys found"
    for code in ("en", "fr"):
        messages = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        missing = sorted(k for k in used if k not in messages and f"{k}.other" not in messages)
        assert not missing, f"{code}: {missing}"
