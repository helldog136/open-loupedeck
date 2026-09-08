from __future__ import annotations

from typing import Any

import pytest

from open_loupedeck import updater


def test_parse_version_basic_forms():
    assert updater._parse_version("v1.2.3") == (1, 2, 3)
    assert updater._parse_version("1.2") == (1, 2, 0)
    assert updater._parse_version("2") == (2, 0, 0)
    assert updater._parse_version("V0.1.0") == (0, 1, 0)


class _FakeResponse:
    def __init__(self, json_data: Any = None, text: str = "", status: int = 200) -> None:
        self._json = json_data
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json


RELEASE_JSON = {
    "tag_name": "v9.9.9",
    "html_url": "https://github.com/helldog136/open-loupedeck/releases/tag/v9.9.9",
    "assets": [
        {"name": "open-loupedeck-Setup-9.9.9.exe", "browser_download_url": "https://example/setup.exe"},
        {"name": "open-loupedeck-9.9.9.dmg", "browser_download_url": "https://example/app.dmg"},
        {"name": "open-loupedeck-9.9.9.AppImage", "browser_download_url": "https://example/app.AppImage"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://example/SHA256SUMS.txt"},
    ],
}


def test_check_for_update_finds_windows_asset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater, "current_version", lambda: "0.1.0")
    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: _FakeResponse(RELEASE_JSON))

    info = updater.check_for_update()

    assert info is not None
    assert info.version == "9.9.9"
    assert info.asset_name == "open-loupedeck-Setup-9.9.9.exe"
    assert info.checksum_url == "https://example/SHA256SUMS.txt"


def test_check_for_update_returns_none_when_not_newer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(updater, "current_version", lambda: "9.9.9")
    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: _FakeResponse(RELEASE_JSON))

    assert updater.check_for_update() is None


def test_check_for_update_returns_none_on_request_failure(monkeypatch: pytest.MonkeyPatch):
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr(updater.httpx, "get", _boom)
    assert updater.check_for_update() is None


def test_check_for_update_missing_platform_asset_still_returns_info(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setattr(updater, "current_version", lambda: "0.1.0")
    release_without_appimage = {
        "tag_name": "v9.9.9",
        "html_url": "https://example/releases/tag/v9.9.9",
        "assets": [{"name": "open-loupedeck-Setup-9.9.9.exe", "browser_download_url": "https://example/setup.exe"}],
    }
    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: _FakeResponse(release_without_appimage))

    info = updater.check_for_update()

    assert info is not None
    assert info.asset_url is None  # caller falls back to info.html_url


def test_expected_sha256_matches_by_filename(monkeypatch: pytest.MonkeyPatch):
    checksums_text = "abc123  open-loupedeck-Setup-9.9.9.exe\ndef456  open-loupedeck-9.9.9.dmg\n"
    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: _FakeResponse(text=checksums_text))

    got = updater._expected_sha256("https://example/SHA256SUMS.txt", "open-loupedeck-Setup-9.9.9.exe", timeout=5.0)

    assert got == "abc123"
