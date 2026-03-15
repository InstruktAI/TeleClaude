"""Characterization tests for teleclaude.daemon."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import teleclaude.daemon as daemon


class NetworkError(Exception):
    """Synthetic exception with a retryable type name."""


def _make_lock_only_daemon(pid_file):
    daemon_instance = daemon.TeleClaudeDaemon.__new__(daemon.TeleClaudeDaemon)
    daemon_instance.pid_file = pid_file
    daemon_instance.pid_file_handle = None
    return daemon_instance


def test_is_retryable_startup_error_recognizes_type_name_and_message() -> None:
    assert daemon._is_retryable_startup_error(NetworkError("dns failed")) is True
    assert daemon._is_retryable_startup_error(RuntimeError("Temporary failure in name resolution")) is True
    assert daemon._is_retryable_startup_error(ValueError("bad credentials")) is False


def test_acquire_and_release_lock_writes_pid_and_cleans_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registered: list[object] = []
    daemon_instance = _make_lock_only_daemon(tmp_path / "teleclaude.pid")
    monkeypatch.setattr(daemon.atexit, "register", registered.append)

    daemon_instance._acquire_lock()

    assert daemon_instance.pid_file.read_text(encoding="utf-8") == str(os.getpid())
    assert daemon_instance.pid_file_handle is not None
    assert registered == [daemon_instance._release_lock]

    daemon_instance._release_lock()

    assert daemon_instance.pid_file_handle is None
    assert not daemon_instance.pid_file.exists()


def test_acquire_lock_raises_when_another_handle_already_holds_it(tmp_path: Path) -> None:
    pid_file = tmp_path / "teleclaude.pid"
    first = _make_lock_only_daemon(pid_file)
    second = _make_lock_only_daemon(pid_file)
    first._acquire_lock()

    try:
        with pytest.raises(daemon.DaemonLockError, match="already running"):
            second._acquire_lock()
    finally:
        first._release_lock()
