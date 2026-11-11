"""PyInstaller build spec for the open-loupedeck tray application (onedir).

Build from the repo root with:
    pyinstaller packaging/pyinstaller.spec --noconfirm

Windows/Linux output: dist/open-loupedeck/
macOS output: dist/open-loupedeck.app (a proper double-clickable bundle, plus the raw
dist/open-loupedeck/ onedir tree it was built from).
"""

import ctypes.util
import os
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
    (str(SRC_PKG / "locales"), "open_loupedeck/locales"),
    (str(SRC_PKG / "packs"), "open_loupedeck/packs"),
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
    # Device backends are imported lazily by open_loupedeck.devices.registry.
    "open_loupedeck.devices.loupedeck.backend",
    "open_loupedeck.devices.streamdeck.backend",
    "open_loupedeck.devices.virtual.backend",
    # python-elgato-streamdeck, imported lazily by the Stream Deck backend.
    "StreamDeck.DeviceManager",
    "StreamDeck.ImageHelpers.PILHelper",
    "StreamDeck.Transport.LibUSBHIDAPI",
]


def _hidapi_binaries() -> list[tuple[str, str]]:
    """The native hidapi library python-elgato-streamdeck loads with ctypes (Stream Deck backend).

    Bundled at the root of the app under a name the library tries (``hidapi.dll`` on Windows,
    ``libhidapi.dylib`` on macOS, ``libhidapi-libusb.so.0`` on Linux); PyInstaller's ctypes hook
    retries a failed bare-name load from the bundle. ``OPEN_LOUPEDECK_HIDAPI`` names the file
    explicitly (the Windows release job downloads it); otherwise the system's copy is used. Not
    found: the build goes on and the Stream Deck backend then needs hidapi installed on the system.
    """

    names = {"win32": ("hidapi", "hidapi.dll"), "darwin": ("hidapi", "libhidapi.dylib")}
    find, dest_name = names.get(sys.platform, ("hidapi-libusb", "libhidapi-libusb.so.0"))
    src = os.environ.get("OPEN_LOUPEDECK_HIDAPI") or ""
    if not src:
        found = ctypes.util.find_library(find) or ""
        if found and not os.path.isabs(found):
            # Linux find_library returns a soname: look for it in the usual library directories.
            for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib64", "/usr/lib"):
                if os.path.exists(os.path.join(d, found)):
                    found = os.path.join(d, found)
                    break
        if os.path.isabs(found):
            src = found
        elif sys.platform == "darwin":
            for prefix in ("/opt/homebrew", "/usr/local"):
                cand = os.path.join(prefix, "lib", "libhidapi.dylib")
                if os.path.exists(cand):
                    src = cand
                    break
    if not src or not os.path.isfile(src):
        print("WARNING: hidapi not found; the Stream Deck backend will need it installed on the system.")
        return []
    real = os.path.realpath(src)
    staged = Path(workpath) / "hidapi" / dest_name
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(Path(real).read_bytes())  # copied under the name the library looks for
    print(f"Bundling hidapi: {real} as {dest_name}")
    return [(str(staged), ".")]


binaries = _hidapi_binaries()

a = Analysis(
    [str(REPO_ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(REPO_ROOT / "src")],
    datas=datas,
    binaries=binaries,
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
