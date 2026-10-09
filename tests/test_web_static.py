"""The config UI's static front-end: ES modules are served with a JS MIME type and their imports resolve."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from open_loupedeck.config_state import ConfigState
from open_loupedeck.package_paths import package_root
from open_loupedeck.web_app import create_web_app

STATIC = package_root() / "static"
JS = STATIC / "js"
IMPORT_RE = re.compile(r"""^\s*(?:import|export)\b[^;]*?\bfrom\s+["']([^"']+)["']""", re.M | re.S)


@pytest.fixture()
def client(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    return TestClient(create_web_app(cfg, ConfigState(cfg), asyncio.Lock()))


def test_index_loads_entry_module(client: TestClient) -> None:
    html = client.get("/").text
    assert '<script type="module" src="/assets/ui/js/main.js"></script>' in html


def test_modules_served_as_javascript(client: TestClient) -> None:
    for path in sorted(JS.rglob("*.js")):
        rel = path.relative_to(STATIC).as_posix()
        resp = client.get(f"/assets/ui/{rel}")
        assert resp.status_code == 200, rel
        assert resp.headers["content-type"].split(";")[0] in {"text/javascript", "application/javascript"}, rel


def test_relative_imports_resolve() -> None:
    files = sorted(JS.rglob("*.js"))
    assert (JS / "main.js") in files
    for path in files:
        for spec in IMPORT_RE.findall(path.read_text(encoding="utf-8")):
            assert spec.startswith("."), f"{path.name}: non-relative import {spec!r} (no bundler)"
            target = (path.parent / spec).resolve()
            assert target.is_file(), f"{path.relative_to(JS)} imports missing {spec}"
