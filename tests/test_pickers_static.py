"""The reusable pickers (static/js/pickers): files are served with the right MIME type and icons.json is sane."""

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
PICKERS = STATIC / "js" / "pickers"
MODULES = ["action-picker.js", "icon-gallery.js", "color-picker.js", "helpers.js", "common.js"]
JS_TYPES = {"text/javascript", "application/javascript"}


@pytest.fixture()
def client(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    return TestClient(create_web_app(cfg, ConfigState(cfg), asyncio.Lock()))


def test_picker_modules_served_as_javascript(client: TestClient) -> None:
    for name in MODULES:
        resp = client.get(f"/assets/ui/js/pickers/{name}")
        assert resp.status_code == 200, name
        assert resp.headers["content-type"].split(";")[0] in JS_TYPES, name


def test_icons_json_served_as_json(client: TestClient) -> None:
    resp = client.get("/assets/ui/js/pickers/icons.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].split(";")[0] == "application/json"
    assert isinstance(resp.json(), list)


def test_pickers_page_and_css_served(client: TestClient) -> None:
    page = client.get("/assets/ui/pickers.html")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "/assets/ui/css/pickers.css" in page.text
    css = client.get("/assets/ui/css/pickers.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")


def test_icons_json_valid() -> None:
    icons = json.loads((PICKERS / "icons.json").read_text(encoding="utf-8"))
    assert len(icons) >= 250
    names = [i["name"] for i in icons]
    assert len(names) == len(set(names)), "duplicate icon names"
    slug = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
    for icon in icons:
        assert slug.match(icon["name"]), icon
        assert icon["keywords"] and all(isinstance(k, str) and k.strip() for k in icon["keywords"]), icon
        assert icon.get("cat"), icon


def test_icon_categories_have_translations() -> None:
    icons = json.loads((PICKERS / "icons.json").read_text(encoding="utf-8"))
    en = json.loads((package_root() / "locales" / "en.json").read_text(encoding="utf-8"))
    for cat in {i["cat"] for i in icons}:
        assert f"picker.icon.cat.{cat}" in en, cat


def test_picker_modules_use_only_relative_imports() -> None:
    import_re = re.compile(r"""^\s*(?:import|export)\b[^;]*?\bfrom\s+["']([^"']+)["']""", re.M | re.S)
    for path in PICKERS.glob("*.js"):
        for spec in import_re.findall(path.read_text(encoding="utf-8")):
            assert spec.startswith("."), f"{path.name}: {spec}"
            assert (path.parent / spec).resolve().is_file(), f"{path.name} imports missing {spec}"
