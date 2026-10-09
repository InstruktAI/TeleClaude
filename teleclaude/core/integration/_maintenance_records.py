"""Private persistence and lock owner for canonical-main maintenance records."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.paths import safe_path_component

_STATE_DIRECTORY = ".teleclaude"
_MAINTENANCE_DIRECTORY = "maintenance"
_DRAIN_LOCK_FILENAME = "drain.lock"
_RECORD_SUFFIX = ".json"
_RECORD_GLOB = "*.json"
_ACTIVATION_RECORD_GLOB = "*/*.json"
_LOCK_MODE = "a+"
_TEXT_ENCODING = "utf-8"
_NEWLINE = "\n"
_OUTPUT_TAIL_FIELD = "output_tail"


class _MaintenanceRecordPayload(BaseModel):
    """Closed wire model for one persisted action record."""

    model_config = ConfigDict(extra="forbid")

    before_sha: str | None
    after_sha: str
    action_id: str
    queued_at: str
    state: str
    exit_code: int | None
    finished_at: str | None
    output_tail: str | None


class MaintenanceRecordState(StrEnum):
    """The retry lifecycle of one owed deterministic maintenance action."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"


@dataclass(frozen=True)
class MaintenanceActionRecord:
    """One durable action obligation for an immutable activation range."""

    before_sha: str | None
    after_sha: str
    action_id: str
    queued_at: str
    state: MaintenanceRecordState
    exit_code: int | None = None
    finished_at: str | None = None
    output_tail: str | None = None


def maintenance_directory(project_root: str | Path) -> Path:
    """Return the gitignored record directory for the owning checkout."""
    root = resolve_project_state_root(project_root)
    return root / _STATE_DIRECTORY / _MAINTENANCE_DIRECTORY


def activation_directory(project_root: str | Path, after_sha: str) -> Path:
    """Return the immutable activation's record directory."""
    return maintenance_directory(project_root) / safe_path_component(after_sha)


def record_path(project_root: str | Path, after_sha: str, action_id: str) -> Path:
    """Return one action record's stable path."""
    filename = safe_path_component(action_id) + _RECORD_SUFFIX
    return activation_directory(project_root, after_sha) / filename


def write_record(path: Path, record: MaintenanceActionRecord) -> None:
    """Atomically persist a record so readers see its old or new full value."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=_TEXT_ENCODING,
            dir=path.parent,
            prefix=path.name,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(asdict(record), handle, separators=(",", ":"))
            handle.write(_NEWLINE)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_record(path: Path) -> MaintenanceActionRecord:
    """Read one typed record from its durable JSON form, migrating an older record forward first."""
    document = json.loads(path.read_text(encoding=_TEXT_ENCODING))
    upcast = _upcast_record_document(document)
    payload = _MaintenanceRecordPayload.model_validate(upcast)
    record = _record_from_payload(payload)
    if upcast is not document:
        write_record(path, record)
    return record


def _upcast_record_document(document: object) -> object:
    """Bring a record written before failures kept their output to the current shape.

    Remove once no record that predates ``output_tail`` can remain on any computer.
    """
    if isinstance(document, dict) and _OUTPUT_TAIL_FIELD not in document:
        return {**document, _OUTPUT_TAIL_FIELD: None}
    return document


def _record_from_payload(payload: _MaintenanceRecordPayload) -> MaintenanceActionRecord:
    return MaintenanceActionRecord(
        before_sha=payload.before_sha,
        after_sha=payload.after_sha,
        action_id=payload.action_id,
        queued_at=payload.queued_at,
        state=MaintenanceRecordState(payload.state),
        exit_code=payload.exit_code,
        finished_at=payload.finished_at,
        output_tail=payload.output_tail,
    )


def read_records(project_root: str | Path) -> tuple[MaintenanceActionRecord, ...]:
    """Read the checkout's action records in stable path order."""
    directory = maintenance_directory(project_root)
    if not directory.exists():
        return ()
    return tuple(read_record(path) for path in sorted(directory.glob(_ACTIVATION_RECORD_GLOB)))


def activation_has_records(project_root: str | Path, after_sha: str) -> bool:
    """Return whether any action record, including a terminal failure, remains."""
    directory = activation_directory(project_root, after_sha)
    return directory.exists() and any(directory.glob(_RECORD_GLOB))


def remove_record(path: Path) -> None:
    """Remove a confirmed-success action record."""
    path.unlink(missing_ok=True)


@contextmanager
def maintenance_drain_lock(project_root: str | Path, on_contention: Callable[[], None] | None = None) -> Iterator[None]:
    """Hold the stable OS lock that serializes all drain state transitions.

    A holder already in place makes the caller wait; ``on_contention`` is called once
    before it does, so the caller can say so.
    """
    lock_path = maintenance_directory(project_root) / _DRAIN_LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open(_LOCK_MODE, encoding=_TEXT_ENCODING) as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if on_contention is not None:
                on_contention()
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
