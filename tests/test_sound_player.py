"""sound_player: command construction, MCI call sequence / alias lifecycle, play modes (OS layer mocked)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from open_loupedeck import sound_player as sp
from open_loupedeck.actions.builtins import SoundPlay, SoundStopAll
from open_loupedeck.actions.registry import ActionContext


def test_clamp_volume_and_mode() -> None:
    assert sp.clamp_volume(None) == 100
    assert sp.clamp_volume("abc") == 100
    assert sp.clamp_volume(-5) == 0
    assert sp.clamp_volume(250) == 100
    assert sp.clamp_volume("42.4") == 42
    assert sp.normalize_mode(None) == "play"
    assert sp.normalize_mode(" Toggle ") == "toggle"
    with pytest.raises(ValueError):
        sp.normalize_mode("loop")


def test_build_player_command() -> None:
    assert sp.build_player_command("afplay", "/usr/bin/afplay", "a.mp3", 50) == [
        "/usr/bin/afplay",
        "-v",
        "0.50",
        "a.mp3",
    ]
    assert sp.build_player_command("paplay", "pa", "a.wav", 50) == ["pa", "--volume=32768", "a.wav"]
    assert sp.build_player_command("aplay", "ap", "a.wav", 10) == ["ap", "a.wav"]
    assert "--volume=30" in sp.build_player_command("mpv", "mpv", "a.mp3", 30)
    ff = sp.build_player_command("ffplay", "ff", "a.mp3", 30)
    assert ff[-3:] == ["-volume", "30", "a.mp3"] and "-nodisp" in ff


def test_find_player_order(monkeypatch: pytest.MonkeyPatch) -> None:
    present = {"aplay", "mpv", "afplay"}
    monkeypatch.setattr(sp.shutil, "which", lambda n: f"/bin/{n}" if n in present else None)
    assert sp.find_player("auto", "linux") == ("aplay", "/bin/aplay")  # paplay missing -> aplay before mpv
    assert sp.find_player("auto", "darwin")[0] == "afplay"
    assert sp.find_player("mpv") == ("mpv", "/bin/mpv")
    assert sp.find_player("/opt/custom/vlc") == ("vlc", "/opt/custom/vlc")  # not on PATH: used verbatim
    monkeypatch.setattr(sp.shutil, "which", lambda n: None)
    with pytest.raises(RuntimeError):
        sp.find_player("auto", "linux")


class FakeProc:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def test_process_backend_spawns_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    procs: list[FakeProc] = []

    def fake_popen(cmd: list[str], **kw: Any) -> FakeProc:
        calls.append(cmd)
        procs.append(FakeProc())
        return procs[-1]

    monkeypatch.setattr(sp.shutil, "which", lambda n: f"/bin/{n}" if n == "paplay" else None)
    monkeypatch.setattr(sp.subprocess, "Popen", fake_popen)
    player = sp.SoundPlayer(sp.ProcessBackend(platform="linux"))
    assert player.play("/x/a.wav", 50) == "started"
    assert calls == [["/bin/paplay", "--volume=32768", "/x/a.wav"]]
    assert player.active_count() == 1
    assert player.stop_all() == 1
    assert procs[0].terminated and player.active_count() == 0


def test_explicit_player_param_overrides_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sp.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(sp.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd) or FakeProc())
    player = sp.SoundPlayer(sp.WindowsMciBackend(send=lambda c: ""))
    player.play("C:/a.mp3", 100, player="mpv")
    assert calls and calls[0][0] == "/bin/mpv"


class FakeMci:
    """Records MCI commands; ``modes`` maps alias -> status reply."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.modes: dict[str, str] = {}
        self.fail_prefix: str | None = None

    def __call__(self, cmd: str) -> str:
        self.log.append(cmd)
        if self.fail_prefix and cmd.startswith(self.fail_prefix):
            raise sp.MciError("boom")
        parts = cmd.split()
        if parts[0] == "open":
            self.modes[parts[-1]] = "playing"
        if parts[0] == "status":
            return self.modes.get(parts[1], "") or (_ for _ in ()).throw(sp.MciError("closed"))
        if parts[0] == "close":
            self.modes.pop(parts[1], None)
        return ""


def test_mci_sequence_and_alias_lifecycle() -> None:
    mci = FakeMci()
    be = sp.WindowsMciBackend(send=mci, poll_seconds=3600)
    pb1 = be.start(r"C:\sounds\air horn.mp3", 40)
    pb2 = be.start(r"C:\sounds\clap.wav", 100)
    assert mci.log[:3] == [
        'open "C:\\sounds\\air horn.mp3" type mpegvideo alias olsnd1',
        "setaudio olsnd1 volume to 400",
        "play olsnd1",
    ]
    assert mci.log[3] == 'open "C:\\sounds\\clap.wav" type waveaudio alias olsnd2'  # one alias per playback
    assert pb1.is_running() and pb2.is_running()
    assert be.reap_once() == 2
    mci.modes["olsnd1"] = "stopped"  # sound 1 ended on its own
    assert be.reap_once() == 1
    assert "close olsnd1" in mci.log and "close olsnd2" not in mci.log
    assert not pb1.is_running()
    pb2.stop()
    assert mci.log[-2:] == ["stop olsnd2", "close olsnd2"]
    assert be.reap_once() == 0


def test_mci_play_failure_closes_alias() -> None:
    mci = FakeMci()
    mci.fail_prefix = "play "
    be = sp.WindowsMciBackend(send=mci, poll_seconds=3600)
    with pytest.raises(sp.MciError):
        be.start("C:/a.mp3", 100)
    assert "close olsnd1" in mci.log and be.reap_once() == 0


def test_mci_setaudio_failure_still_plays() -> None:
    mci = FakeMci()
    mci.fail_prefix = "setaudio"
    be = sp.WindowsMciBackend(send=mci, poll_seconds=3600)
    be.start("C:/a.wav", 30)
    assert any(c.startswith("play ") for c in mci.log)


def test_modes_play_toggle_restart() -> None:
    be = sp.NullBackend()
    player = sp.SoundPlayer(be)
    assert player.play("a.wav", 100, "play", "k1") == "started"
    assert player.play("a.wav", 100, "play", "k1") == "started"  # overlap allowed
    assert player.active_count() == 2
    assert player.play("a.wav", 100, "toggle", "k1") == "stopped"  # stops the key's sounds
    assert player.active_count() == 0
    assert player.play("a.wav", 100, "toggle", "k1") == "started"
    assert player.play("a.wav", 100, "restart", "k1") == "started"
    assert [p.running for p in be.started][-2:] == [False, True]
    assert player.play("b.wav", 100, "play", "k2") == "started"
    assert player.stop_all() == 2


def test_sound_play_action_and_stop_all(tmp_path: Path) -> None:
    be = sp.NullBackend()
    sp.set_player(sp.SoundPlayer(be))
    try:
        (tmp_path / "library" / "sounds").mkdir(parents=True)
        (tmp_path / "library" / "sounds" / "a.wav").write_bytes(b"x")
        ctx = ActionContext(obs=None, http_client=None, log=None, config_dir=tmp_path, source_storage_key="0:touch_1")  # type: ignore[arg-type]

        async def run() -> None:
            await SoundPlay().run(ctx, {"file": "library/sounds/a.wav", "volume": 30, "mode": "toggle"})
            assert sp.get_player().active_count() == 1
            await SoundPlay().run(ctx, {"file": "library/sounds/a.wav", "mode": "toggle"})  # pressed again
            assert sp.get_player().active_count() == 0
            await SoundPlay().run(ctx, {"file": "library/sounds/a.wav"})
            await SoundStopAll().run(ctx, {})
            assert sp.get_player().active_count() == 0
            with pytest.raises(FileNotFoundError):
                await SoundPlay().run(ctx, {"file": "library/sounds/missing.wav"})
            with pytest.raises(ValueError):
                await SoundPlay().run(ctx, {"file": "library/sounds/a.wav", "mode": "nope"})

        asyncio.run(run())
        assert be.started[0].volume == 30 and be.started[0].path.endswith("a.wav")
    finally:
        sp.set_player(None)


def test_mci_commands_all_run_on_one_worker_thread():
    """MCI devices are thread-affine: open/play/status/stop/close must share a single thread."""

    import threading

    seen: set[int] = set()

    def send(command: str) -> str:
        seen.add(threading.get_ident())
        return "playing" if command.startswith("status") else ""

    be = sp.WindowsMciBackend(send=send, poll_seconds=3600)
    player = sp.SoundPlayer(be)
    threads = [threading.Thread(target=player.play, args=("a.mp3", 100, "restart", f"k{i}")) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    player.stop_all()
    assert len(seen) == 1
    assert threading.get_ident() not in seen


def test_restart_stops_same_file_even_from_another_key():
    be = sp.NullBackend()
    player = sp.SoundPlayer(be)
    player.play("a.wav", 100, "play", "key-1")
    assert player.active_count() == 1
    player.play("a.wav", 100, "restart", "key-2")
    assert player.active_count() == 1
