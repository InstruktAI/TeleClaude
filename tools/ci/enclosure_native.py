"""Existing native adapter contracts and bounded reads shared by enclosure roles."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import ERROR_BUDGET, AdmittedDeadline

# Every adapter receives the original absolute monotonic cutoff, never a fresh duration.
type NativeCommand = Callable[[tuple[str, ...], int], int | None]

READ_LIMIT: Final = 1024 * 1024
ERROR_NATIVE_READ: Final = "native enclosure read was incomplete or failed: {executable}, exit {status}"
NANOSECONDS: Final = 1_000_000_000
INVENTORY_ARGUMENTS: Final = (
    "/usr/bin/dpkg-query",
    "--show",
    "--showformat=${Package}\t${Version}\t${Architecture}\t${Status}\n",
)


@dataclass(frozen=True)
class NativeRead:
    """Bounded stdout from the real native read; incomplete output cannot prove inventory."""

    status: int | None
    stdout: bytes
    complete: bool


type NativeQuery = Callable[[tuple[str, ...], int], NativeRead]


def query_native(argv: tuple[str, ...], query: NativeQuery, deadline: AdmittedDeadline, cap: int) -> bytes:
    """Preserve the original absolute end and reject incomplete or late native query results."""
    end = deadline.command_end(cap)
    if time.monotonic_ns() >= end:
        raise TimeoutError(ERROR_BUDGET)
    result = query(argv, end)
    if time.monotonic_ns() >= end:
        raise TimeoutError(ERROR_BUDGET)
    if result.status != 0 or not result.complete or len(result.stdout) > READ_LIMIT:
        raise ValueError(ERROR_NATIVE_READ.format(executable=argv[0], status=result.status))
    return result.stdout


def execute_native(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    stdout_fd: int,
    stderr_fd: int,
    end_ns: int,
    started: Callable[[int], None],
    preserve: Callable[[subprocess.Popen[bytes]], None] | None = None,
) -> int:
    """Start one real native executable and preserve one cutoff through the started receipt and wait."""
    remaining = (end_ns - time.monotonic_ns()) / NANOSECONDS
    if remaining <= 0:
        raise TimeoutError(ERROR_BUDGET)
    # These producers exercise actual native executables; replacing them with Python collaborators changes the boundary.
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=stdout_fd,
        stderr=stderr_fd,
        close_fds=True,
        umask=0o022,
    )
    if preserve is not None:
        preserve(process)
    started(process.pid)
    remaining = (end_ns - time.monotonic_ns()) / NANOSECONDS
    if remaining <= 0:
        raise TimeoutError(ERROR_BUDGET)
    return process.wait(timeout=remaining)


def read_native_stdout(descriptor: int) -> tuple[bytes, bool]:
    """Read the existing bounded complete-output predicate from an owned native stdout file."""
    before = os.fstat(descriptor)
    output = os.pread(descriptor, READ_LIMIT + 1, 0)
    after = os.fstat(descriptor)
    complete = (
        len(output) <= READ_LIMIT
        and len(output) == after.st_size
        and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    )
    return output, complete
