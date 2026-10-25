"""Shared process-group execution for declared argument vectors."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import IO, Any

_PROCESS_GROUP_TERM_GRACE_SECONDS = 2.0
_PROCESS_GROUP_KILL_GRACE_SECONDS = 2.0
_PROCESS_POLL_INTERVAL_SECONDS = 0.05
# An outer owner's SIGTERM must outlast one nested runner's whole escalation.
_PROCESS_GROUP_NESTED_TERM_GRACE_SECONDS = (
    _PROCESS_GROUP_TERM_GRACE_SECONDS + _PROCESS_GROUP_KILL_GRACE_SECONDS + _PROCESS_POLL_INTERVAL_SECONDS
)
COMMAND_START_FAILURE_EXIT_CODE = 127
_OUTPUT_TAIL_CHARACTERS = 4096
_OUTPUT_ENCODING = "utf-8"
_OUTPUT_DECODE_ERRORS = "replace"
_START_FAILURE_OUTPUT = "{kind}: {error}"
_PROCESS_GROUP_CANCELLATION_CONTEXT_NAME = "process_group_cancellation"
_CONCURRENT_OPERATION_LIMIT = 2
type _SignalHandler = Callable[[int, FrameType | None], object] | int | None


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


@dataclass(frozen=True)
class _OperationValue[T]:
    value: T


@dataclass(frozen=True)
class _OperationFailure:
    error: BaseException


@contextmanager
def process_group_cancellation_scope(cancellation: ProcessGroupCancellation) -> Iterator[None]:
    """Bind cancellation so ``asyncio.to_thread`` carries it into the worker."""
    token = _PROCESS_GROUP_CANCELLATION.set(cancellation)
    try:
        yield
    finally:
        _PROCESS_GROUP_CANCELLATION.reset(token)


def run_concurrent_operations[T](operations: Sequence[Callable[[], T]]) -> tuple[T, ...]:
    """Run bounded synchronous checks with shared cancellation and ordered results.

    Each worker receives its own copied context through ``asyncio.to_thread``.
    Nested coordinators inherit cancellation and own separate bounded workers;
    they never wait for space in the executor that is running their parent.
    """
    raise_if_command_cancelled()
    if len(operations) < 2:
        return tuple(operation() for operation in operations)
    cancellation = _PROCESS_GROUP_CANCELLATION.get() or ProcessGroupCancellation()
    previous: dict[int, _SignalHandler] = {}
    installable = threading.current_thread() is threading.main_thread()

    def request_signal(signum: int, _frame: object) -> None:
        cancellation.request(signum)

    with process_group_cancellation_scope(cancellation):
        try:
            if installable:
                for signal_value in (signal.SIGINT, signal.SIGTERM):
                    previous[signal_value] = signal.signal(signal_value, request_signal)
            outcomes = asyncio.run(_gather_operations(operations, cancellation))
            for outcome in outcomes:
                if isinstance(outcome, _OperationFailure) and not isinstance(
                    outcome.error, ProcessGroupCancellationRequested
                ):
                    raise outcome.error
            _raise_if_cancelled(cancellation)
            return tuple(outcome.value for outcome in outcomes if isinstance(outcome, _OperationValue))
        except ProcessGroupCancellationRequested:
            if installable and (received_signum := cancellation.signum) is not None:
                signal.signal(received_signum, signal.SIG_DFL)
                os.kill(os.getpid(), received_signum)
                raise SystemExit(128 + received_signum) from None
            raise
        finally:
            for stored_signal, handler in previous.items():
                signal.signal(stored_signal, handler)


async def _gather_operations[T](
    operations: Sequence[Callable[[], T]], cancellation: ProcessGroupCancellation
) -> tuple[_OperationValue[T] | _OperationFailure, ...]:
    """Join every worker before releasing the caller's resources."""
    semaphore = asyncio.Semaphore(_CONCURRENT_OPERATION_LIMIT)

    async def invoke(operation: Callable[[], T]) -> _OperationValue[T] | _OperationFailure:
        async with semaphore:
            return await asyncio.to_thread(_invoke_operation, operation, cancellation)

    tasks = [asyncio.create_task(invoke(operation)) for operation in operations]
    try:
        return tuple(await asyncio.gather(*tasks))
    except BaseException:
        cancellation.request()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _invoke_operation[T](
    operation: Callable[[], T], cancellation: ProcessGroupCancellation
) -> _OperationValue[T] | _OperationFailure:
    """Keep worker BaseExceptions out of asyncio until every worker is joined."""
    try:
        _raise_if_cancelled(cancellation)
        return _OperationValue(operation())
    except BaseException as exc:
        cancellation.request()
        return _OperationFailure(exc)


@dataclass(frozen=True)
class CommandResult:
    """The terminal result of one argument-vector execution.

    ``output_tail`` holds the end of the command's combined output when the caller asked
    for it to be captured, so a failure can be reported with the command's own reason.
    ``timed_out`` is set when the command's process group was reaped because it outlived
    the caller's deadline.
    """

    exit_code: int
    output_tail: str | None = None
    timed_out: bool = False


def run_process_group_command(
    command: list[str],
    cwd: Path,
    child_env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float | None = None,
    capture_output: Callable[[str], str] | None = None,
    nested_runner: bool = False,
) -> CommandResult:
    """Run one external command and reap its entire process group on exit."""
    return run_process_group_commands(
        (command,),
        cwd,
        child_env,
        timeout_seconds=timeout_seconds,
        capture_output=capture_output,
        nested_runner=nested_runner,
    )[0]


def run_process_group_commands(
    commands: Sequence[Sequence[str]],
    cwd: Path,
    child_env: Mapping[str, str] | None = None,
    on_result: Callable[[int, CommandResult], None] | None = None,
    *,
    capture_output: Callable[[str], str] | None = None,
    timeout_seconds: float | None = None,
    nested_runner: bool = False,
) -> tuple[CommandResult, ...]:
    """Run argument vectors concurrently and reap every process group on exit.

    ``on_result`` is called with a command's index and result as soon as that command
    ends, so a caller can report each outcome while the others still run. With
    ``capture_output`` each command's combined output goes to a temporary file instead of
    the caller's streams; the whole output is passed through that function, and the tail of
    what it returns comes back with the result. A caller with no terminal of its own uses it
    so a failure keeps its reason, and masks what must not travel before anything is cut.

    ``timeout_seconds`` bounds each command from its start. A command still running past it
    has its process group terminated with a grace long enough for a nested runner to finish
    reaping its own groups, then killed, and its result is marked ``timed_out``. Without it
    a command runs until it exits.

    ``nested_runner`` grants a wrapper enough termination grace to finish its
    own child-group escalation on cancellation, exceptions and normal cleanup.
    Leaf command grace remains unchanged.
    """
    processes: list[subprocess.Popen[bytes] | None] = []
    started_at: list[float] = []
    outputs: list[IO[bytes] | None] = []
    results: list[CommandResult | None] = []
    previous: dict[int, Any] = {}
    cancellation = _PROCESS_GROUP_CANCELLATION.get()
    term_grace = _PROCESS_GROUP_NESTED_TERM_GRACE_SECONDS if nested_runner else _PROCESS_GROUP_TERM_GRACE_SECONDS

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
                output = tempfile.TemporaryFile() if capture_output is not None else None
                outputs.append(output)
                try:
                    # Declared arbitrary argv requires an external process; no Python-native API can perform the action.
                    process = subprocess.Popen(
                        list(command),
                        cwd=str(cwd),
                        env=dict(child_env) if child_env is not None else None,
                        start_new_session=True,
                        stdout=output,
                        stderr=subprocess.STDOUT if output is not None else None,
                    )
                except OSError as exc:
                    processes.append(None)
                    started_at.append(time.monotonic())
                    start_failure = CommandResult(
                        COMMAND_START_FAILURE_EXIT_CODE,
                        _START_FAILURE_OUTPUT.format(kind=type(exc).__name__, error=exc)
                        if capture_output is not None
                        else None,
                    )
                    results.append(start_failure)
                    if on_result is not None:
                        on_result(len(results) - 1, start_failure)
                    continue
                processes.append(process)
                started_at.append(time.monotonic())
                results.append(None)
            while any(result is None for result in results):
                _raise_if_cancelled(cancellation)
                for index, process in enumerate(processes):
                    if process is None or results[index] is not None:
                        continue
                    exit_code = process.poll()
                    if exit_code is None:
                        if timeout_seconds is not None and time.monotonic() - started_at[index] >= timeout_seconds:
                            _kill_process_group(process, _PROCESS_GROUP_NESTED_TERM_GRACE_SECONDS)
                            expired = CommandResult(
                                _reaped_exit_code(process), _output_tail(outputs[index], capture_output), True
                            )
                            results[index] = expired
                            if on_result is not None:
                                on_result(index, expired)
                        continue
                    _kill_process_group(process, term_grace)
                    finished = CommandResult(exit_code, _output_tail(outputs[index], capture_output))
                    results[index] = finished
                    if on_result is not None:
                        on_result(index, finished)
                if any(result is None for result in results):
                    time.sleep(_PROCESS_POLL_INTERVAL_SECONDS)
        except _SignalReceived as received:
            _kill_process_groups(processes, term_grace)
            signal.signal(received.signum, signal.SIG_DFL)
            os.kill(os.getpid(), received.signum)
            raise SystemExit(128 + received.signum) from None
        except BaseException:
            _kill_process_groups(processes, term_grace)
            raise
        return tuple(result for result in results if result is not None)
    finally:
        for stored_signal, handler in previous.items():
            signal.signal(stored_signal, handler)
        for captured in outputs:
            if captured is not None:
                captured.close()


def _output_tail(output: IO[bytes] | None, transform: Callable[[str], str] | None) -> str | None:
    """Return the end of one command's transformed output, or ``None`` when none was captured."""
    if output is None or transform is None:
        return None
    output.seek(0)
    whole = output.read().decode(_OUTPUT_ENCODING, errors=_OUTPUT_DECODE_ERRORS)
    return transform(whole)[-_OUTPUT_TAIL_CHARACTERS:]


class _SignalReceived(BaseException):
    """Unwind a blocked child wait after a termination signal."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _raise_if_cancelled(cancellation: ProcessGroupCancellation | None) -> None:
    if cancellation is not None and cancellation.requested:
        raise ProcessGroupCancellationRequested


def raise_if_command_cancelled() -> None:
    """Check the current command owner's cancellation while waiting for resources."""
    _raise_if_cancelled(_PROCESS_GROUP_CANCELLATION.get())


def _reaped_exit_code(process: subprocess.Popen[bytes]) -> int:
    """Return a reaped command's exit code; SIGKILL was the last signal sent when it is still unreaped."""
    exit_code = process.poll()
    return -signal.SIGKILL if exit_code is None else exit_code


def _kill_process_group(
    process: subprocess.Popen[bytes], term_grace: float = _PROCESS_GROUP_TERM_GRACE_SECONDS
) -> None:
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
    if not _wait_process_group(process, process_group, term_grace):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except OSError:
            pass
        _wait_process_group(process, process_group, _PROCESS_GROUP_KILL_GRACE_SECONDS)


def _kill_process_groups(
    processes: Sequence[subprocess.Popen[bytes] | None], term_grace: float = _PROCESS_GROUP_TERM_GRACE_SECONDS
) -> None:
    """Terminate and reap every process group that started successfully."""
    for process in processes:
        if process is not None:
            _kill_process_group(process, term_grace)


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
