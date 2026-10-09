"""Cross-platform, non-blocking sound playback for ``sound.play`` and the sound library preview.

No third-party dependency:

* **Windows** -- the built-in ``winmm`` MCI API through :mod:`ctypes` (mp3 / wav / wma / mid ...). One MCI
  alias per playback, so sounds overlap; volume is 0-100; a small reaper thread closes the alias once the
  sound ends.
* **macOS** -- ``afplay`` (volume ``-v 0..1``).
* **Linux** -- the first available of ``paplay`` / ``aplay`` / ``mpv`` / ``ffplay``.

``play`` returns immediately. Playbacks may overlap; ``mode="toggle"`` stops the key's running sound
instead of starting another one, ``mode="restart"`` stops it and starts again. Setting the environment
variable ``OPEN_LOUPEDECK_SOUND_BACKEND=null`` selects a backend that only records what would be played
(tests, headless machines).
"""

from __future__ import annotations

import itertools
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

MODES = ("play", "toggle", "restart")
# Extensions Windows MCI can decode out of the box (ogg / flac / opus need a codec pack).
WINDOWS_EXTENSIONS = frozenset({".mp3", ".wav", ".wma", ".mid", ".midi", ".aac", ".m4a", ".mp4"})
_POLL_SECONDS = 0.15


def clamp_volume(value: Any) -> int:
    """Volume as an int 0-100 (default 100 for empty / invalid values)."""

    try:
        v = round(float(value))
    except (TypeError, ValueError):
        return 100
    return max(0, min(100, v))


def normalize_mode(value: Any) -> str:
    mode = str(value or "play").strip().lower()
    if mode not in MODES:
        raise ValueError(f"sound.play mode must be one of {', '.join(MODES)}")
    return mode


# --------------------------------------------------------------------------------------------- backends


class Playback(Protocol):
    def is_running(self) -> bool: ...

    def stop(self) -> None: ...


class Backend(Protocol):
    name: str

    def start(self, path: str, volume: int) -> Playback: ...


def build_player_command(name: str, exe: str, path: str, volume: int) -> list[str]:
    """Command line for an external player (``name`` is its bare program name)."""

    if name == "mpv":
        return [exe, "--no-video", "--really-quiet", f"--volume={volume}", path]
    if name == "ffplay":
        return [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", str(volume), path]
    if name == "afplay":
        return [exe, "-v", f"{volume / 100:.2f}", path]
    if name == "paplay":
        return [exe, f"--volume={int(volume / 100 * 65536)}", path]
    return [exe, path]  # aplay and unknown players: no volume control


def find_player(preferred: str = "auto", platform: str | None = None) -> tuple[str, str]:
    """``(bare name, executable)`` of the player to use; raises ``RuntimeError`` when none exists."""

    plat = platform or sys.platform
    pref = (preferred or "auto").strip()
    if pref and pref != "auto":
        return os.path.basename(pref), shutil.which(pref) or pref
    names = ["afplay"] if plat == "darwin" else []
    names += ["paplay", "aplay", "mpv", "ffplay"]
    for name in names:
        exe = shutil.which(name)
        if exe:
            return name, exe
    raise RuntimeError("No supported audio player found (afplay, paplay, aplay, mpv, ffplay).")


class _ProcessPlayback:
    def __init__(self, proc: Any) -> None:
        self.proc = proc

    def is_running(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                logger.debug("terminate failed", exc_info=True)


class ProcessBackend:
    """Spawns an external player process per playback."""

    name = "process"

    def __init__(self, preferred: str = "auto", platform: str | None = None) -> None:
        self.preferred = preferred
        self.platform = platform

    def start(self, path: str, volume: int) -> Playback:
        name, exe = find_player(self.preferred, self.platform)
        cmd = build_player_command(name, exe, path, volume)
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return _ProcessPlayback(proc)


class MciError(RuntimeError):
    pass


def _default_mci_send() -> Callable[[str], str]:
    """``mciSendStringW`` wrapper: returns the reply text, raises :class:`MciError` on failure."""

    import ctypes

    winmm = ctypes.windll.winmm  # type: ignore[attr-defined]

    def send(command: str) -> str:
        buf = ctypes.create_unicode_buffer(256)
        err = winmm.mciSendStringW(command, buf, 255, 0)
        if err:
            msg = ctypes.create_unicode_buffer(256)
            winmm.mciGetErrorStringW(err, msg, 255)
            raise MciError(f"{msg.value or 'MCI error'} ({err}) for: {command}")
        return buf.value

    return send


class _MciPlayback:
    def __init__(self, backend: WindowsMciBackend, alias: str) -> None:
        self.backend = backend
        self.alias = alias
        self.closed = False

    def is_running(self) -> bool:
        if self.closed:
            return False
        return self.backend.status(self.alias) in ("playing", "paused")

    def stop(self) -> None:
        self.backend.close(self.alias)
        self.closed = True


class WindowsMciBackend:
    """winmm MCI: ``open`` -> ``setaudio volume`` -> ``play`` (async); a reaper closes finished aliases."""

    name = "winmm"

    def __init__(self, send: Callable[[str], str] | None = None, poll_seconds: float = _POLL_SECONDS) -> None:
        self._send_fn = send
        self._counter = itertools.count(1)
        self._lock = threading.RLock()
        self._live: dict[str, _MciPlayback] = {}
        self._reaper: threading.Thread | None = None
        self._poll = poll_seconds

    def _send(self, command: str) -> str:
        with self._lock:
            if self._send_fn is None:
                self._send_fn = _default_mci_send()
            return self._send_fn(command)

    @staticmethod
    def _device_type(path: str) -> str:
        return "waveaudio" if path.lower().endswith(".wav") else "mpegvideo"

    def start(self, path: str, volume: int) -> Playback:
        alias = f"olsnd{next(self._counter)}"
        quoted = path.replace('"', "")
        self._send(f'open "{quoted}" type {self._device_type(path)} alias {alias}')
        try:
            self._send(f"setaudio {alias} volume to {volume * 10}")
        except MciError:
            logger.debug("setaudio not supported for %s", path)  # plays at full volume
        try:
            self._send(f"play {alias}")
        except MciError:
            self.close(alias)
            raise
        pb = _MciPlayback(self, alias)
        with self._lock:
            self._live[alias] = pb
        self._ensure_reaper()
        return pb

    def status(self, alias: str) -> str:
        try:
            return self._send(f"status {alias} mode").strip().lower()
        except MciError:
            return "stopped"

    def close(self, alias: str) -> None:
        for cmd in (f"stop {alias}", f"close {alias}"):
            try:
                self._send(cmd)
            except MciError:
                logger.debug("MCI %s failed", cmd, exc_info=True)
        with self._lock:
            pb = self._live.pop(alias, None)
        if pb is not None:
            pb.closed = True

    def _ensure_reaper(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return
        self._reaper = threading.Thread(target=self._reap_loop, name="mci-reaper", daemon=True)
        self._reaper.start()

    def reap_once(self) -> int:
        """Close the aliases whose sound has ended; returns how many are still live."""

        with self._lock:
            items = list(self._live.items())
        for alias, pb in items:
            if not pb.is_running():
                self.close(alias)
        with self._lock:
            return len(self._live)

    def _reap_loop(self) -> None:
        while True:
            time.sleep(self._poll)
            if not self.reap_once():
                return


class NullBackend:
    """Records playbacks instead of making noise (tests / ``OPEN_LOUPEDECK_SOUND_BACKEND=null``)."""

    name = "null"

    class _Pb:
        def __init__(self, path: str, volume: int) -> None:
            self.path, self.volume, self.running = path, volume, True

        def is_running(self) -> bool:
            return self.running

        def stop(self) -> None:
            self.running = False

    def __init__(self) -> None:
        self.started: list[NullBackend._Pb] = []

    def start(self, path: str, volume: int) -> Playback:
        pb = NullBackend._Pb(path, volume)
        self.started.append(pb)
        return pb


def default_backend() -> Backend:
    if os.environ.get("OPEN_LOUPEDECK_SOUND_BACKEND", "").strip().lower() == "null":
        return NullBackend()
    if sys.platform == "win32":
        return WindowsMciBackend()
    return ProcessBackend()


# ------------------------------------------------------------------------------------------- the player


class SoundPlayer:
    """Tracks running playbacks per key so toggle / restart / stop-all work."""

    def __init__(self, backend: Backend | None = None) -> None:
        self._backend = backend
        self._lock = threading.Lock()
        self._active: list[tuple[str, Playback]] = []

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            self._backend = default_backend()
        return self._backend

    def _prune(self) -> None:
        self._active = [(k, p) for k, p in self._active if p.is_running()]

    def _stop_key(self, key: str) -> bool:
        stopped = False
        keep: list[tuple[str, Playback]] = []
        for k, p in self._active:
            if k == key:
                p.stop()
                stopped = True
            else:
                keep.append((k, p))
        self._active = keep
        return stopped

    def play(
        self,
        path: str,
        volume: Any = 100,
        mode: str = "play",
        key: str | None = None,
        player: str = "auto",
    ) -> str:
        """Start a sound; returns ``"started"`` or ``"stopped"`` (toggle pressed on a playing key)."""

        mode = normalize_mode(mode)
        vol = clamp_volume(volume)
        backend = self.backend
        if player and player != "auto" and not isinstance(backend, NullBackend):
            backend = ProcessBackend(player)  # the legacy ``player`` param always means "run that program"
        key = key or path
        with self._lock:
            self._prune()
            if mode in ("toggle", "restart"):
                was_playing = self._stop_key(key)
                if was_playing and mode == "toggle":
                    return "stopped"
            pb = backend.start(path, vol)
            self._active.append((key, pb))
        return "started"

    def stop_all(self) -> int:
        with self._lock:
            n = len(self._active)
            for _, p in self._active:
                p.stop()
            self._active = []
        return n

    def active_count(self) -> int:
        with self._lock:
            self._prune()
            return len(self._active)


_player: SoundPlayer | None = None
_player_lock = threading.Lock()


def get_player() -> SoundPlayer:
    global _player
    with _player_lock:
        if _player is None:
            _player = SoundPlayer()
        return _player


def set_player(player: SoundPlayer | None) -> None:
    """Replace the shared player (tests)."""

    global _player
    with _player_lock:
        _player = player
