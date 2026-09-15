"""Shared process-group execution for declared argument vectors."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROCESS_GROUP_TERM_GRACE_SECONDS = 2.0
_PROCESS_GROUP_KILL_GRACE_SECONDS = 2.0


@dataclass(frozen=True)
class CommandResult:
    """The terminal result of one argument-vector execution."""

    exit_code: int


def run_process_group_command(
    command: list[str], cwd: Path, child_env: Mapping[str, str] | None = None
) -> CommandResult:
    """Run one external command and reap its entire process group on exit."""
    process = subprocess.Popen(
        command, cwd=str(cwd), env=dict(child_env) if child_env is not None else None, start_new_session=True
    )
    previous: dict[int, Any] = {}

    def _forward(signum: int, _frame: object) -> None:
        raise _SignalReceived(signum)

    installable = threading.current_thread() is threading.main_thread()
    try:
        if installable:
            for signal_value in (signal.SIGINT, signal.SIGTERM):
                previous[signal_value] = signal.signal(signal_value, _forward)
        try:
            exit_code = process.wait()
        except _SignalReceived as received:
            _kill_process_group(process)
            signal.signal(received.signum, signal.SIG_DFL)
            os.kill(os.getpid(), received.signum)
            raise SystemExit(128 + received.signum) from None
        except BaseException:
            _kill_process_group(process)
            raise
        _kill_process_group(process)
        return CommandResult(exit_code)
    finally:
        for stored_signal, handler in previous.items():
            signal.signal(stored_signal, handler)


class _SignalReceived(BaseException):
    """Unwind a blocked child wait after a termination signal."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    process_group = process.pid
    try:
        process_group = os.getpgid(process.pid)
    except OSError:
        pass
    if not _process_group_exists(process_group):
        return
    try:
        os.killpg(process_group, signal.SIGTERM)
    except OSError:
        return
    if not _wait_process_group(process, process_group, _PROCESS_GROUP_TERM_GRACE_SECONDS):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except OSError:
            pass
        _wait_process_group(process, process_group, _PROCESS_GROUP_KILL_GRACE_SECONDS)


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_process_group(process: subprocess.Popen[bytes], process_group: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        process.poll()
        if not _process_group_exists(process_group):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))
