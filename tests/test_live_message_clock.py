"""``display.clock`` with a named IANA timezone -- needs the `tzdata` package on Windows,
which has no system-provided timezone database (see pyproject.toml's win32-conditional dep).
"""

from __future__ import annotations

from open_loupedeck.live_message import format_clock_overlay_text


def test_named_timezone_resolves_without_raising():
    text = format_clock_overlay_text({"timezone": "Europe/Paris", "time_format": "%H:%M"})
    assert "\n" in text


def test_invalid_timezone_falls_back_to_local_time():
    text = format_clock_overlay_text({"timezone": "Not/AZone", "time_format": "%H:%M"})
    assert "\n" in text


def test_no_timezone_uses_local_time():
    text = format_clock_overlay_text({})
    assert "\n" in text
