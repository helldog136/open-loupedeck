#!/usr/bin/env bash
# Build the macOS .app bundle (PyInstaller) and wrap it in a .dmg.
#
# NOT YET TESTED ON REAL macOS HARDWARE -- written to the documented PyInstaller/hdiutil
# behavior, review before relying on it. Run from the repo root on macOS:
#   bash packaging/macos/build_dmg.sh
#
# The app is NOT code-signed or notarized (no Apple Developer account yet), so Gatekeeper
# will show an "unidentified developer" warning on first launch (right-click > Open works
# around it). See the plan / release notes for how to explain this to users.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/version = "(.*)"/\1/')"
APP_NAME="open-loupedeck"
OUT_DIR="packaging/macos/output"
STAGING_DIR="build/dmg-staging"

echo "Building PyInstaller bundle (version ${VERSION})..."
pyinstaller packaging/pyinstaller.spec --noconfirm

if [ ! -d "dist/${APP_NAME}.app" ]; then
    echo "error: dist/${APP_NAME}.app not found -- did the spec's BUNDLE() step run? (macOS only)" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -R "dist/${APP_NAME}.app" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

DMG_PATH="${OUT_DIR}/${APP_NAME}-${VERSION}.dmg"
rm -f "$DMG_PATH"

hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING_DIR" -ov -format UDZO "$DMG_PATH"

echo "Built: $DMG_PATH"
