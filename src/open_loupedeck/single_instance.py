"""Single-instance guard for the tray app.

Uses a tiny local control socket, independent of the web UI port, so this works the same way
regardless of whether ``--web`` is enabled or which port it ends up on.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Arbitrary fixed high port, loopback-only. Unrelated to the web UI port on purpose.
CONTROL_PORT = 47212
_SHOW_COMMAND = b"show"


def notify_running_instance() -> bool:
    """Best-effort: ask an already-running instance to show its window.

    Returns True if a running instance was reached, False if nothing is listening there
    (meaning: no other instance is running).
    """

    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=1.0) as sock:
            sock.sendall(_SHOW_COMMAND)
        return True
    except OSError:
        return False


def try_become_primary_instance(on_show_requested: Callable[[], None]) -> bool:
    """Bind the control port and, on success, serve it on a background thread forever.

    Returns True if this process is now the primary instance. Returns False if the port was
    already taken by another instance -- the caller should not start the agent or tray icon.
    """

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(("127.0.0.1", CONTROL_PORT))
        server.listen(4)
    except OSError:
        logger.debug("single_instance: control port %s already taken", CONTROL_PORT)
        server.close()
        return False

    def _serve() -> None:
        while True:
            try:
                conn, _addr = server.accept()
            except OSError:
                return  # server socket was closed
            with conn, contextlib.suppress(OSError):
                data = conn.recv(64)
                if data.strip() == _SHOW_COMMAND:
                    with contextlib.suppress(Exception):
                        on_show_requested()

    threading.Thread(target=_serve, name="single-instance-control", daemon=True).start()
    logger.debug("single_instance: listening on control port %s", CONTROL_PORT)
    return True
