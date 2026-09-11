"""Bootstrap-safe locked atomic replacement for configuration files."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from uuid import uuid4

_LOCK_SUFFIX: Final = ".lock"
_TEMPORARY_PREFIX: Final = "."
_TEMPORARY_SUFFIX: Final = ".tmp"
_READ_WRITE_MODE: Final = "r+"
_LOCK_MODE: Final = "a+"
_UTF8: Final = "utf-8"


class FileTransaction:
    """Hold one stable per-file lock across read, decision, and replacement."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock_path = path.with_suffix(f"{path.suffix}{_LOCK_SUFFIX}")
        self._lock_file: object | None = None

    def read_text(self, *, encoding: str = "utf-8") -> str:
        return self.path.read_text(encoding=encoding) if self.path.exists() else ""

    def replace_text(self, content: str, *, encoding: str = "utf-8", creation_mode: int | None = None) -> None:
        temporary = self.path.with_name(f"{_TEMPORARY_PREFIX}{self.path.name}.{uuid4().hex}{_TEMPORARY_SUFFIX}")
        try:
            temporary.write_text(content, encoding=encoding)
            target_mode = stat.S_IMODE(self.path.stat().st_mode) if self.path.exists() else creation_mode
            if target_mode is not None:
                temporary.chmod(target_mode)
            with temporary.open(_READ_WRITE_MODE, encoding=encoding) as handle:
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


@contextmanager
def file_transaction(path: Path) -> Iterator[FileTransaction]:
    """Acquire a durable lock; callers perform all related I/O through it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(f"{path.suffix}{_LOCK_SUFFIX}")
    with lock_path.open(_LOCK_MODE, encoding=_UTF8) as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield FileTransaction(path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
