#!/usr/bin/env bash
# Build the Linux onedir bundle (PyInstaller) and wrap it in an AppImage.
#
# NOT YET TESTED ON REAL LINUX HARDWARE -- written to appimagetool's documented usage, review
# before relying on it. Run from the repo root on Linux:
#   bash packaging/linux/build_appimage.sh
#
# Downloads appimagetool on first run (cached under build/tools/) if not already on PATH.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/version = "(.*)"/\1/')"
APP_NAME="open-loupedeck"
OUT_DIR="packaging/linux/output"
APPDIR="build/${APP_NAME}.AppDir"
TOOLS_DIR="build/tools"

echo "Building PyInstaller bundle (version ${VERSION})..."
pyinstaller packaging/pyinstaller.spec --noconfirm

APPIMAGETOOL="${TOOLS_DIR}/appimagetool-x86_64.AppImage"
if ! command -v appimagetool >/dev/null 2>&1 && [ ! -x "$APPIMAGETOOL" ]; then
    echo "Fetching appimagetool..."
    mkdir -p "$TOOLS_DIR"
    curl -L -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi
APPIMAGETOOL_BIN="$(command -v appimagetool || echo "$APPIMAGETOOL")"

rm -rf "$APPDIR"
mkdir -p "${APPDIR}/usr/bin"
cp -R dist/open-loupedeck/. "${APPDIR}/usr/bin/"

cp "src/open_loupedeck/icons/app.png" "${APPDIR}/${APP_NAME}.png"

cat > "${APPDIR}/${APP_NAME}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=open-loupedeck
Exec=open-loupedeck
Icon=${APP_NAME}
Categories=Utility;
Terminal=false
EOF

cat > "${APPDIR}/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
exec "${HERE}/usr/bin/open-loupedeck" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

mkdir -p "$OUT_DIR"
OUT_FILE="${OUT_DIR}/${APP_NAME}-${VERSION}-x86_64.AppImage"
rm -f "$OUT_FILE"

ARCH=x86_64 "$APPIMAGETOOL_BIN" "$APPDIR" "$OUT_FILE"

echo "Built: $OUT_FILE"
