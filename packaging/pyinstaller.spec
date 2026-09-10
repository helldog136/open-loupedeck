"""PyInstaller build spec for the open-loupedeck tray application (onedir).

Build from the repo root with:
    pyinstaller packaging/pyinstaller.spec --noconfirm

Windows/Linux output: dist/open-loupedeck/
macOS output: dist/open-loupedeck.app (a proper double-clickable bundle, plus the raw
dist/open-loupedeck/ onedir tree it was built from).
"""

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

REPO_ROOT = Path(SPECPATH).resolve().parent
SRC_PKG = REPO_ROOT / "src" / "open_loupedeck"


def _project_version() -> str:
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (REPO_ROOT / "pyproject.toml").read_text())
    return m.group(1) if m else "0.0.0"

# Debug builds (console window + full logging) are far easier to diagnose than a silent
# windowed app when something about the freeze itself is wrong. Windows/macOS/Linux builds are
# verified (Phase 3) -- windowed from here on; flip back to True only for freeze-level debugging.
DEBUG_CONSOLE = False

datas = [
    (str(SRC_PKG / "static"), "open_loupedeck/static"),
    (str(SRC_PKG / "icons"), "open_loupedeck/icons"),
]
# Needed for importlib.metadata.version("open-loupedeck") (used by the auto-updater) to work
# once frozen -- without this, dist-info isn't bundled and the app can't read its own version.
datas += copy_metadata("open-loupedeck")

hiddenimports = [
    # pywebview picks its platform backend dynamically (importlib), which PyInstaller's
    # static import analysis does not always follow.
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "webview.platforms.cocoa",
    "webview.platforms.gtk",
    "webview.platforms.qt",
    # Same for pystray's backend.
    "pystray._win32",
    "pystray._darwin",
    "pystray._xorg",
    "pystray._appindicator",
    "pystray._gtk",
    # uvicorn resolves its event loop / protocol implementations the same dynamic way.
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # pynput (keyboard.play_sequence action) resolves its backend the same dynamic way.
    "pynput.keyboard._win32",
    "pynput.keyboard._darwin",
    "pynput.keyboard._xorg",
    "pynput.keyboard._uinput",
]

a = Analysis(
    [str(REPO_ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(REPO_ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    icon_file = str(SRC_PKG / "icons" / "app.ico")
elif sys.platform == "darwin":
    icon_file = str(SRC_PKG / "icons" / "app.icns")
else:
    icon_file = str(SRC_PKG / "icons" / "app.png")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="open-loupedeck",
    console=DEBUG_CONSOLE,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="open-loupedeck",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="open-loupedeck.app",
        icon=icon_file,
        bundle_identifier="com.open-loupedeck.agent",
        info_plist={
            "CFBundleShortVersionString": _project_version(),
            "LSUIElement": True,  # tray-only app: no Dock icon, no menu bar
        },
    )
