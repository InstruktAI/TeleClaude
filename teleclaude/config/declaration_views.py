"""Keep runtime-resolved declaration answers until their inputs or code change."""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from teleclaude.file_transaction import file_transaction
from teleclaude.paths import DECLARATION_VIEWS_DIR

_EPOCH_NAME = "epoch"
_UTF8 = "utf-8"
_SETTLE_SECONDS = 1_000_000_000


class _Dependency(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def exists(self) -> bool: ...

    @property
    def mtime_ns(self) -> int: ...

    @property
    def size(self) -> int: ...

    @property
    def inode(self) -> int: ...


class _Capabilities(Protocol):
    @property
    def is_target(self) -> bool: ...

    @property
    def code(self) -> bool: ...

    @property
    def docs(self) -> bool: ...

    @property
    def agents(self) -> bool: ...


class _View(Protocol):
    @property
    def kind(self) -> object | None: ...

    @property
    def capabilities(self) -> _Capabilities: ...

    @property
    def dependencies(self) -> Sequence[_Dependency]: ...


def entry_path_for_root(root: Path) -> Path:
    """Map a root path injectively to one flat entry filename."""
    encoded = str(root.expanduser().resolve()).replace("%", "%25").replace("/", "%2F")
    return DECLARATION_VIEWS_DIR / encoded


def entry_text(view: _View, generation: str) -> str:
    """Render one answer and its dependency list as the shell entry format."""
    kind = getattr(view.kind, "value", view.kind)
    answer = str(kind) if kind is not None else "-"
    capabilities = view.capabilities
    if not capabilities.is_target:
        flags = "0 0 0"
    else:
        flags = " ".join("1" if value else "0" for value in (capabilities.code, capabilities.docs, capabilities.agents))
    lines = [generation, answer, flags]
    lines.extend(("+" if dependency.exists else "-") + str(dependency.path) for dependency in view.dependencies)
    return "\n".join(lines) + "\n"


def read_epoch() -> str:
    """Read or initialize the token invalidating answers across installation changes."""
    epoch_path = DECLARATION_VIEWS_DIR / _EPOCH_NAME
    with file_transaction(epoch_path) as transaction:
        epoch = transaction.read_text(encoding=_UTF8).strip()
        if not epoch:
            epoch = uuid4().hex
            transaction.replace_text(epoch + "\n", encoding=_UTF8)
    return epoch


def publish_entry(
    entry_path: Path,
    view: _View,
    pre_read_stats: Sequence[_Dependency],
    epoch_at_start: str,
    *,
    generation: str | None = None,
) -> bool:
    """Publish only a settled answer whose inputs and installation epoch stayed stable."""
    _require_entry_path(entry_path)
    epoch_path = DECLARATION_VIEWS_DIR / _EPOCH_NAME
    with file_transaction(epoch_path) as epoch_transaction:
        if epoch_transaction.read_text(encoding=_UTF8).strip() != epoch_at_start:
            return False
        now_second = time.time_ns() // _SETTLE_SECONDS
        for dependency in pre_read_stats:
            current = _dependency_stat(dependency.path)
            if not _same_stat(dependency, current):
                _remove_entry(entry_path)
                return False
            if dependency.exists and dependency.mtime_ns // _SETTLE_SECONDS >= now_second:
                _remove_entry(entry_path)
                return False
        generation = generation or uuid4().hex
        entry = entry_text(view, generation)
        created_stamps: list[Path] = []
        try:
            for index, dependency in enumerate(pre_read_stats):
                if not dependency.exists:
                    continue
                stamp = entry_path.with_name(f"{entry_path.name}.{generation}.{index}")
                stamp.parent.mkdir(parents=True, exist_ok=True)
                stamp.touch(exist_ok=False)
                os.utime(stamp, ns=(dependency.mtime_ns, dependency.mtime_ns))
                created_stamps.append(stamp)
            with file_transaction(entry_path) as entry_transaction:
                old_generation = _entry_generation(entry_transaction.read_text(encoding=_UTF8))
                entry_transaction.replace_text(entry, encoding=_UTF8, creation_mode=0o600)
            if old_generation:
                _remove_generation_stamps(entry_path, old_generation)
        except BaseException:
            for stamp in created_stamps:
                stamp.unlink(missing_ok=True)
            raise
    return True


def read_entry(entry_path: Path) -> str:
    """Read one stored entry without opening or acquiring any external resource."""
    _require_entry_path(entry_path)
    try:
        return entry_path.read_text(encoding=_UTF8)
    except FileNotFoundError:
        return ""


def discard_declaration_views(trigger: str) -> None:
    """Advance the epoch and remove every cached answer and generation stamp."""
    epoch_path = DECLARATION_VIEWS_DIR / _EPOCH_NAME
    with file_transaction(epoch_path) as transaction:
        transaction.replace_text(uuid4().hex + "\n", encoding=_UTF8)
        if not DECLARATION_VIEWS_DIR.exists():
            return
        for path in DECLARATION_VIEWS_DIR.iterdir():
            if path in {epoch_path, epoch_path.with_suffix(f"{epoch_path.suffix}.lock")}:
                continue
            if path.is_file():
                path.unlink(missing_ok=True)


def _require_entry_path(entry_path: Path) -> None:
    """Refuse entry paths outside the machine-owned declaration view directory."""
    directory = DECLARATION_VIEWS_DIR.resolve()
    resolved = entry_path.expanduser().resolve()
    if resolved.parent != directory:
        raise ValueError("Declaration view entry path is outside its state directory")


def _dependency_stat(path: Path) -> _Dependency:
    """Capture a file's current stat for an optimistic publication comparison."""
    try:
        value = path.stat()
    except FileNotFoundError:
        return _Stat(path=path, exists=False, mtime_ns=0, size=0, inode=0)
    return _Stat(path=path, exists=True, mtime_ns=value.st_mtime_ns, size=value.st_size, inode=value.st_ino)


class _Stat:
    """Structural stat matching the runtime's dependency record."""

    def __init__(self, *, path: Path, exists: bool, mtime_ns: int, size: int, inode: int) -> None:
        self.path = path
        self.exists = exists
        self.mtime_ns = mtime_ns
        self.size = size
        self.inode = inode


def _same_stat(before: _Dependency, after: _Dependency) -> bool:
    return (before.exists, before.mtime_ns, before.size, before.inode) == (
        after.exists,
        after.mtime_ns,
        after.size,
        after.inode,
    )


def _entry_generation(entry: str) -> str | None:
    lines = entry.splitlines()
    return lines[0] if lines else None


def _remove_generation_stamps(entry_path: Path, generation: str) -> None:
    for stamp in entry_path.parent.glob(f"{entry_path.name}.{generation}.*"):
        stamp.unlink(missing_ok=True)


def _remove_entry(entry_path: Path) -> None:
    """Invalidate an older answer when a fresh resolution cannot be kept."""
    with file_transaction(entry_path) as transaction:
        generation = _entry_generation(transaction.read_text(encoding=_UTF8))
        entry_path.unlink(missing_ok=True)
    if generation:
        _remove_generation_stamps(entry_path, generation)
