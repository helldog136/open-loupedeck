"""CI guard: every locale file must match en.json (see scripts/check_locales.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from open_loupedeck import i18n

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_locales.py"
_spec = importlib.util.spec_from_file_location("check_locales", _SCRIPT)
assert _spec and _spec.loader
check_locales = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_locales)


def test_locale_files_are_consistent() -> None:
    problems = check_locales.check_locales(i18n.locales_dir())
    assert not problems, "Locale problems:\n  - " + "\n  - ".join(problems)


def test_checker_reports_missing_extra_and_placeholders(tmp_path: Path) -> None:
    (tmp_path / "en.json").write_text(json.dumps({"_meta.name": "English", "a": "Hi {name}", "b": "x"}))
    (tmp_path / "xx.json").write_text(json.dumps({"_meta.name": "Xx", "a": "Salut", "c": "extra"}))
    msg = "\n".join(check_locales.check_locales(tmp_path))
    assert "missing keys: b" in msg
    assert "extra keys (not in en.json): c" in msg
    assert "{name}" in msg


def test_available_languages_have_native_names() -> None:
    langs = {d["code"]: d["name"] for d in i18n.available_languages()}
    assert langs["en"] == "English"
    assert langs["fr"] == "Français"


def test_t_fallbacks_and_interpolation() -> None:
    assert i18n.t("tray.quit", lang="fr") == "Quitter"
    assert i18n.t("tray.quit", lang="zz") == "Quit"
    assert i18n.t("no.such.key", lang="fr") == "no.such.key"
    assert i18n.t("tray.update.install", lang="en", version="1.2.3") == "Install update 1.2.3"
    assert i18n.t("tray.update.install", lang="en") == "Install update {version}"


def test_plurals() -> None:
    assert i18n.t("pages.count", lang="en", count=1) == "1 page"
    assert i18n.t("pages.count", lang="en", count=0) == "0 pages"
    assert i18n.t("pages.count", lang="fr", count=0) == "0 page"
    assert i18n.t("pages.count", lang="fr", count=5) == "5 pages"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("fr", "fr"), ("FR", "fr"), ("fr_FR.UTF-8", "fr"), ("fr-CA", "fr"), ("xx", "en"), ("en", "en")],
)
def test_resolve_explicit(value: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "detect_os_language", lambda: "ja_JP")
    assert i18n.resolve_language(value) == expected


def test_resolve_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "detect_os_language", lambda: "fr_BE.UTF-8")
    assert i18n.resolve_language("auto") == "fr"
    monkeypatch.setattr(i18n, "detect_os_language", lambda: "ja_JP")
    assert i18n.resolve_language("auto") == "en"
    monkeypatch.setattr(i18n, "detect_os_language", lambda: None)
    assert i18n.resolve_language("auto") == "en"
