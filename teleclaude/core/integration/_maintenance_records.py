"""Private persistence and lock owner for maintenance records of commit and event activations."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.paths import safe_path_component

_STATE_DIRECTORY = ".teleclaude"
_MAINTENANCE_DIRECTORY = "maintenance"
_DRAIN_LOCK_FILENAME = "drain.lock"
_RECORD_SUFFIX = ".json"
_RECORD_GLOB = "*.json"
_ACTIVATION_RECORD_GLOB = "*/*.json"
_EVENT_FILENAME = "event.payload"
_EVENT_KEY_PREFIX = "event-"
_EVENT_ID_FIELD = "event_id"
_LOCK_MODE = "a+"
_ACTIVATION_REGISTRATION_LOCK_FILENAME = "activation-registration.lock"
_TEXT_ENCODING = "utf-8"
_NEWLINE = "\n"
_OUTPUT_TAIL_FIELD = "output_tail"
_ACTIVATION_REGISTRATIONS_FILENAME = "activation-registrations.json"
_MAX_ACTIVATION_REGISTRATIONS = 512
_PENDING_SETTLEMENTS_FILENAME = "pending-settlements.json"
_PENDING_SETTLEMENTS_LOCK_FILENAME = "pending-settlements.lock"


class _CommitRecordPayload(BaseModel):
    """Closed wire model for one persisted action record of a commit activation."""

    model_config = ConfigDict(extra="forbid")

    before_sha: str | None
    after_sha: str
    action_id: str
    queued_at: str
    state: str
    exit_code: int | None
    finished_at: str | None
    output_tail: str | None


class _EventRecordPayload(BaseModel):
    """Closed wire model for one persisted action record of an event activation."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    action_id: str
    queued_at: str
    state: str
    exit_code: int | None
    finished_at: str | None
    output_tail: str | None


class _ActivationRegistrationEntry(BaseModel):
    """The resolved owed actions for one commit advancement."""

    model_config = ConfigDict(extra="forbid")

    after_sha: str
    action_ids: list[str]


class _ActivationRegistrationsPayload(BaseModel):
    """A bounded history that makes commit-boundary recording idempotent."""

    model_config = ConfigDict(extra="forbid")

    registrations: list[_ActivationRegistrationEntry]


class _FailedActionEntry(BaseModel):
    """One action that stayed failed in a settled activation, with the command that replays it."""

    model_config = ConfigDict(extra="forbid")

    action_id: str
    replay_command: str


class _PendingSettlementEntry(BaseModel):
    """One settled commit activation whose announcement is not yet delivered."""

    model_config = ConfigDict(extra="forbid")

    before_sha: str | None
    after_sha: str
    outcome: str
    failed_actions: list[_FailedActionEntry]


class _PendingSettlementsPayload(BaseModel):
    """The settlements awaiting delivery; each stays until the producer accepted its announcement."""

    model_config = ConfigDict(extra="forbid")

    settlements: list[_PendingSettlementEntry]


@dataclass(frozen=True)
class ActivationRegistration:
    """The recorded outcome of resolving an advancement's owed action set."""

    action_ids: tuple[str, ...]


class MaintenanceRecordState(StrEnum):
    """The retry lifecycle of one owed deterministic maintenance action."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"


@dataclass(frozen=True)
class EventActivation:
    """The platform event an event activation answers: its id and the type it was recorded with."""

    event_id: str
    event_type: str


type MaintenanceActivation = ActivationRange | EventActivation


class SettlementOutcome(StrEnum):
    """How a commit activation settled: every owed action completed, or at least one stayed failed."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class FailedAction:
    """An owed action that stayed failed, with the command that replays it for its activation."""

    action_id: str
    replay_command: str


@dataclass(frozen=True)
class PendingSettlement:
    """The settlement of one commit activation, held until its announcement is delivered."""

    activation: ActivationRange
    outcome: SettlementOutcome
    failed_actions: tuple[FailedAction, ...]


@dataclass(frozen=True)
class MaintenanceActionRecord:
    """One durable action obligation for an immutable commit range or a recorded event."""

    activation: MaintenanceActivation
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


@contextmanager
def maintenance_activation_registration_lock(project_root: str | Path) -> Iterator[None]:
    """Serialize activation record registration with the drain's final empty-record boundary."""
    lock_path = maintenance_directory(project_root) / _ACTIVATION_REGISTRATION_LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open(_LOCK_MODE, encoding=_TEXT_ENCODING) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_activation_registration(project_root: str | Path, after_sha: str) -> ActivationRegistration | None:
    """Read whether one advancement's owed set was resolved, including an empty set."""
    path = maintenance_directory(project_root) / _ACTIVATION_REGISTRATIONS_FILENAME
    if not path.exists():
        return None
    payload = _ActivationRegistrationsPayload.model_validate_json(path.read_text(encoding=_TEXT_ENCODING))
    entry = next((registration for registration in payload.registrations if registration.after_sha == after_sha), None)
    return None if entry is None else ActivationRegistration(action_ids=tuple(entry.action_ids))


def write_activation_registration(project_root: str | Path, after_sha: str, action_ids: tuple[str, ...]) -> None:
    """Record one resolved advancement while holding the activation-registration lock."""
    path = maintenance_directory(project_root) / _ACTIVATION_REGISTRATIONS_FILENAME
    registrations = (
        _ActivationRegistrationsPayload.model_validate_json(path.read_text(encoding=_TEXT_ENCODING)).registrations
        if path.exists()
        else []
    )
    retained = [registration for registration in registrations if registration.after_sha != after_sha]
    retained.append(_ActivationRegistrationEntry(after_sha=after_sha, action_ids=list(action_ids)))
    bounded = retained[-_MAX_ACTIVATION_REGISTRATIONS:]
    payload = _ActivationRegistrationsPayload(registrations=bounded)
    _write_atomically(path, payload.model_dump_json())


@contextmanager
def _pending_settlements_lock(project_root: str | Path) -> Iterator[None]:
    """Serialize reads and rewrites of the pending-settlement list; held only for the file operation itself."""
    lock_path = maintenance_directory(project_root) / _PENDING_SETTLEMENTS_LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open(_LOCK_MODE, encoding=_TEXT_ENCODING) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_pending_settlements_unlocked(path: Path) -> list[_PendingSettlementEntry]:
    if not path.exists():
        return []
    return _PendingSettlementsPayload.model_validate_json(path.read_text(encoding=_TEXT_ENCODING)).settlements


def _pending_settlement_from_entry(entry: _PendingSettlementEntry) -> PendingSettlement:
    return PendingSettlement(
        activation=ActivationRange(before_sha=entry.before_sha, after_sha=entry.after_sha),
        outcome=SettlementOutcome(entry.outcome),
        failed_actions=tuple(FailedAction(failed.action_id, failed.replay_command) for failed in entry.failed_actions),
    )


def _pending_settlement_entry(settlement: PendingSettlement) -> _PendingSettlementEntry:
    return _PendingSettlementEntry(
        before_sha=settlement.activation.before_sha,
        after_sha=settlement.activation.after_sha,
        outcome=settlement.outcome.value,
        failed_actions=[
            _FailedActionEntry(action_id=failed.action_id, replay_command=failed.replay_command)
            for failed in settlement.failed_actions
        ],
    )


def read_pending_settlements(project_root: str | Path) -> tuple[PendingSettlement, ...]:
    """Read the settlements whose announcement is not yet delivered, oldest first."""
    path = maintenance_directory(project_root) / _PENDING_SETTLEMENTS_FILENAME
    with _pending_settlements_lock(project_root):
        entries = _read_pending_settlements_unlocked(path)
    return tuple(_pending_settlement_from_entry(entry) for entry in entries)


def write_pending_settlement(project_root: str | Path, settlement: PendingSettlement) -> None:
    """Hold one settlement for delivery; a repeat of the same settlement replaces its earlier copy."""
    path = maintenance_directory(project_root) / _PENDING_SETTLEMENTS_FILENAME
    entry = _pending_settlement_entry(settlement)
    with _pending_settlements_lock(project_root):
        retained = [
            held
            for held in _read_pending_settlements_unlocked(path)
            if (held.after_sha, held.outcome) != (entry.after_sha, entry.outcome)
        ]
        retained.append(entry)
        payload = _PendingSettlementsPayload(settlements=retained)
        _write_atomically(path, payload.model_dump_json())


def remove_pending_settlement(project_root: str | Path, settlement: PendingSettlement) -> None:
    """Retire one settlement once its announcement is delivered."""
    path = maintenance_directory(project_root) / _PENDING_SETTLEMENTS_FILENAME
    with _pending_settlements_lock(project_root):
        held = _read_pending_settlements_unlocked(path)
        retained = [
            entry
            for entry in held
            if (entry.after_sha, entry.outcome) != (settlement.activation.after_sha, settlement.outcome.value)
        ]
        if len(retained) != len(held):
            _write_atomically(path, _PendingSettlementsPayload(settlements=retained).model_dump_json())


def commit_activation_key(after_sha: str) -> str:
    """Name the record directory of the commit activation that ends at ``after_sha``."""
    return safe_path_component(after_sha)


def event_activation_key(event_id: str) -> str:
    """Name the record directory of the activation that answers one event."""
    return safe_path_component(_EVENT_KEY_PREFIX + event_id)


def activation_key(activation: MaintenanceActivation) -> str:
    """Name the record directory of an activation, which is also how a record is addressed for replay."""
    if isinstance(activation, EventActivation):
        return event_activation_key(activation.event_id)
    return commit_activation_key(activation.after_sha)


def activation_directory(project_root: str | Path, key: str) -> Path:
    """Return the immutable activation's record directory."""
    return maintenance_directory(project_root) / key


def record_path(project_root: str | Path, key: str, action_id: str) -> Path:
    """Return one action record's stable path."""
    filename = safe_path_component(action_id) + _RECORD_SUFFIX
    return activation_directory(project_root, key) / filename


def event_file_path(project_root: str | Path, event_id: str) -> Path:
    """Return the file holding the event an event activation answers; the record glob never reads it."""
    return activation_directory(project_root, event_activation_key(event_id)) / _EVENT_FILENAME


def write_event_file(project_root: str | Path, event: ReceivedEvent) -> Path:
    """Persist the event in the envelope's own serialization for the actions that react to it."""
    path = event_file_path(project_root, event.id)
    _write_atomically(path, event.model_dump_json())
    return path


def write_record(path: Path, record: MaintenanceActionRecord) -> None:
    """Atomically persist a record so readers see its old or new full value."""
    _write_atomically(path, _record_payload(record).model_dump_json())


def _write_atomically(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` in one step so readers see the old or the new full content."""
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
            handle.write(text)
            handle.write(_NEWLINE)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _record_payload(record: MaintenanceActionRecord) -> _CommitRecordPayload | _EventRecordPayload:
    """The closed wire model of a record, for the kind of activation it answers."""
    activation = record.activation
    if isinstance(activation, EventActivation):
        return _EventRecordPayload(
            event_id=activation.event_id,
            event_type=activation.event_type,
            action_id=record.action_id,
            queued_at=record.queued_at,
            state=record.state.value,
            exit_code=record.exit_code,
            finished_at=record.finished_at,
            output_tail=record.output_tail,
        )
    return _CommitRecordPayload(
        before_sha=activation.before_sha,
        after_sha=activation.after_sha,
        action_id=record.action_id,
        queued_at=record.queued_at,
        state=record.state.value,
        exit_code=record.exit_code,
        finished_at=record.finished_at,
        output_tail=record.output_tail,
    )


def read_record(path: Path) -> MaintenanceActionRecord:
    """Read one typed record from its durable JSON form, migrating an older record forward first."""
    return _record_from_text(path, path.read_text(encoding=_TEXT_ENCODING))


def _read_listed_record(path: Path) -> MaintenanceActionRecord | None:
    """Read a listed record, or nothing when its file was retired after the listing."""
    try:
        text = path.read_text(encoding=_TEXT_ENCODING)
    except FileNotFoundError:
        # A confirmed success retires its record while unlocked observers list the directory.
        return None
    return _record_from_text(path, text)


def _record_from_text(path: Path, text: str) -> MaintenanceActionRecord:
    document = json.loads(text)
    upcast = _upcast_record_document(document)
    record = _record_from_document(upcast)
    if upcast is not document:
        write_record(path, record)
    return record


def _record_from_document(document: object) -> MaintenanceActionRecord:
    """Validate a record document against the closed wire model of its activation kind."""
    if isinstance(document, dict) and _EVENT_ID_FIELD in document:
        event_payload = _EventRecordPayload.model_validate(document)
        return _record_from_event_payload(event_payload)
    return _record_from_commit_payload(_CommitRecordPayload.model_validate(document))


def _upcast_record_document(document: object) -> object:
    """Bring a record written before failures kept their output to the current shape.

    Remove once no record that predates ``output_tail`` can remain on any computer.
    """
    if isinstance(document, dict) and _OUTPUT_TAIL_FIELD not in document:
        return {**document, _OUTPUT_TAIL_FIELD: None}
    return document


def _record_from_commit_payload(payload: _CommitRecordPayload) -> MaintenanceActionRecord:
    return MaintenanceActionRecord(
        activation=ActivationRange(before_sha=payload.before_sha, after_sha=payload.after_sha),
        action_id=payload.action_id,
        queued_at=payload.queued_at,
        state=MaintenanceRecordState(payload.state),
        exit_code=payload.exit_code,
        finished_at=payload.finished_at,
        output_tail=payload.output_tail,
    )


def _record_from_event_payload(payload: _EventRecordPayload) -> MaintenanceActionRecord:
    return MaintenanceActionRecord(
        activation=EventActivation(event_id=payload.event_id, event_type=payload.event_type),
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
    listed = (_read_listed_record(path) for path in sorted(directory.glob(_ACTIVATION_RECORD_GLOB)))
    return tuple(record for record in listed if record is not None)


def activation_has_records(project_root: str | Path, key: str) -> bool:
    """Return whether any action record, including a terminal failure, remains."""
    directory = activation_directory(project_root, key)
    return directory.exists() and any(directory.glob(_RECORD_GLOB))


def remove_record(path: Path) -> None:
    """Remove a confirmed-success action record, and the event it answered once no record needs that event."""
    path.unlink(missing_ok=True)
    directory = path.parent
    event_file = directory / _EVENT_FILENAME
    if event_file.exists() and not any(directory.glob(_RECORD_GLOB)):
        event_file.unlink(missing_ok=True)
        # A directory that still holds anything else stays; only an emptied one is removed.
        with suppress(OSError):
            directory.rmdir()


def maintenance_drain_is_running(project_root: str | Path) -> bool:
    """Observe the stable drain lock without waiting or creating a lock file."""
    lock_path = maintenance_directory(project_root) / _DRAIN_LOCK_FILENAME
    if not lock_path.exists():
        return False
    with lock_path.open(_LOCK_MODE, encoding=_TEXT_ENCODING) as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        try:
            return False
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
