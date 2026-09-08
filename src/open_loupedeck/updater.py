"""Check GitHub Releases for a newer version and (Windows) apply it via the installer.

The update check itself works on every OS; only ``apply_windows_update`` actually replaces a
running install. On macOS/Linux, callers should send the user to ``UpdateInfo.html_url`` instead
-- self-replacing a running ``.app`` bundle or AppImage safely needs a dedicated relaunch helper
that isn't built yet.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GITHUB_OWNER = "helldog136"
GITHUB_REPO = "open-loupedeck"
PACKAGE_NAME = "open-loupedeck"

_API_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
_CHECKSUMS_ASSET_NAME = "SHA256SUMS.txt"
_ASSET_SUFFIX_BY_PLATFORM = {
    "win32": ".exe",
    "darwin": ".dmg",
    "linux": ".AppImage",
}


def _parse_version(raw: str) -> tuple[int, int, int]:
    s = raw.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in s.split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def current_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return "0.0.0"


@dataclass
class UpdateInfo:
    version: str
    html_url: str
    asset_url: str | None
    asset_name: str | None
    checksum_url: str | None


def check_for_update(timeout: float = 8.0) -> UpdateInfo | None:
    """Return update info if the latest GitHub release is newer than this build, else None."""

    try:
        r = httpx.get(
            _API_LATEST_RELEASE_URL,
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
            follow_redirects=True,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        logger.debug("check_for_update: GitHub API request failed", exc_info=True)
        return None

    tag = str(data.get("tag_name") or "")
    if not tag or _parse_version(tag) <= _parse_version(current_version()):
        return None

    assets = data.get("assets") or []
    suffix = _ASSET_SUFFIX_BY_PLATFORM.get(sys.platform)
    asset_url: str | None = None
    asset_name: str | None = None
    checksum_url: str | None = None
    for a in assets:
        name = str(a.get("name") or "")
        if name == _CHECKSUMS_ASSET_NAME:
            checksum_url = a.get("browser_download_url")
        elif suffix and asset_url is None and name.endswith(suffix):
            asset_url = a.get("browser_download_url")
            asset_name = name

    html_url = str(data.get("html_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest")
    logger.info("Update available: %s (current: %s)", tag, current_version())
    return UpdateInfo(
        version=tag.lstrip("vV"),
        html_url=html_url,
        asset_url=asset_url,
        asset_name=asset_name,
        checksum_url=checksum_url,
    )


def _expected_sha256(checksum_url: str, asset_name: str, timeout: float) -> str | None:
    try:
        r = httpx.get(checksum_url, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
    except Exception:
        logger.debug("Could not fetch %s", _CHECKSUMS_ASSET_NAME, exc_info=True)
        return None
    for raw_line in r.text.splitlines():
        line = raw_line.strip()
        if line.endswith(asset_name):
            return line.split()[0].lower()
    return None


def download_update(info: UpdateInfo, timeout: float = 120.0) -> Path:
    """Download the platform installer asset to a temp file, verifying its checksum when published."""

    if not info.asset_url or not info.asset_name:
        raise RuntimeError("No installer asset for this platform in the latest release")

    dest = Path(tempfile.gettempdir()) / info.asset_name
    hasher = hashlib.sha256()
    with httpx.stream("GET", info.asset_url, timeout=timeout, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(65536):
                f.write(chunk)
                hasher.update(chunk)

    if info.checksum_url:
        expected = _expected_sha256(info.checksum_url, info.asset_name, timeout=15.0)
        if expected is None:
            logger.warning("No checksum found for %s; installing unverified", info.asset_name)
        elif expected != hasher.hexdigest().lower():
            dest.unlink(missing_ok=True)
            raise RuntimeError("Downloaded update failed checksum verification")

    return dest


def apply_windows_update(installer_path: Path) -> None:
    """Launch the downloaded installer silently and detached.

    Relies on Inno Setup's ``/CLOSEAPPLICATIONS`` (plus the ``AppMutex`` declared in
    ``packaging/windows/installer.iss``) to close this running app via the Windows Restart
    Manager, and ``/RESTARTAPPLICATIONS`` to relaunch it once installed -- this call does not,
    and should not, exit the current process itself.
    """

    subprocess.Popen(
        [
            str(installer_path),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/RESTARTAPPLICATIONS",
        ],
        close_fds=True,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
