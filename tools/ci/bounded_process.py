"""Run one child command in an owned process group with bounded time and output."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_EMPTY = ""
_UTF8 = "utf-8"
_UTF8_REPLACEMENT = "replace"
_PROCESS_FAILURE = 1
_PROCESS_LAUNCH_EXIT_CODE = 127
_PROCESS_LAUNCH_FAILED = "The required process could not be started."
_PROCESS_OUTPUT_LIMIT_DETAIL = "The command exceeded the output limit."
_PROCESS_TERMINATION_GRACE_SECONDS = 1
DEFAULT_OUTPUT_LIMIT_BYTES = 65536
PROCESS_TIMEOUT_DETAIL = "The command exceeded its deadline."


@dataclass(frozen=True)
class ProcessExecution:
    """Bounded output and lifecycle result from one child process group."""

    exit_status: int
    stdout: str
    stderr: str
    duration_seconds: float
    diagnostics: str = _EMPTY


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
) -> ProcessExecution:
    """Run one command in an owned process group and retain bounded evidence."""
    started = time.monotonic()
    # A child process is required to exercise the checked public executable and uv as real boundaries.
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        return ProcessExecution(
            exit_status=_PROCESS_LAUNCH_EXIT_CODE,
            stdout=_EMPTY,
            stderr=_EMPTY,
            duration_seconds=time.monotonic() - started,
            diagnostics=_PROCESS_LAUNCH_FAILED,
        )
    try:
        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_seconds)
            diagnostics = _EMPTY
        except subprocess.TimeoutExpired:
            _stop_process_group(process)
            stdout_bytes, stderr_bytes = process.communicate()
            diagnostics = PROCESS_TIMEOUT_DETAIL
        except BaseException:
            _stop_process_group(process)
            process.communicate()
            raise
    finally:
        if process.poll() is None:
            _stop_process_group(process)
    output_exceeded = len(stdout_bytes) > output_limit_bytes or len(stderr_bytes) > output_limit_bytes
    if output_exceeded:
        diagnostics = _PROCESS_OUTPUT_LIMIT_DETAIL
    return ProcessExecution(
        exit_status=process.returncode if process.returncode is not None else _PROCESS_FAILURE,
        stdout=stdout_bytes[:output_limit_bytes].decode(_UTF8, errors=_UTF8_REPLACEMENT),
        stderr=stderr_bytes[:output_limit_bytes].decode(_UTF8, errors=_UTF8_REPLACEMENT),
        duration_seconds=time.monotonic() - started,
        diagnostics=diagnostics,
    )


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate every process in the command group, escalating after a short grace."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait()
    except ChildProcessError:
        return
