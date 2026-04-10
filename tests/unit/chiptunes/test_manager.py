"""Tests for teleclaude.chiptunes.manager — subprocess IPC client."""

from __future__ import annotations

import json
import os
import socket
import threading
from collections.abc import Generator, Mapping
from pathlib import Path

import pytest

import teleclaude.chiptunes.manager as manager_module
from teleclaude.chiptunes.manager import ChiptunesManager
from teleclaude.chiptunes.types import ChiptunesState


class _FakeWorkerServer:
    """Minimal Unix socket server simulating the chiptunes worker subprocess."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._server: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._received: list[Mapping[str, object]] = []
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self._socket_path)
        self._server.listen(1)
        self._server.settimeout(2.0)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        assert self._server is not None
        while self._running:
            try:
                conn, _ = self._server.accept()
                self._conn = conn
                self._read_loop(conn)
            except TimeoutError:
                continue
            except OSError:
                break

    def _read_loop(self, conn: socket.socket) -> None:
        buf = b""
        try:
            while self._running:
                conn.settimeout(0.5)
                try:
                    data = conn.recv(4096)
                except TimeoutError:
                    continue
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._received.append(json.loads(line.decode()))
        except OSError:
            pass

    def send_event(self, event: Mapping[str, object]) -> None:
        if self._conn is not None:
            self._conn.sendall((json.dumps(event) + "\n").encode())

    @property
    def received(self) -> list[Mapping[str, object]]:
        return self._received

    def stop(self) -> None:
        self._running = False
        if self._conn:
            try:
                self._conn.close()
            except OSError:
                pass
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)


@pytest.fixture()
def fake_worker() -> Generator[_FakeWorkerServer]:
    # Use /tmp to stay within macOS AF_UNIX path length limit (104 bytes)
    import tempfile  # pylint: disable=import-outside-toplevel

    fd, sock_path = tempfile.mkstemp(prefix="tc_ct_", suffix=".sock", dir="/tmp")
    os.close(fd)
    os.unlink(sock_path)
    server = _FakeWorkerServer(sock_path)
    server.start()
    yield server
    server.stop()


def _make_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    socket_path: str,
    pid_path: str | None = None,
) -> ChiptunesManager:
    """Create a manager patched to use a custom socket/pid path."""
    monkeypatch.setattr(manager_module, "SOCKET_PATH", socket_path)
    if pid_path is None:
        pid_path = str(tmp_path / "chiptunes.pid")
    monkeypatch.setattr(manager_module, "PID_PATH", pid_path)
    return ChiptunesManager(tmp_path / "music", volume=0.25)


@pytest.mark.unit
class TestChiptunesManagerIPC:
    def test_send_cmd_delivers_json_to_socket(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_worker: _FakeWorkerServer,
    ) -> None:
        sock_path = fake_worker._socket_path
        manager = _make_manager(monkeypatch, tmp_path, sock_path)
        manager._connect()

        manager._send_cmd({"cmd": "pause"})
        threading.Event().wait(0.2)

        assert any(msg.get("cmd") == "pause" for msg in fake_worker.received)
        manager._disconnect()

    def test_handle_track_start_event_updates_last_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_worker: _FakeWorkerServer,
    ) -> None:
        sock_path = fake_worker._socket_path
        manager = _make_manager(monkeypatch, tmp_path, sock_path)
        started: list[tuple[str, str]] = []
        manager.on_track_start = lambda label, path: started.append((label, path))

        manager._connect()
        threading.Event().wait(0.2)

        fake_worker.send_event(
            {
                "event": "track_start",
                "track": "Lazy Jones",
                "sid_path": "/music/Lazy_Jones.sid",
            }
        )
        threading.Event().wait(0.3)

        assert manager._last_state.get("track_path") == "/music/Lazy_Jones.sid"
        assert manager._last_state.get("playback") == "playing"
        assert started == [("Lazy Jones", "/music/Lazy_Jones.sid")]
        manager._disconnect()

    def test_handle_state_update_event_applies_full_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_worker: _FakeWorkerServer,
    ) -> None:
        sock_path = fake_worker._socket_path
        manager = _make_manager(monkeypatch, tmp_path, sock_path)
        changes: list[ChiptunesState] = []
        manager.on_state_change = changes.append

        manager._connect()
        threading.Event().wait(0.2)

        fake_worker.send_event(
            {
                "event": "state_update",
                "state": {
                    "playback": "paused",
                    "track_path": "/music/Delta.sid",
                    "position_seconds": 12.5,
                    "history": ["/music/Delta.sid"],
                    "history_index": 0,
                },
            }
        )
        threading.Event().wait(0.3)

        assert manager._last_state.get("playback") == "paused"
        assert manager._last_state.get("track_path") == "/music/Delta.sid"
        assert manager._last_state.get("position_seconds") == 12.5
        assert changes
        manager._disconnect()

    def test_disconnect_does_not_kill_worker(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_worker: _FakeWorkerServer,
    ) -> None:
        sock_path = fake_worker._socket_path
        pid_path = str(tmp_path / "chiptunes.pid")
        Path(pid_path).write_text(str(os.getpid()), encoding="utf-8")

        manager = _make_manager(monkeypatch, tmp_path, sock_path, pid_path=pid_path)
        manager._connect()
        threading.Event().wait(0.1)

        manager.shutdown()

        assert manager._sock is None
        assert ChiptunesManager._worker_alive()
        manager._disconnect()

    def test_reader_disconnect_resets_playback_to_cold(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_worker: _FakeWorkerServer,
    ) -> None:
        sock_path = fake_worker._socket_path
        manager = _make_manager(monkeypatch, tmp_path, sock_path)
        changes: list[ChiptunesState] = []
        manager.on_state_change = changes.append

        manager._connect()
        threading.Event().wait(0.1)

        # Set state to playing via a track_start event
        fake_worker.send_event(
            {
                "event": "track_start",
                "track": "Test Track",
                "sid_path": "/music/Test.sid",
            }
        )
        threading.Event().wait(0.1)
        assert manager._last_state.get("playback") == "playing"
        changes.clear()

        # Kill the fake worker connection — reader thread should detect and clean up
        fake_worker.stop()
        threading.Event().wait(0.3)

        assert manager._last_state.get("playback") == "cold"
        assert manager._sock is None
        # Track path preserved for recovery
        assert manager._last_state.get("track_path") == "/music/Test.sid"
        assert changes, "on_state_change should have been called"

    def test_enqueue_command_reconnects_when_socket_is_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        fake_worker: _FakeWorkerServer,
    ) -> None:
        sock_path = fake_worker._socket_path
        manager = _make_manager(monkeypatch, tmp_path, sock_path)
        # Ensure _sock is None (default)
        assert manager._sock is None

        # Mock _ensure_worker to avoid subprocess spawning
        monkeypatch.setattr(manager, "_ensure_worker", lambda: None)

        manager.enqueue_command("cmd-abc", "next")
        threading.Event().wait(0.2)

        assert manager._sock is not None
        assert any(msg.get("cmd") == "next" and msg.get("command_id") == "cmd-abc" for msg in fake_worker.received)
        manager._disconnect()


@pytest.mark.unit
class TestChiptunesManagerProperties:
    def test_last_state_returns_empty_by_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        manager = _make_manager(monkeypatch, tmp_path, "/nonexistent")
        assert manager.last_state == {}

    def test_enabled_reflects_internal_flag(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        manager = _make_manager(monkeypatch, tmp_path, "/nonexistent")
        assert manager.enabled is False
        manager._enabled = True
        assert manager.enabled is True


@pytest.mark.unit
class TestWorkerAlive:
    def test_worker_alive_returns_true_for_own_pid(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        pid_path = str(tmp_path / "chiptunes.pid")
        Path(pid_path).write_text(str(os.getpid()), encoding="utf-8")
        monkeypatch.setattr(manager_module, "PID_PATH", pid_path)
        assert ChiptunesManager._worker_alive() is True

    def test_worker_alive_returns_false_for_missing_pid(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(manager_module, "PID_PATH", str(tmp_path / "nope.pid"))
        assert ChiptunesManager._worker_alive() is False
