"""On GitHub Actions, surface test failures as annotations (readable without downloading the raw logs)."""

from __future__ import annotations

import os


def pytest_runtest_logreport(report) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    text = str(getattr(report, "longreprtext", "") or "")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    tail = " | ".join(lines[-3:])[:600].replace("%", "%25").replace("\r", " ").replace("\n", " ")
    print(f"::error title=FAILED {report.nodeid}::{tail}")
