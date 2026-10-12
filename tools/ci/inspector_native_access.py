"""Produce one credential-free native access receipt from fixed readiness operands."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

_ENCODING = "utf-8"
_PRIVATE_FILE_MODE = 0o600
_ARGUMENT_COUNT = 3
_INVALID_ARGUMENTS = "The native access receipt requires one operation and one fixed marker path."
_MAIN = "__main__"


class NativeAccessOperation(StrEnum):
    """The two fixed access operations used by credential-free readiness."""

    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class NativeAccessReceipt:
    """Completed operation metadata, without file content or exception text."""

    operation: NativeAccessOperation
    errno: int | None = None
    sha256: str | None = None


def native_probe_program() -> str:
    """Use this checked module's exact source under the restricted native interpreter."""
    return Path(__file__).read_text(encoding=_ENCODING)


def main() -> None:
    """Execute one controlled access operation and emit only its narrow receipt."""
    if len(sys.argv) != _ARGUMENT_COUNT:
        raise ValueError(_INVALID_ARGUMENTS)
    operation = NativeAccessOperation(sys.argv[1])
    path = Path(sys.argv[2])
    try:
        if operation is NativeAccessOperation.READ:
            receipt = NativeAccessReceipt(operation, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        else:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _PRIVATE_FILE_MODE)
            os.close(descriptor)
            receipt = NativeAccessReceipt(operation)
    except OSError as error:
        receipt = NativeAccessReceipt(operation, errno=error.errno)
    print(json.dumps(asdict(receipt)))


if __name__ == _MAIN:
    main()
