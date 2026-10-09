"""On GitHub Actions, surface test failures as annotations (readable without downloading the raw logs)."""

from __future__ import annotations

import os

_config = None


def pytest_configure(config) -> None:
    global _config
    _config = config


def pytest_runtest_logreport(report) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed or _config is None:
        return
    tr = _config.pluginmanager.get_plugin("terminalreporter")
    if tr is None:
        return
    text = str(getattr(report, "longreprtext", "") or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    tail = " | ".join(lines[-3:])[:600].replace("%", "%25").replace("\r", " ").replace("\n", " ")
    tr.write_line("")
    tr.write_line(f"::error title=FAILED {report.nodeid}::{tail}")
