"""Existing native adapter contracts and bounded reads shared by enclosure roles."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from tools.ci.enclosure_contract import ERROR_BUDGET, AdmittedDeadline

# Every adapter receives the original absolute monotonic cutoff, never a fresh duration.
type NativeCommand = Callable[[tuple[str, ...], int], int | None]

READ_LIMIT: Final = 1024 * 1024
ERROR_NATIVE_READ: Final = "native enclosure read was incomplete or failed: {executable}, exit {status}"
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
