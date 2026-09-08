from __future__ import annotations

import asyncio

import pytest

from open_loupedeck.obs_client import ObsSession


class _FakeResult:
    def __init__(self, ok: bool, data: dict | None = None) -> None:
        self._ok = ok
        self.responseData = data or {}
        self.requestStatus = None
        self.comment = ""

    def ok(self) -> bool:
        return self._ok


class _FakeWs:
    def __init__(self, *, fail_calls: bool = False, result: _FakeResult | None = None) -> None:
        self.fail_calls = fail_calls
        self.result = result or _FakeResult(True)
        self.disconnected = False

    async def call(self, _req):
        if self.fail_calls:
            raise ConnectionError("socket closed")
        return self.result

    async def disconnect(self) -> None:
        self.disconnected = True


def _run(coro):
    return asyncio.run(coro)


def test_update_credentials_closes_existing_session_when_changed():
    session = ObsSession("127.0.0.1", 4455, "old-pw")
    fake = _FakeWs()
    session._ws = fake

    changed = _run(session.update_credentials("127.0.0.1", 4455, "new-pw"))

    assert changed is True
    assert fake.disconnected is True
    assert session._ws is None
    assert session._password == "new-pw"


def test_update_credentials_keeps_session_when_unchanged():
    session = ObsSession("127.0.0.1", 4455, "pw")
    fake = _FakeWs()
    session._ws = fake

    changed = _run(session.update_credentials("127.0.0.1", 4455, "pw"))

    assert changed is False
    assert fake.disconnected is False
    assert session._ws is fake


def test_probe_returns_true_and_keeps_session_when_live():
    session = ObsSession("127.0.0.1", 4455, "pw")
    fake = _FakeWs(result=_FakeResult(True, {"obsVersion": "30.0.0"}))
    session._ws = fake

    assert _run(session.probe(timeout=1.0)) is True
    assert session._ws is fake


def test_probe_drops_stale_session_and_returns_false_when_dead():
    # Port 1 is not something a test OBS instance would ever be listening on, so the reconnect
    # attempt this triggers fails fast instead of actually finding a server.
    session = ObsSession("127.0.0.1", 1, "pw")
    fake = _FakeWs(fail_calls=True)
    session._ws = fake

    assert _run(session.probe(timeout=1.0)) is False
    assert fake.disconnected is True
    assert session._ws is None


def test_call_drops_dead_session_on_exception():
    session = ObsSession("127.0.0.1", 4455, "pw")
    fake = _FakeWs(fail_calls=True)
    session._ws = fake

    with pytest.raises(ConnectionError):
        _run(session.call("SetCurrentProgramScene", {"sceneName": "x"}))

    assert fake.disconnected is True
    assert session._ws is None
