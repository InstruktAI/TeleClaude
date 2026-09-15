"""Shared process-group execution for declared argument vectors."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROCESS_GROUP_TERM_GRACE_SECONDS = 2.0
_PROCESS_GROUP_KILL_GRACE_SECONDS = 2.0
_PROCESS_POLL_INTERVAL_SECONDS = 0.05
_COMMAND_START_FAILURE_EXIT_CODE = 127
_PROCESS_GROUP_CANCELLATION_CONTEXT_NAME = "process_group_cancellation"


class ProcessGroupCancellation:
    """Thread-safe cancellation shared by an async caller and command worker."""

    def __init__(self) -> None:
        self._requested = threading.Event()
        self._signum: int | None = None
        self._lock = threading.RLock()

    @property
    def requested(self) -> bool:
        """Whether the owning async operation requested cancellation."""
        return self._requested.is_set()

    @property
    def signum(self) -> int | None:
        """The first termination signal, when cancellation came from a signal."""
        with self._lock:
            return self._signum

    def request(self, signum: int | None = None) -> None:
        """Request cancellation without replacing the first signal received."""
        with self._lock:
            if self._signum is None:
                self._signum = signum
        self._requested.set()


class ProcessGroupCancellationRequested(BaseException):
    """Stop command execution after every started process group is reaped."""


_PROCESS_GROUP_CANCELLATION: ContextVar[ProcessGroupCancellation | None] = ContextVar(
    _PROCESS_GROUP_CANCELLATION_CONTEXT_NAME,
    default=None,
)


@contextmanager
def process_group_cancellation_scope(cancellation: ProcessGroupCancellation) -> Iterator[None]:
    """Bind cancellation so ``asyncio.to_thread`` carries it into the worker."""
    token = _PROCESS_GROUP_CANCELLATION.set(cancellation)
    try:
        yield
    finally:
        _PROCESS_GROUP_CANCELLATION.reset(token)


@dataclass(frozen=True)
class CommandResult:
    """The terminal result of one argument-vector execution."""

    exit_code: int


def run_process_group_command(
    command: list[str], cwd: Path, child_env: Mapping[str, str] | None = None
) -> CommandResult:
    """Run one external command and reap its entire process group on exit."""
    return run_process_group_commands((command,), cwd, child_env)[0]


def run_process_group_commands(
    commands: Sequence[Sequence[str]], cwd: Path, child_env: Mapping[str, str] | None = None
) -> tuple[CommandResult, ...]:
    """Run argument vectors concurrently and reap every process group on exit."""
    processes: list[subprocess.Popen[bytes] | None] = []
    results: list[CommandResult | None] = []
    previous: dict[int, Any] = {}
    cancellation = _PROCESS_GROUP_CANCELLATION.get()

    def _forward(signum: int, _frame: object) -> None:
        raise _SignalReceived(signum)

    installable = threading.current_thread() is threading.main_thread()
    try:
        if installable:
            for signal_value in (signal.SIGINT, signal.SIGTERM):
                previous[signal_value] = signal.signal(signal_value, _forward)
        try:
            for command in commands:
                _raise_if_cancelled(cancellation)
                try:
                    # Declared arbitrary argv requires an external process; no Python-native API can perform the action.
                    process = subprocess.Popen(
                        list(command),
                        cwd=str(cwd),
                        env=dict(child_env) if child_env is not None else None,
                        start_new_session=True,
                    )
                except OSError:
                    processes.append(None)
                    results.append(CommandResult(_COMMAND_START_FAILURE_EXIT_CODE))
                    continue
                processes.append(process)
                results.append(None)
            while any(result is None for result in results):
                _raise_if_cancelled(cancellation)
                for index, process in enumerate(processes):
                    if process is None or results[index] is not None:
                        continue
                    exit_code = process.poll()
                    if exit_code is None:
                        continue
                    _kill_process_group(process)
                    results[index] = CommandResult(exit_code)
                if any(result is None for result in results):
                    time.sleep(_PROCESS_POLL_INTERVAL_SECONDS)
        except _SignalReceived as received:
            _kill_process_groups(processes)
            signal.signal(received.signum, signal.SIG_DFL)
            os.kill(os.getpid(), received.signum)
            raise SystemExit(128 + received.signum) from None
        except BaseException:
            _kill_process_groups(processes)
            raise
        return tuple(result for result in results if result is not None)
    finally:
        for stored_signal, handler in previous.items():
            signal.signal(stored_signal, handler)


class _SignalReceived(BaseException):
    """Unwind a blocked child wait after a termination signal."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _raise_if_cancelled(cancellation: ProcessGroupCancellation | None) -> None:
    if cancellation is not None and cancellation.requested:
        raise ProcessGroupCancellationRequested


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


def _kill_process_groups(processes: Sequence[subprocess.Popen[bytes] | None]) -> None:
    """Terminate and reap every process group that started successfully."""
    for process in processes:
        if process is not None:
            _kill_process_group(process)


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
