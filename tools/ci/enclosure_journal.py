"""Exclusive ownership and one-attempt effect journal for the acceptance enclosure."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import (
    QUALIFICATION_DIGEST,
    RECIPE_DIGEST,
    STATIC_DIGEST,
    Action,
    Deadline,
    JsonObject,
    JsonValue,
    Phase,
    StaticPackage,
    Transition,
    object_value,
    parse_object,
    require_hex,
    text,
)

UTF8: Final = "utf-8"
NEWLINE: Final = b"\n"
EMPTY: Final = ""
JOURNAL_NAME: Final = "actions.jsonl"
JSON_SEPARATORS: Final = (",", ":")
BOOT_ID: Final = Path("/proc/sys/kernel/random/boot_id")
PROC_STAT: Final = "/proc/{pid}/stat"
PROC_DIRECTORY: Final = "/proc/{pid}"
PROC_STAT_END: Final = ")"
PROC_START_INDEX: Final = 19
JOURNAL_LIMIT: Final = 1024 * 1024
SCHEMA_VERSION: Final = 1
NANOSECONDS: Final = 1_000_000_000
ERROR_OWNER: Final = "the original enclosure controller identity is unavailable or changed"
ERROR_OWNERSHIP: Final = "the enclosure journal is not a private, exclusively owned regular file"
ERROR_HISTORY: Final = "the enclosure action journal is missing, truncated, corrupt or inconsistent"
ERROR_BUSY: Final = "another helper owns this run's action serialization boundary"
ERROR_UNKNOWN: Final = "the recorded enclosure effect is unknown; no second invocation is admitted: {action}"
ERROR_PHASE: Final = "the reviewed action edge does not admit {action} from {phase}"
ERROR_STOPPED: Final = "an unsuccessful enclosure action permits no subsequent normal-path mutation"
ERROR_LATE: Final = "the native action result arrived after its original command allowance"
ERROR_APPEND: Final = "recording the unknown effect also failed: {error_class}"
ERROR_RECORDED: Final = "a terminal receipt already exists; consume it through the read-only receipt query: {action}"
CLOSURE_ACTIONS: Final = frozenset({Action.POWEROFF, Action.OBSERVE, Action.EXTRACT, Action.RELEASE})
START_ACTIONS: Final = frozenset({Action.START_GUEST, Action.START_PAYLOAD})


class Key(StrEnum):
    """Fields in the protected, append-only run journal."""

    SCHEMA_VERSION = "schema_version"
    RUN_TOKEN = "run_token"
    CANDIDATE_COMMIT = "candidate_commit"
    CANDIDATE_TREE = "candidate_tree"
    REALIZATION_DIGEST = "realization_digest"
    STATIC_LOCK_DIGEST = "static_lock_digest"
    RECIPE_DIGEST = "recipe_digest"
    QUALIFICATION_DIGEST = "qualification_digest"
    CONTROLLER_PID = "controller_pid"
    CONTROLLER_START = "controller_start_ticks"
    CONTROLLER_UID = "controller_uid"
    BOOT_ID = "boot_id"
    STARTED_NS = "started_ns"
    END_NS = "end_ns"
    RESERVE_NS = "reserve_ns"
    SEQUENCE = "sequence"
    PREVIOUS_DIGEST = "previous_digest"
    EVENT = "event"
    PAYLOAD = "payload"
    ACTION = "action"
    STATUS = "status"
    EVIDENCE = "evidence"
    ERROR_CLASS = "error_class"
    LATE_RESULT = "late_result"
    DETAIL = "detail"
    COMMAND_END_NS = "command_end_ns"


class Event(StrEnum):
    """Journal event types, separate from action outcomes."""

    OWNER = "owner"
    INTENT = "intent"
    OUTCOME = "outcome"


class Outcome(StrEnum):
    """Actual action result or an explicit absence of acknowledgment."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TerminalProcessState(StrEnum):
    """Native process states which cannot own a new enclosure effect."""

    ZOMBIE = "Z"
    DEAD = "X"
    DEAD_LOWER = "x"


@dataclass(frozen=True)
class Controller:
    """Native Linux process identity of the original outside supervisor."""

    pid: int
    start_ticks: int
    uid: int
    boot_id: str

    @classmethod
    def capture(cls, pid: int) -> Controller:
        """Read positive native facts; inaccessible process state never means exited."""
        if pid <= 0:
            raise ValueError(ERROR_OWNER)
        raw = Path(PROC_STAT.format(pid=pid)).read_text(encoding=UTF8)
        end = raw.rfind(PROC_STAT_END)
        fields = raw[end + 1 :].split()
        if end < 0 or len(fields) <= PROC_START_INDEX or fields[0] in set(TerminalProcessState):
            raise ValueError(ERROR_OWNER)
        start = int(fields[PROC_START_INDEX])
        boot = BOOT_ID.read_text(encoding=UTF8).strip()
        if start <= 0 or not boot:
            raise ValueError(ERROR_OWNER)
        return cls(pid, start, Path(PROC_DIRECTORY.format(pid=pid)).stat().st_uid, boot)

    def require_alive(self) -> None:
        """Admit effects only while the same original process still exists."""
        try:
            current = Controller.capture(self.pid)
        except (OSError, ValueError) as error:
            raise RuntimeError(ERROR_OWNER) from error
        if current != self:
            raise RuntimeError(ERROR_OWNER)


@dataclass(frozen=True)
class Binding:
    """Run/source/static identities shared by all helpers; no runtime proof is implied."""

    run_token: str
    candidate_commit: str
    candidate_tree: str
    realization_digest: str
    controller: Controller

    def record(self, deadline: Deadline) -> JsonObject:
        """Serialize the initial identity and original budget once."""
        require_hex(self.run_token, 32)
        require_hex(self.candidate_commit, 40)
        require_hex(self.candidate_tree, 40)
        require_hex(self.realization_digest, 64)
        if (
            any(type(value) is not int for value in (deadline.started_ns, deadline.end_ns, deadline.reserve_ns))
            or deadline.started_ns <= 0
            or deadline.reserve_ns <= 0
            or deadline.end_ns <= deadline.started_ns + deadline.reserve_ns
        ):
            raise ValueError(ERROR_HISTORY)
        return {
            Key.SCHEMA_VERSION: SCHEMA_VERSION,
            Key.RUN_TOKEN: self.run_token,
            Key.CANDIDATE_COMMIT: self.candidate_commit,
            Key.CANDIDATE_TREE: self.candidate_tree,
            Key.REALIZATION_DIGEST: self.realization_digest,
            Key.STATIC_LOCK_DIGEST: STATIC_DIGEST,
            Key.RECIPE_DIGEST: RECIPE_DIGEST,
            Key.QUALIFICATION_DIGEST: QUALIFICATION_DIGEST,
            Key.CONTROLLER_PID: self.controller.pid,
            Key.CONTROLLER_START: self.controller.start_ticks,
            Key.CONTROLLER_UID: self.controller.uid,
            Key.BOOT_ID: self.controller.boot_id,
            Key.STARTED_NS: deadline.started_ns,
            Key.END_NS: deadline.end_ns,
            Key.RESERVE_NS: deadline.reserve_ns,
        }


@dataclass(frozen=True)
class ActionResult:
    """A terminal native acknowledgment with bounded structured evidence."""

    status: Outcome
    evidence: Mapping[str, JsonValue]

    def record(self, action: Action) -> JsonObject:
        """Freeze result data before the journal append crosses the durability boundary."""
        return {Key.ACTION: action.value, Key.STATUS: self.status.value, Key.EVIDENCE: dict(self.evidence)}


class ActionAlreadyRecorded(RuntimeError):
    """A new mutation was refused; the exact prior receipt remains separately consumable."""

    def __init__(self, action: Action, receipt: ActionResult) -> None:
        super().__init__(ERROR_RECORDED.format(action=action))
        self.action = action
        self.receipt = receipt


@dataclass(frozen=True)
class JournalView:
    """Derived normal-path state, including unresolved intent and exact terminal receipts."""

    rows: tuple[JsonObject, ...]
    phase: Phase
    pending: Action | None
    outcomes: Mapping[Action, ActionResult]


def _encode(record: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=JSON_SEPARATORS, allow_nan=False).encode(UTF8)


class ActionJournal:
    """An anchored journal; the lock covers intent, native effect and terminal outcome."""

    def __init__(
        self, directory_fd: int, journal_fd: int, binding: Binding, deadline: Deadline, package: StaticPackage
    ):
        self.directory_fd = directory_fd
        self.journal_fd = journal_fd
        self.binding = binding
        self.deadline = deadline
        self.transitions = package.transitions()
        self.owner_record = binding.record(deadline)

    @classmethod
    def create(cls, parent: Path, binding: Binding, deadline: Deadline, package: StaticPackage) -> ActionJournal:
        """Exclusively reserve a private run directory and read back its durable initial record."""
        binding.controller.require_alive()
        binding.record(deadline)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        directory_fd = -1
        journal_fd = -1
        try:
            os.mkdir(binding.run_token, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
            directory_fd = os.open(
                binding.run_token, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
            )
            journal_fd = os.open(
                JOURNAL_NAME,
                os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory_fd,
            )
            journal = cls(directory_fd, journal_fd, binding, deadline, package)
            with journal._exclusive():
                journal._append((), Event.OWNER, journal.owner_record)
                journal.read()
            os.fsync(directory_fd)
            return journal
        except BaseException:
            if journal_fd >= 0:
                os.close(journal_fd)
            if directory_fd >= 0:
                os.close(directory_fd)
            raise
        finally:
            os.close(parent_fd)

    @classmethod
    def attach_inherited(
        cls, original_directory_fd: int, binding: Binding, deadline: Deadline, package: StaticPackage
    ) -> ActionJournal:
        """Retain the inherited original directory but acquire an independent journal open-file description."""
        binding.controller.require_alive()
        directory_fd = os.dup(original_directory_fd)
        journal_fd = -1
        try:
            # Inheriting/duping the journal itself would share flock ownership across concurrent helper children.
            journal_fd = os.open(
                JOURNAL_NAME, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
            )
            journal = cls(directory_fd, journal_fd, binding, deadline, package)
            with journal._exclusive():
                journal.read()
            return journal
        except BaseException:
            if journal_fd >= 0:
                os.close(journal_fd)
            os.close(directory_fd)
            raise

    def close(self) -> None:
        """Release helper descriptors; retained workload resources are not removed here."""
        os.close(self.journal_fd)
        os.close(self.directory_fd)

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        try:
            fcntl.flock(self.journal_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(ERROR_BUSY) from error
        try:
            self._require_owned()
            yield
        finally:
            fcntl.flock(self.journal_fd, fcntl.LOCK_UN)

    def _require_owned(self) -> None:
        directory = os.fstat(self.directory_fd)
        native = os.fstat(self.journal_fd)
        linked = os.stat(JOURNAL_NAME, dir_fd=self.directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.geteuid()
            or stat.S_IMODE(directory.st_mode) != 0o700
            or not stat.S_ISREG(native.st_mode)
            or native.st_uid != os.geteuid()
            or stat.S_IMODE(native.st_mode) != 0o600
            or native.st_nlink != 1
            or (native.st_dev, native.st_ino) != (linked.st_dev, linked.st_ino)
        ):
            raise ValueError(ERROR_OWNERSHIP)

    def _append(self, previous: tuple[JsonObject, ...], event: Event, payload: JsonObject) -> None:
        prior = hashlib.sha256(_encode(previous[-1])).hexdigest() if previous else EMPTY
        record: JsonObject = {
            Key.SEQUENCE: len(previous),
            Key.PREVIOUS_DIGEST: prior,
            Key.EVENT: event.value,
            Key.PAYLOAD: payload,
        }
        data = _encode(record) + NEWLINE
        if os.fstat(self.journal_fd).st_size + len(data) > JOURNAL_LIMIT:
            raise ValueError(ERROR_HISTORY)
        offset = 0
        while offset < len(data):
            written = os.write(self.journal_fd, data[offset:])
            if written <= 0:
                raise OSError(ERROR_HISTORY)
            offset += written
        os.fsync(self.journal_fd)

    def read(self) -> JournalView:
        """Read an immutable history prefix; interrupted writes are never repaired or treated as absence."""
        self._require_owned()
        data = os.pread(self.journal_fd, JOURNAL_LIMIT + 1, 0)
        if not data or len(data) > JOURNAL_LIMIT or not data.endswith(NEWLINE):
            raise ValueError(ERROR_HISTORY)
        rows: list[JsonObject] = []
        phase = Phase.OWNED
        pending: Action | None = None
        outcomes: dict[Action, ActionResult] = {}
        for line in data.splitlines():
            row = parse_object(line)
            expected_prior = hashlib.sha256(_encode(rows[-1])).hexdigest() if rows else EMPTY
            if set(row) != {Key.SEQUENCE, Key.PREVIOUS_DIGEST, Key.EVENT, Key.PAYLOAD} or (
                type(row.get(Key.SEQUENCE)) is not int
                or row[Key.SEQUENCE] != len(rows)
                or row[Key.PREVIOUS_DIGEST] != expected_prior
            ):
                raise ValueError(ERROR_HISTORY)
            event = Event(text(row, Key.EVENT))
            payload = object_value(row[Key.PAYLOAD])
            if not rows:
                if event is not Event.OWNER or _encode(payload) != _encode(self.owner_record):
                    raise ValueError(ERROR_HISTORY)
            else:
                pending, phase = _apply_row(event, payload, pending, phase, outcomes, self.transitions)
            rows.append(row)
        return JournalView(tuple(rows), phase, pending, outcomes)

    def perform(
        self,
        action: Action,
        operation: Callable[[int], ActionResult],
        *,
        maximum_seconds: float,
        vector_end_ns: int | None = None,
        command_end_ns: int | None = None,
        admission: Callable[[int], None],
    ) -> ActionResult:
        """Issue an admitted effect once; every second mutation is refused before its callback."""
        with self._exclusive():
            self.binding.controller.require_alive()
            view = self.read()
            if view.pending is not None or any(result.status is Outcome.UNKNOWN for result in view.outcomes.values()):
                raise RuntimeError(ERROR_UNKNOWN.format(action=view.pending or action))
            if action in view.outcomes:
                raise ActionAlreadyRecorded(action, view.outcomes[action])
            if any(result.status is not Outcome.SUCCEEDED for result in view.outcomes.values()):
                raise RuntimeError(ERROR_STOPPED)
            transition = self.transitions[action]
            if view.phase is not transition.before:
                raise ValueError(ERROR_PHASE.format(action=action, phase=view.phase))
            if action in START_ACTIONS:
                self.deadline.admit(maximum_seconds)
            started = time.monotonic_ns()
            allowance = self.deadline.allowance(
                maximum_seconds, vector_end_ns=vector_end_ns, preserve_reserve=action not in CLOSURE_ACTIONS
            )
            command_end = min(self.deadline.end_ns, started + int(allowance * NANOSECONDS))
            if command_end_ns is not None:
                if type(command_end_ns) is not int or command_end_ns <= 0:
                    raise ValueError(ERROR_HISTORY)
                command_end = min(command_end, command_end_ns)
            if time.monotonic_ns() >= command_end:
                raise TimeoutError(ERROR_LATE)
            admission(command_end)
            if time.monotonic_ns() >= command_end:
                raise TimeoutError(ERROR_LATE)
            intent: JsonObject = {Key.ACTION: action.value, Key.COMMAND_END_NS: command_end}
            self._append(view.rows, Event.INTENT, intent)
            committed = self.read()
            try:
                if time.monotonic_ns() >= command_end:
                    raise TimeoutError(ERROR_LATE)
                result = operation(command_end)
            except BaseException as error:
                unknown = ActionResult(Outcome.UNKNOWN, {Key.ERROR_CLASS: type(error).__name__})
                try:
                    self._append(committed.rows, Event.OUTCOME, unknown.record(action))
                except (OSError, ValueError) as secondary:
                    error.add_note(ERROR_APPEND.format(error_class=type(secondary).__name__))
                raise
            if time.monotonic_ns() >= command_end:
                result = ActionResult(Outcome.UNKNOWN, {Key.DETAIL: ERROR_LATE, Key.LATE_RESULT: result.record(action)})
            self._append(committed.rows, Event.OUTCOME, result.record(action))
            self.read()
            return result

    def receipt(self, action: Action) -> ActionResult | None:
        """Consume a recorded acknowledgment without acquiring authority to invoke an effect."""
        with self._exclusive():
            return self.read().outcomes.get(action)


def _apply_row(
    event: Event,
    payload: JsonObject,
    pending: Action | None,
    phase: Phase,
    outcomes: dict[Action, ActionResult],
    transitions: Mapping[Action, Transition],
) -> tuple[Action | None, Phase]:
    if event is Event.OWNER:
        raise ValueError(ERROR_HISTORY)
    action = Action(text(payload, Key.ACTION))
    if event is Event.INTENT:
        if (
            set(payload) != {Key.ACTION, Key.COMMAND_END_NS}
            or type(payload[Key.COMMAND_END_NS]) is not int
            or pending is not None
            or action in outcomes
            or phase is not transitions[action].before
            or any(result.status is not Outcome.SUCCEEDED for result in outcomes.values())
        ):
            raise ValueError(ERROR_HISTORY)
        return action, phase
    if pending is not action or set(payload) != {Key.ACTION, Key.STATUS, Key.EVIDENCE}:
        raise ValueError(ERROR_HISTORY)
    status = Outcome(text(payload, Key.STATUS))
    evidence = object_value(payload[Key.EVIDENCE])
    outcomes[action] = ActionResult(status, evidence)
    return None, transitions[action].after if status is Outcome.SUCCEEDED else phase
