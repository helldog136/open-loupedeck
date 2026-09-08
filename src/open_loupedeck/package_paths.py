"""Locate this package's own bundled data files (``static/``, ``icons/``) -- frozen-build aware.

``Path(__file__)`` does not reliably point at a real on-disk directory once frozen by
PyInstaller: pure-Python modules are compiled into an archive rather than kept as loose files,
so sibling data directories placed next to the source no longer exist next to ``__file__`` at
runtime. ``sys._MEIPASS`` (set by PyInstaller in both onefile and onedir modes) must be used
instead once frozen.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Must match the destination path used for `datas` in packaging/pyinstaller.spec, and the
# force-include mapping in pyproject.toml's [tool.hatch.build.targets.wheel.force-include].
_PACKAGE_DIR_NAME = "open_loupedeck"


def package_root() -> Path:
    """Root directory holding this package's bundled data directories."""

    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent)
        return base / _PACKAGE_DIR_NAME
    return Path(__file__).resolve().parent
