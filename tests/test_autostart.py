"""Autostart entries launch the app in the background (no config window at login)."""

from __future__ import annotations

from open_loupedeck import autostart


def test_launch_argv_carries_background_flag():
    assert autostart._launch_argv()[-1] == autostart.BACKGROUND_FLAG


def test_windows_command_line_quotes_each_part_and_keeps_flag():
    line = autostart._windows_command_line()
    assert line.endswith(f'"{autostart.BACKGROUND_FLAG}"')


def test_linux_desktop_entry_execs_with_flag():
    assert autostart.BACKGROUND_FLAG in autostart._linux_desktop_text().splitlines()[3]


def test_macos_plist_lists_flag_as_program_argument():
    assert f"<string>{autostart.BACKGROUND_FLAG}</string>" in autostart._macos_plist_text()
