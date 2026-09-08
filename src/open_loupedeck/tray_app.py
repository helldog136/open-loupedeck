"""System tray entry point: background agent + tray icon + a native setup window.

Wraps the exact same FastAPI-served web UI the CLI's ``--web`` flag already serves (see
``web_app.py`` / ``static/``) in a real OS window via ``pywebview`` -- no browser, no address
bar, and no changes needed to the web UI itself.

Threading model (validated on Windows; macOS/Linux may need this flipped -- see the plan):
pywebview owns the main thread (``webview.start()``), the tray icon runs on its own background
thread, and the agent (asyncio + its embedded web server) runs on a third background thread via
``app.start_agent_in_background_thread``.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
import webbrowser

import pystray
import webview
from PIL import Image

from . import single_instance, updater
from .app import DEFAULT_WEB_ADDR, AgentHandle, start_agent_in_background_thread
from .config_paths import default_config_path
from .package_paths import package_root

logger = logging.getLogger(__name__)

_ICON_PATH = package_root() / "icons" / "app.png"
_WEB_URL = f"http://{DEFAULT_WEB_ADDR}"

# Matches the AppMutex Inno Setup will be told to look for (packaging/windows/installer.iss),
# so its /CLOSEAPPLICATIONS can find and close this running app via the Windows Restart Manager
# during a silent auto-update. Never released explicitly: the OS reclaims it on process exit.
_WINDOWS_APP_MUTEX_NAME = "OpenLoupedeckTrayMutex"

_UPDATE_CHECK_INTERVAL_SEC = 24 * 60 * 60

_windows_app_mutex_handle: int | None = None


def _create_windows_app_mutex() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    global _windows_app_mutex_handle
    _windows_app_mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, _WINDOWS_APP_MUTEX_NAME)


class TrayApp:
    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._icon: pystray.Icon | None = None
        self._agent: AgentHandle | None = None
        self._update_info: updater.UpdateInfo | None = None
        self._update_downloading = False
        self._quitting = False

    # --- window -----------------------------------------------------------------

    def show_window(self) -> None:
        if self._window is not None:
            self._window.show()

    def _on_window_closing(self) -> bool:
        # Hide instead of destroying: the agent (and the deck) keep running in the background.
        if self._window is not None:
            self._window.hide()
        return False

    # --- menu actions -------------------------------------------------------------

    def _quit(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        # Idempotent: a double-click (or the menu re-delivering the notify message before the
        # icon visually disappears) must not try to shut an already-stopped agent down again --
        # that raced into "Event loop is closed" and left the process stuck, unkillable except
        # via Task Manager.
        if self._quitting:
            logger.info("Tray: quit already in progress, ignoring")
            return
        self._quitting = True
        logger.info("Tray: quit requested")
        if self._agent is not None:
            with contextlib.suppress(Exception):
                self._agent.request_shutdown()
                self._agent.join(timeout=10)
        if self._window is not None:
            with contextlib.suppress(Exception):
                self._window.destroy()
        with contextlib.suppress(Exception):
            icon.stop()

    # --- updates --------------------------------------------------------------------

    def _update_menu_text(self, _item: pystray.MenuItem) -> str:
        if self._update_downloading:
            return "Téléchargement de la mise à jour…"
        if self._update_info is not None:
            return f"Installer la mise à jour {self._update_info.version}"
        return "Rechercher une mise à jour"

    def _on_update_found(self, info: updater.UpdateInfo) -> None:
        self._update_info = info
        if self._icon is not None:
            with contextlib.suppress(Exception):
                self._icon.notify(f"open-loupedeck {info.version} est disponible.", "Mise à jour disponible")
            self._icon.update_menu()

    def _update_check_loop(self) -> None:
        while True:
            info = updater.check_for_update()
            if info is not None:
                self._on_update_found(info)
            time.sleep(_UPDATE_CHECK_INTERVAL_SEC)

    def _on_update_menu_click(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        if self._update_downloading:
            return

        if self._update_info is None:
            info = updater.check_for_update()
            if info is None:
                icon.notify("Aucune mise à jour disponible.", "open-loupedeck")
            else:
                self._on_update_found(info)
            return

        if sys.platform != "win32":
            # macOS/Linux: no automated self-replace yet -- send the user to the release page.
            webbrowser.open(self._update_info.html_url)
            return

        info = self._update_info
        self._update_downloading = True
        icon.update_menu()
        try:
            installer_path = updater.download_update(info)
            updater.apply_windows_update(installer_path)
            icon.notify("Installation en cours, l'application va redémarrer…", "open-loupedeck")
        except Exception:
            logger.exception("Update to %s failed", info.version)
            icon.notify("Échec de la mise à jour.", "open-loupedeck")
            self._update_downloading = False
            self._update_info = None
            icon.update_menu()

    # --- setup ------------------------------------------------------------------------

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "Ouvrir la configuration",
                lambda _icon, _item: self.show_window(),
                default=True,
            ),
            pystray.MenuItem(self._update_menu_text, self._on_update_menu_click),
            pystray.MenuItem("Quitter", self._quit),
        )

    def run(self) -> None:
        if not single_instance.try_become_primary_instance(self.show_window):
            logger.info("Another instance is already running; asking it to show its window.")
            single_instance.notify_running_instance()
            return

        _create_windows_app_mutex()

        self._agent = start_agent_in_background_thread(default_config_path())

        self._window = webview.create_window(
            "open-loupedeck",
            url=_WEB_URL,
            width=1100,
            height=760,
        )
        self._window.events.closing += self._on_window_closing

        self._icon = pystray.Icon(
            "open-loupedeck",
            Image.open(_ICON_PATH),
            "open-loupedeck",
            self._build_menu(),
        )
        self._icon.run_detached()

        threading.Thread(target=self._update_check_loop, name="update-check", daemon=True).start()

        # pywebview needs the main thread on macOS; keeping it there on every OS is the
        # simplest arrangement that is known to work everywhere.
        webview.start()


def main() -> None:
    TrayApp().run()


if __name__ == "__main__":
    main()
