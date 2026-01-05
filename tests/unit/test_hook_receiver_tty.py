"""Unit tests for robust TTY discovery in hook receiver."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.hooks.receiver import _get_parent_process_info


class _FakeProc:
    def __init__(self, pid: int, name: str, terminal: str | None, parent: "_FakeProc | None") -> None:
        self.pid = pid
        self._name = name
        self._terminal = terminal
        self._parent = parent

    def terminal(self) -> str | None:  # noqa: D401 - simple getter
        return self._terminal

    def name(self) -> str:
        return self._name

    def parent(self) -> "_FakeProc | None":
        return self._parent


def _install_fake_psutil(monkeypatch: pytest.MonkeyPatch, mapping: dict[int, _FakeProc]) -> None:
    def _process(pid: int) -> _FakeProc:
        return mapping[pid]

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=_process))


def _allow_fake_tty(monkeypatch: pytest.MonkeyPatch, tty_path: str) -> None:
    real_exists = Path.exists

    def _exists(self: Path) -> bool:
        if str(self) == tty_path:
            return True
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", _exists)


def test_prefers_shell_parent_with_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    tty_path = "/dev/ttys-test"
    shell = _FakeProc(pid=100, name="zsh", terminal=tty_path, parent=None)
    agent = _FakeProc(pid=200, name="python", terminal=tty_path, parent=shell)

    _install_fake_psutil(monkeypatch, {200: agent})
    _allow_fake_tty(monkeypatch, tty_path)
    monkeypatch.setattr("os.getppid", lambda: 200)

    pid, tty = _get_parent_process_info()
    assert pid == 100
    assert tty == tty_path


def test_falls_back_to_nearest_tty_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    tty_path = "/dev/ttys-test"
    parent = _FakeProc(pid=200, name="python", terminal=tty_path, parent=None)

    _install_fake_psutil(monkeypatch, {200: parent})
    _allow_fake_tty(monkeypatch, tty_path)
    monkeypatch.setattr("os.getppid", lambda: 200)

    pid, tty = _get_parent_process_info()
    assert pid == 200
    assert tty == tty_path
