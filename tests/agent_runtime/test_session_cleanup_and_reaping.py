"""Functional regression: host-pane processes are reaped before per-session tmpdir removal.

`terminate_session` used to remove the per-session TMPDIR immediately after
`kill_session` returned, racing a still-exiting Node process that flushes its
compile cache from an exit-time hook. These tests drive the real
`terminate_session` boundary against a real filesystem tree and a real
`shutil.rmtree`; only the process boundary is faked, via a background thread
that writes into the tmpdir's node-compile-cache directory on its own
schedule, independent of any liveness poll.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from teleclaude.core import session_cleanup, session_listeners, tmux_bridge
from teleclaude.core.db import Db

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-cleanup-and-reaping"
_CACHE_SUBPATH = ("node-compile-cache", "v24.18.0-arm64-cf738c9d-502")


_BURST_ENTRY_COUNT = 3000


class _FakePaneProcess:
    """Fake pane process backed by a real thread writing into a cache dir.

    No writes happen until ``request_exit`` — mirroring Node's exit-time
    compile-cache flush, where zero cache files exist while the process
    runs. ``request_exit`` then triggers a rapid, uninterrupted burst of
    ``_BURST_ENTRY_COUNT`` writes before ``wait_burst_done`` unblocks.

    The burst exists because a single confirmed write is not enough to
    reliably expose the reap-before-remove regression: `shutil.rmtree`
    takes one `scandir` snapshot and only fails if a *new* entry appears
    before its matching `rmdir`. With only a handful of pre-existing
    files, unlinking them can complete in under a millisecond on a fast
    filesystem — faster than this thread's write cadence — letting rmtree
    finish before the next write lands, even with the reap wait removed.
    Pre-populating thousands of entries makes rmtree's own unlink pass
    take measurably longer than one write cycle, so the continuing writer
    (see below) reliably lands at least one more write inside that widened
    window regardless of scheduling luck.

    After the burst, the thread keeps writing continuously on its own
    schedule for ``flush_seconds`` before reporting dead, unless
    ``never_exits`` is set, in which case it keeps writing past that
    window and never reports dead.
    """

    def __init__(self, cache_dir: Path, *, flush_seconds: float, never_exits: bool = False) -> None:
        self.pid = 4242
        self._cache_dir = cache_dir
        self._flush_seconds = flush_seconds
        self._never_exits = never_exits
        self._exit_requested = threading.Event()
        self._terminate = threading.Event()
        self._burst_done = threading.Event()
        self._dead = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        self._exit_requested.wait()
        if self._terminate.is_set():
            return
        counter = 0
        for _ in range(_BURST_ENTRY_COUNT):
            (self._cache_dir / f"entry-{counter}").write_bytes(b"x")
            counter += 1
        self._burst_done.set()
        deadline = time.monotonic() + self._flush_seconds
        while self._never_exits or time.monotonic() < deadline:
            if self._terminate.is_set():
                return
            (self._cache_dir / f"entry-{counter}").write_bytes(b"x")
            counter += 1
            time.sleep(0.002)
        self._dead.set()

    def request_exit(self) -> None:
        self._exit_requested.set()

    def wait_burst_done(self, timeout: float) -> bool:
        return self._burst_done.wait(timeout)

    def wait_dead(self, timeout: float) -> bool:
        return self._dead.wait(timeout)

    def shutdown(self) -> None:
        self._terminate.set()
        self._exit_requested.set()
        self._thread.join(timeout=2.0)


async def _make_test_db(monkeypatch: pytest.MonkeyPatch) -> Db:
    test_db = Db(":memory:")
    await test_db.initialize()
    monkeypatch.setattr(session_cleanup, "db", test_db)
    monkeypatch.setattr(session_listeners, "db", test_db)
    return test_db


def _install_fake_pane(monkeypatch: pytest.MonkeyPatch, writer: _FakePaneProcess) -> None:
    async def fake_get_pane_process_tree(session_name: str) -> list[Any]:
        del session_name
        return [writer]

    async def fake_kill_session(session_name: str) -> bool:
        del session_name
        writer.request_exit()
        # Block until the writer's pre-populate burst has landed on disk —
        # otherwise the "no wait" mutation races a mostly-empty directory,
        # and a fast filesystem can finish rmtree before the next write
        # lands regardless of scheduling luck. See _FakePaneProcess.
        await asyncio.to_thread(writer.wait_burst_done, 5.0)
        return True

    async def fake_wait_for_processes_exit(procs: list[Any], timeout: float) -> list[Any]:
        exited = writer.wait_dead(timeout)
        return [] if exited else list(procs)

    monkeypatch.setattr(tmux_bridge, "get_pane_process_tree", fake_get_pane_process_tree)
    monkeypatch.setattr(tmux_bridge, "kill_session", fake_kill_session)
    monkeypatch.setattr(tmux_bridge, "wait_for_processes_exit", fake_wait_for_processes_exit)


@pytest.mark.spec(_SPEC, "UC-SCR-1")
async def test_reap_before_remove_lets_tmpdir_cleanup_succeed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cluster_event_bus: None,
) -> None:
    """The exiting pane's compile-cache writer finishes before rmtree runs."""
    del cluster_event_bus
    session_id = "8f7f3c1a-1111-4000-8000-000000000002"
    test_db = await _make_test_db(monkeypatch)
    monkeypatch.setattr(tmux_bridge, "get_session_tmpdir_base", lambda: tmp_path)

    session_tmpdir = tmp_path / session_id
    cache_dir = session_tmpdir.joinpath(*_CACHE_SUBPATH)
    cache_dir.mkdir(parents=True)

    writer = _FakePaneProcess(cache_dir, flush_seconds=0.2)
    _install_fake_pane(monkeypatch, writer)

    await test_db.create_session(
        computer_name="local",
        tmux_session_name="tc_test-reap",
        last_input_origin="cli",
        title="test",
        session_id=session_id,
        emit_session_started=False,
    )
    adapter_client = SimpleNamespace(delete_channel=AsyncMock(return_value=None))

    try:
        result = await session_cleanup.terminate_session(session_id, adapter_client, reason="test")
    finally:
        writer.shutdown()

    assert result is True
    assert not session_tmpdir.exists()


@pytest.mark.spec(_SPEC, "UC-SCR-2")
async def test_bounded_reap_still_completes_when_process_outlives_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cluster_event_bus: None,
) -> None:
    """A pane process that never exits does not strand the closing lifecycle write."""
    del cluster_event_bus
    session_id = "8f7f3c1a-2222-4000-8000-000000000003"
    test_db = await _make_test_db(monkeypatch)
    monkeypatch.setattr(tmux_bridge, "get_session_tmpdir_base", lambda: tmp_path)
    monkeypatch.setattr(session_cleanup, "SESSION_PROCESS_REAP_TIMEOUT", 0.2)

    session_tmpdir = tmp_path / session_id
    cache_dir = session_tmpdir.joinpath(*_CACHE_SUBPATH)
    cache_dir.mkdir(parents=True)

    writer = _FakePaneProcess(cache_dir, flush_seconds=0.05, never_exits=True)
    _install_fake_pane(monkeypatch, writer)

    await test_db.create_session(
        computer_name="local",
        tmux_session_name="tc_test-bounded",
        last_input_origin="cli",
        title="test",
        session_id=session_id,
        emit_session_started=False,
    )
    adapter_client = SimpleNamespace(delete_channel=AsyncMock(return_value=None))

    try:
        result = await session_cleanup.terminate_session(session_id, adapter_client, reason="test")
    finally:
        writer.shutdown()

    assert result is True
    closed = await test_db.get_session(session_id)
    assert closed is not None
    assert closed.closed_at is not None
