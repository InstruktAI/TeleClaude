"""Functional regression tests for the chiptunes worker registry.

The worker registry (pidfile + control socket) used to live under ``/tmp``, which
macOS purges after ~3 days untouched — deleting the registry out from under a
live worker, leaking a duplicate on the next daemon restart while the orphan kept
playing with no control path. These tests pin the relocated registry, the
scan-backed adopt-or-kill dedup, and the worker idle lease at the manager/worker
process boundary, where the defect is observable without waiting on a real purge.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.chiptunes import manager as manager_mod
from teleclaude.chiptunes import worker as worker_mod
from teleclaude.chiptunes.manager import ChiptunesManager
from teleclaude.chiptunes.worker import _IDLE_LEASE_SECONDS, _WorkerProcess
from teleclaude.paths import CHIPTUNES_PID_PATH, CHIPTUNES_SOCKET_PATH, TELECLAUDE_HOME

pytestmark = pytest.mark.functional

_SPEC = "docs/project/spec/feature/agent_runtime/daemon-lifecycle.md"


class _FakeProc:
    """Stand-in for a ``psutil.Process`` row yielded by ``process_iter``."""

    def __init__(self, pid: int, cmdline: list[str], uid: int) -> None:
        self.info: dict[str, object] = {"pid": pid, "cmdline": cmdline}
        self._uid = uid

    def uids(self) -> SimpleNamespace:
        return SimpleNamespace(real=self._uid, effective=self._uid, saved=self._uid)


@pytest.mark.spec(_SPEC, "UC-CW1")
def test_registry_resolves_under_home_root_not_tmp() -> None:
    """The socket and pidfile live flat at the never-purged home root, not /tmp."""
    for registry_path in (CHIPTUNES_SOCKET_PATH, CHIPTUNES_PID_PATH):
        assert registry_path.parent == TELECLAUDE_HOME
        assert Path("/tmp") not in registry_path.parents
    # Both processes resolve the same relocated constants — no /tmp literal survives.
    assert manager_mod.CHIPTUNES_SOCKET_PATH == CHIPTUNES_SOCKET_PATH
    assert manager_mod.CHIPTUNES_PID_PATH == CHIPTUNES_PID_PATH
    assert worker_mod.CHIPTUNES_SOCKET_PATH == CHIPTUNES_SOCKET_PATH
    assert worker_mod.CHIPTUNES_PID_PATH == CHIPTUNES_PID_PATH


@pytest.mark.spec(_SPEC, "UC-CW2")
def test_scan_matches_only_exact_same_user_worker_invocation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Liveness comes from the process table: only this user's exact -m invocation counts."""
    own_uid = os.getuid()
    procs = [
        _FakeProc(101, [sys.executable, "-m", "teleclaude.chiptunes.worker", "--music-dir", "/x"], own_uid),
        _FakeProc(202, ["python", "run.py", "teleclaude.chiptunes.worker"], own_uid),
        _FakeProc(303, [sys.executable, "-m", "teleclaude.chiptunes.worker"], own_uid + 1),
    ]
    monkeypatch.setattr(manager_mod.psutil, "process_iter", lambda _attrs=None: iter(procs))
    manager = ChiptunesManager(tmp_path)
    # 202 merely mentions the module string; 303 is another user — neither is a worker.
    assert manager._find_live_workers() == [101]


@pytest.mark.spec(_SPEC, "UC-CW3")
def test_reachable_worker_is_adopted_without_spawning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A live worker with a reachable socket is adopted — no duplicate is spawned."""
    manager = ChiptunesManager(tmp_path)
    monkeypatch.setattr(manager, "_find_live_workers", lambda: [4242])
    monkeypatch.setattr(manager, "_worker_socket_reachable", lambda: True)
    events: list[object] = []
    monkeypatch.setattr(manager, "_terminate_workers", lambda pids: events.append(("terminate", list(pids))))
    monkeypatch.setattr(manager, "_spawn_worker", lambda: events.append(("spawn",)))
    manager._ensure_worker()
    assert events == []


@pytest.mark.spec(_SPEC, "UC-CW4")
def test_unreachable_orphan_is_terminated_before_single_spawn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A live-but-unreachable worker (purged socket) is killed before exactly one replacement."""
    manager = ChiptunesManager(tmp_path)
    monkeypatch.setattr(manager, "_find_live_workers", lambda: [4242])
    monkeypatch.setattr(manager, "_worker_socket_reachable", lambda: False)
    events: list[object] = []
    monkeypatch.setattr(manager, "_terminate_workers", lambda pids: events.append(("terminate", list(pids))))
    monkeypatch.setattr(manager, "_clear_registry", lambda: events.append(("clear",)))
    monkeypatch.setattr(manager, "_spawn_worker", lambda: events.append(("spawn",)))
    monkeypatch.setattr(manager, "_await_socket", lambda: None)
    manager._ensure_worker()
    assert events == [("terminate", [4242]), ("clear",), ("spawn",)]


@pytest.mark.spec(_SPEC, "UC-CW5")
def test_reattach_reconnects_to_reachable_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reattach to a reachable worker reconnects and pulls a state snapshot."""
    manager = ChiptunesManager(tmp_path)
    monkeypatch.setattr(manager, "_find_live_workers", lambda: [4242])
    monkeypatch.setattr(manager, "_worker_socket_reachable", lambda: True)
    events: list[object] = []
    monkeypatch.setattr(manager, "_connect", lambda: events.append("connect"))
    monkeypatch.setattr(manager, "_send_cmd", lambda cmd: events.append(("send", cmd.get("cmd"))))
    monkeypatch.setattr(manager, "_terminate_workers", lambda _pids: events.append("terminate"))
    manager.reattach()
    assert "terminate" not in events
    assert events == ["connect", ("send", "capture_state")]
    assert manager.enabled is True


@pytest.mark.spec(_SPEC, "UC-CW6")
def test_reattach_terminates_unreachable_orphan_without_reconnecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reattach never reconnects to a purged socket — it terminates the orphan instead."""
    manager = ChiptunesManager(tmp_path)
    monkeypatch.setattr(manager, "_find_live_workers", lambda: [4242])
    monkeypatch.setattr(manager, "_worker_socket_reachable", lambda: False)
    events: list[object] = []
    monkeypatch.setattr(manager, "_connect", lambda: events.append("connect"))
    monkeypatch.setattr(manager, "_terminate_workers", lambda pids: events.append(("terminate", list(pids))))
    monkeypatch.setattr(manager, "_clear_registry", lambda: events.append(("clear",)))
    manager.reattach()
    assert "connect" not in events
    assert events == [("terminate", [4242]), ("clear",)]


@pytest.mark.spec(_SPEC, "UC-CW7")
def test_worker_requests_stop_after_idle_lease_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """With no client connected past the idle window, the worker requests a clean stop."""
    worker = _WorkerProcess(tmp_path, 1.0)
    worker._last_client_activity = 1000.0
    monkeypatch.setattr(worker, "_now", lambda: 1000.0 + _IDLE_LEASE_SECONDS + 1.0)
    worker._check_idle_lease()
    assert worker._running is False


@pytest.mark.spec(_SPEC, "UC-CW8")
def test_worker_keeps_running_within_idle_lease_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Within the idle window the worker keeps running — restart gaps are tolerated."""
    worker = _WorkerProcess(tmp_path, 1.0)
    worker._last_client_activity = 1000.0
    monkeypatch.setattr(worker, "_now", lambda: 1000.0 + _IDLE_LEASE_SECONDS - 1.0)
    worker._check_idle_lease()
    assert worker._running is True
