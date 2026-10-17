"""Append-only ownership ledger for the approved B5, B7 and B6 native flow."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from tools.ci.enclosure_contract import parse_object

ENCODING: Final = "utf-8"
LINE_BREAK: Final = "\n"
RECORD_FIELD: Final = "record"
RECORD_CLOSED_LIST: Final = "closed_list"
RECORD_ID_FIELD: Final = "id"
RECORD_CASE_FIELD: Final = "case"
RECORD_LABEL_FIELD: Final = "label"
RECORD_KIND_FIELD: Final = "kind"
RECORD_STATE_FIELD: Final = "state"
RECORD_PARENT_FIELD: Final = "parent"
RECORD_ACTIONS_FIELD: Final = "actions"
RECORD_OPERATION_FIELD: Final = "operation_id"
RECORD_SESSION_FIELD: Final = "session_id"
RECORD_EVIDENCE_FIELD: Final = "evidence"
RECORD_OPEN: Final = "open"
RECORD_DISCHARGED: Final = "discharged"
RECORD_OPERATION: Final = "operation"
RECORD_SESSION: Final = "session"
RECORD_TRIGGER: Final = "trigger"
RECORD_EFFECT: Final = "effect"
RECORD_UNKNOWN: Final = "unknown"
RECORD_KINDS: Final = frozenset({RECORD_OPERATION, RECORD_SESSION, RECORD_TRIGGER, RECORD_EFFECT})
RECORD_ALL_KINDS: Final = RECORD_KINDS | frozenset({RECORD_UNKNOWN})
FIELD_SET: Final = "set"
ID_SEPARATOR: Final = ":"
LINE_SEQUENCE_START: Final = 1
DETAIL_MISSING: Final = "the owned start ledger is missing"
DETAIL_INVALID: Final = "the owned start ledger is malformed: {detail}"
DETAIL_CASE: Final = "the owned start ledger has no closed action list for {case}"
DETAIL_ACTION: Final = "{case} has no declared start action {label} of kind {kind}"
DETAIL_DUPLICATE: Final = "the owned start ledger repeats an id: {identifier}"
DETAIL_UNKNOWN_ID: Final = "the owned start ledger update has no open id: {identifier}"
DETAIL_DUPLICATE_CASE: Final = "the owned start ledger repeats a closed action list: {case}"
DETAIL_PARENT: Final = "the owned start ledger parent does not match {case}:{label}"
DETAIL_TRIGGER_DISCHARGE: Final = "a trigger attempt cannot be discharged by observation: {identifier}"
DETAIL_ALREADY_SETTLED: Final = "the owned start attempt is no longer open: {identifier}"
DETAIL_RECORD_FIELDS: Final = "an owned start ledger record has unexpected fields"
DETAIL_FLOW_ID: Final = "the owned start ledger has an invalid flow id"
DETAIL_SEQUENCE: Final = "the owned start ledger id does not name its physical open-line number"

type ActionSpec = Mapping[str, str]
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True)
class Attempt:
    """The current derived view of one append-only attempt."""

    identifier: str
    case: str
    label: str
    kind: str
    state: str
    parent: str | None = None
    operation_id: str | None = None
    session_id: str | None = None
    evidence: str | None = None


@dataclass
class StartLedger:
    """A single-writer, append-only ledger; every append is flushed before its caller crosses the boundary."""

    path: Path
    flow_id: str
    lines: list[str] = field(default_factory=list)
    closed_lists: dict[str, dict[str, tuple[str, str | None]]] = field(default_factory=dict)
    attempts: dict[str, Attempt] = field(default_factory=dict)

    @classmethod
    def create(cls, path: Path, flow_id: str | None = None) -> StartLedger:
        """Create the flow-owned file exactly once and fsync its first line before any start."""
        identifier = flow_id if flow_id is not None else str(uuid.uuid4())
        if not identifier:
            raise ValueError(DETAIL_FLOW_ID)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding=ENCODING) as handle:
            handle.write(identifier + LINE_BREAK)
            handle.flush()
            os.fsync(handle.fileno())
        return cls(path=path, flow_id=identifier, lines=[identifier])

    @classmethod
    def load(cls, path: Path, *, captured: list[bytes] | None = None) -> StartLedger:
        """Read and validate every line; missing, truncated or malformed history never becomes an empty ledger."""
        if not path.is_file():
            raise ValueError(DETAIL_MISSING)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ValueError(DETAIL_INVALID.format(detail=type(error).__name__)) from error
        if captured is not None:
            captured.append(data)
        return cls.from_bytes(data, path=path)

    @classmethod
    def from_bytes(cls, data: bytes, *, path: Path) -> StartLedger:
        """Validate a captured immutable byte sequence without opening its source or any report-supplied path."""
        try:
            content = data.decode(ENCODING)
        except UnicodeError as error:
            raise ValueError(DETAIL_INVALID.format(detail=type(error).__name__)) from error
        lines = content.splitlines(keepends=True)
        if not lines or any(not line.endswith(LINE_BREAK) for line in lines):
            raise ValueError(DETAIL_INVALID.format(detail="truncated line"))
        flow_id = lines[0][: -len(LINE_BREAK)]
        if not flow_id or ID_SEPARATOR in flow_id or LINE_BREAK in flow_id:
            raise ValueError(DETAIL_FLOW_ID)
        ledger = cls(path=path, flow_id=flow_id, lines=[flow_id])
        for line_number, raw_line in enumerate(lines[1:], start=2):
            try:
                value = parse_object(raw_line.encode(ENCODING))
            except ValueError as error:
                raise ValueError(DETAIL_INVALID.format(detail="invalid JSON")) from error
            ledger._read_row(value, line_number)
            ledger.lines.append(raw_line[: -len(LINE_BREAK)])
        ledger._validate_parents()
        return ledger

    def declare_case(self, case: str, actions: Sequence[ActionSpec]) -> None:
        """Record the complete closed action list before the case crosses any call or gate."""
        if case in self.closed_lists:
            raise ValueError(DETAIL_DUPLICATE_CASE.format(case=case))
        parsed: dict[str, tuple[str, str | None]] = {}
        rows: list[JsonObject] = []
        for action in actions:
            label = action.get(RECORD_LABEL_FIELD)
            kind = action.get(RECORD_KIND_FIELD)
            parent = action.get(RECORD_PARENT_FIELD)
            if not isinstance(label, str) or not label or kind not in RECORD_KINDS:
                raise ValueError(DETAIL_INVALID.format(detail="invalid closed action list"))
            if label in parsed:
                raise ValueError(DETAIL_INVALID.format(detail="duplicate closed-list label"))
            parsed[label] = (str(kind), parent)
            row: JsonObject = {RECORD_LABEL_FIELD: label, RECORD_KIND_FIELD: kind}
            if parent is not None:
                row[RECORD_PARENT_FIELD] = parent
            rows.append(row)
        self._append(
            {
                RECORD_FIELD: RECORD_CLOSED_LIST,
                RECORD_CASE_FIELD: case,
                RECORD_ACTIONS_FIELD: cast(JsonValue, rows),
            }
        )
        self.closed_lists[case] = parsed

    def begin(self, case: str, label: str, kind: str, parent: str | None = None) -> str:
        """Append and fsync one open attempt before its call or gate is crossed."""
        self._require_declared(case, label, kind, parent)
        parent_id = None
        if parent is not None:
            parents = [
                attempt for attempt in self.attempts.values() if attempt.case == case and attempt.label == parent
            ]
            if len(parents) != 1:
                raise ValueError(DETAIL_PARENT.format(case=case, label=parent))
            parent_id = parents[0].identifier
        line_number = len(self.lines) + LINE_SEQUENCE_START
        identifier = ID_SEPARATOR.join((self.flow_id, case, label, str(line_number)))
        if identifier in self.attempts:
            raise ValueError(DETAIL_DUPLICATE.format(identifier=identifier))
        row: JsonObject = {
            RECORD_ID_FIELD: identifier,
            RECORD_CASE_FIELD: case,
            RECORD_LABEL_FIELD: label,
            RECORD_KIND_FIELD: kind,
            RECORD_STATE_FIELD: RECORD_OPEN,
        }
        if parent_id is not None:
            row[RECORD_PARENT_FIELD] = parent_id
        self._append(row)
        self.attempts[identifier] = Attempt(identifier, case, label, kind, RECORD_OPEN, parent_id)
        return identifier

    def begin_child_before_parent(
        self, case: str, child_label: str, parent_label: str, child_kind: str, parent_kind: str
    ) -> tuple[str, str]:
        """Record an ungated child start before the owner start that causes its plan to run."""
        self._require_declared(case, child_label, child_kind, parent_label)
        self._require_declared(case, parent_label, parent_kind, None)
        child_line = len(self.lines) + LINE_SEQUENCE_START
        parent_line = child_line + 1
        child_id = ID_SEPARATOR.join((self.flow_id, case, child_label, str(child_line)))
        parent_id = ID_SEPARATOR.join((self.flow_id, case, parent_label, str(parent_line)))
        self._append(
            {
                RECORD_ID_FIELD: child_id,
                RECORD_CASE_FIELD: case,
                RECORD_LABEL_FIELD: child_label,
                RECORD_KIND_FIELD: child_kind,
                RECORD_STATE_FIELD: RECORD_OPEN,
                RECORD_PARENT_FIELD: parent_id,
            }
        )
        self._append(
            {
                RECORD_ID_FIELD: parent_id,
                RECORD_CASE_FIELD: case,
                RECORD_LABEL_FIELD: parent_label,
                RECORD_KIND_FIELD: parent_kind,
                RECORD_STATE_FIELD: RECORD_OPEN,
            }
        )
        self.attempts[child_id] = Attempt(child_id, case, child_label, child_kind, RECORD_OPEN, parent_id)
        self.attempts[parent_id] = Attempt(parent_id, case, parent_label, parent_kind, RECORD_OPEN)
        return child_id, parent_id

    def record_operation(self, identifier: str, operation_id: str) -> None:
        """Append a parsed public receipt without discharging an attempt by receipt alone."""
        attempt = self._open(identifier)
        if attempt.kind not in (RECORD_OPERATION, RECORD_TRIGGER) or not operation_id:
            raise ValueError(DETAIL_INVALID.format(detail="operation receipt does not match attempt"))
        if attempt.operation_id is not None:
            raise ValueError(DETAIL_INVALID.format(detail="duplicate operation receipt"))
        self._append({RECORD_ID_FIELD: identifier, RECORD_OPERATION_FIELD: operation_id})
        self.attempts[identifier] = Attempt(
            attempt.identifier,
            attempt.case,
            attempt.label,
            attempt.kind,
            attempt.state,
            attempt.parent,
            operation_id,
            attempt.session_id,
            attempt.evidence,
        )

    def record_session(self, identifier: str, session_id: str) -> None:
        """Append a successful public session id; it stays open until the retained record is closed."""
        attempt = self._open(identifier)
        if attempt.kind != RECORD_SESSION or not session_id or attempt.session_id is not None:
            raise ValueError(DETAIL_INVALID.format(detail="session result does not match attempt"))
        self._append({RECORD_ID_FIELD: identifier, RECORD_SESSION_FIELD: session_id})
        self.attempts[identifier] = Attempt(
            attempt.identifier,
            attempt.case,
            attempt.label,
            attempt.kind,
            attempt.state,
            attempt.parent,
            attempt.operation_id,
            session_id,
            attempt.evidence,
        )

    def record_effect(self, identifier: str, evidence: str) -> None:
        """Bind an observed owned effect to its still-open ledger attempt without settling it."""
        attempt = self._open(identifier)
        if attempt.kind != RECORD_EFFECT or not evidence or attempt.evidence is not None:
            raise ValueError(DETAIL_INVALID.format(detail="effect evidence does not match an open effect"))
        self._append({RECORD_ID_FIELD: identifier, RECORD_EVIDENCE_FIELD: evidence})
        self.attempts[identifier] = Attempt(
            attempt.identifier,
            attempt.case,
            attempt.label,
            attempt.kind,
            attempt.state,
            attempt.parent,
            attempt.operation_id,
            attempt.session_id,
            evidence,
        )

    def unknown(self, identifier: str) -> None:
        """Append an unknown-open classification without manufacturing an operation or session id."""
        attempt = self._open(identifier)
        if attempt.operation_id is not None or attempt.session_id is not None:
            raise ValueError(DETAIL_INVALID.format(detail="unknown attempt already has a public id"))
        self._append({RECORD_ID_FIELD: identifier, RECORD_KIND_FIELD: RECORD_UNKNOWN, RECORD_STATE_FIELD: RECORD_OPEN})
        self.attempts[identifier] = Attempt(
            attempt.identifier,
            attempt.case,
            attempt.label,
            RECORD_UNKNOWN,
            RECORD_OPEN,
            attempt.parent,
            attempt.operation_id,
            attempt.session_id,
            attempt.evidence,
        )

    def discharge(self, identifier: str, evidence: str) -> None:
        """Append public settlement evidence for an operation refusal/claim or a closed session."""
        attempt = self._open(identifier)
        if attempt.kind in (RECORD_TRIGGER, RECORD_UNKNOWN) or not evidence:
            raise ValueError(DETAIL_TRIGGER_DISCHARGE.format(identifier=identifier))
        if attempt.kind == RECORD_OPERATION and attempt.operation_id is None:
            raise ValueError(DETAIL_INVALID.format(detail="operation discharged without a public receipt"))
        if attempt.kind == RECORD_SESSION and attempt.session_id is None:
            raise ValueError(DETAIL_INVALID.format(detail="session discharged without a public session id"))
        self._append(
            {RECORD_ID_FIELD: identifier, RECORD_STATE_FIELD: RECORD_DISCHARGED, RECORD_EVIDENCE_FIELD: evidence}
        )
        self.attempts[identifier] = Attempt(
            attempt.identifier,
            attempt.case,
            attempt.label,
            attempt.kind,
            RECORD_DISCHARGED,
            attempt.parent,
            attempt.operation_id,
            attempt.session_id,
            evidence,
        )

    @property
    def open_attempts(self) -> tuple[Attempt, ...]:
        return tuple(attempt for attempt in self.attempts.values() if attempt.state == RECORD_OPEN)

    def _require_declared(self, case: str, label: str, kind: str, parent: str | None) -> None:
        actions = self.closed_lists.get(case)
        if actions is None:
            raise ValueError(DETAIL_CASE.format(case=case))
        actual = actions.get(label)
        if actual != (kind, parent):
            raise ValueError(DETAIL_ACTION.format(case=case, label=label, kind=kind))

    def _open(self, identifier: str) -> Attempt:
        attempt = self.attempts.get(identifier)
        if attempt is None:
            raise ValueError(DETAIL_UNKNOWN_ID.format(identifier=identifier))
        if attempt.state != RECORD_OPEN:
            raise ValueError(DETAIL_ALREADY_SETTLED.format(identifier=identifier))
        return attempt

    def _append(self, row: JsonObject) -> None:
        encoded = json.dumps(row, separators=(",", ":")) + LINE_BREAK
        with self.path.open("a", encoding=ENCODING) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        self.lines.append(encoded[: -len(LINE_BREAK)])

    def _read_row(self, row: JsonObject, line_number: int) -> None:
        record_type = row.get(RECORD_FIELD)
        if record_type == RECORD_CLOSED_LIST:
            self._read_closed_list(row)
            return
        identifier = row.get(RECORD_ID_FIELD)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(DETAIL_INVALID.format(detail="record id is missing"))
        if row.get(RECORD_KIND_FIELD) == RECORD_UNKNOWN:
            self._read_unknown(row, identifier)
            return
        if (
            RECORD_OPERATION_FIELD in row
            or RECORD_SESSION_FIELD in row
            or (RECORD_EVIDENCE_FIELD in row and row.get(RECORD_STATE_FIELD) != RECORD_DISCHARGED)
        ):
            self._read_answer(row, identifier)
            return
        if row.get(RECORD_STATE_FIELD) == RECORD_DISCHARGED:
            self._read_discharge(row, identifier)
            return
        self._read_open(row, identifier, line_number)

    def _read_closed_list(self, row: JsonObject) -> None:
        if frozenset(row) != frozenset({RECORD_FIELD, RECORD_CASE_FIELD, RECORD_ACTIONS_FIELD}):
            raise ValueError(DETAIL_RECORD_FIELDS)
        case = row.get(RECORD_CASE_FIELD)
        actions = row.get(RECORD_ACTIONS_FIELD)
        if not isinstance(case, str) or case in self.closed_lists or not isinstance(actions, list):
            raise ValueError(DETAIL_INVALID.format(detail="closed action list is malformed"))
        parsed: dict[str, tuple[str, str | None]] = {}
        for action in actions:
            if not isinstance(action, Mapping):
                raise ValueError(DETAIL_INVALID.format(detail="closed action is not an object"))
            label = action.get(RECORD_LABEL_FIELD)
            kind = action.get(RECORD_KIND_FIELD)
            parent = action.get(RECORD_PARENT_FIELD)
            expected = {RECORD_LABEL_FIELD, RECORD_KIND_FIELD}
            if parent is not None:
                expected.add(RECORD_PARENT_FIELD)
            if (
                frozenset(action) != frozenset(expected)
                or not isinstance(label, str)
                or not label
                or kind not in RECORD_KINDS
                or (parent is not None and not isinstance(parent, str))
                or label in parsed
            ):
                raise ValueError(DETAIL_INVALID.format(detail="closed action is malformed"))
            parsed[label] = (str(kind), parent)
        self.closed_lists[case] = parsed

    def _read_open(self, row: JsonObject, identifier: str, line_number: int) -> None:
        expected = {
            RECORD_ID_FIELD,
            RECORD_CASE_FIELD,
            RECORD_LABEL_FIELD,
            RECORD_KIND_FIELD,
            RECORD_STATE_FIELD,
        }
        parent = row.get(RECORD_PARENT_FIELD)
        if parent is not None:
            expected.add(RECORD_PARENT_FIELD)
        parts = identifier.split(ID_SEPARATOR)
        case = row.get(RECORD_CASE_FIELD)
        label = row.get(RECORD_LABEL_FIELD)
        kind = row.get(RECORD_KIND_FIELD)
        state = row.get(RECORD_STATE_FIELD)
        if (
            frozenset(row) != frozenset(expected)
            or identifier in self.attempts
            or len(parts) != 4
            or parts[0] != self.flow_id
            or parts[1] != case
            or parts[2] != label
            or parts[3] != str(line_number)
            or not isinstance(case, str)
            or not isinstance(label, str)
            or kind not in RECORD_KINDS
            or state != RECORD_OPEN
        ):
            raise ValueError(DETAIL_SEQUENCE)
        actions = self.closed_lists.get(case)
        declared = actions.get(label) if actions is not None else None
        parent_parts = parent.split(ID_SEPARATOR) if isinstance(parent, str) else []
        parent_matches = (declared is not None and declared[1] is None and parent is None) or (
            declared is not None
            and declared[1] is not None
            and len(parent_parts) == 4
            and parent_parts[0] == self.flow_id
            and parent_parts[1] == case
            and parent_parts[2] == declared[1]
        )
        if actions is None or declared is None or declared[0] != kind or not parent_matches:
            raise ValueError(DETAIL_ACTION.format(case=case, label=label, kind=kind))
        typed_parent = parent if isinstance(parent, str) else None
        self.attempts[identifier] = Attempt(identifier, case, label, str(kind), str(state), typed_parent)

    def _read_answer(self, row: JsonObject, identifier: str) -> None:
        attempt = self._open(identifier)
        if frozenset(row) == frozenset({RECORD_ID_FIELD, RECORD_EVIDENCE_FIELD}):
            evidence = row.get(RECORD_EVIDENCE_FIELD)
            if (
                attempt.kind != RECORD_EFFECT
                or not isinstance(evidence, str)
                or not evidence
                or attempt.evidence is not None
            ):
                raise ValueError(DETAIL_INVALID.format(detail="effect evidence record is malformed"))
            self.attempts[identifier] = Attempt(
                attempt.identifier,
                attempt.case,
                attempt.label,
                attempt.kind,
                attempt.state,
                attempt.parent,
                attempt.operation_id,
                attempt.session_id,
                evidence,
            )
            return
        if frozenset(row) == frozenset({RECORD_ID_FIELD, RECORD_OPERATION_FIELD}):
            operation_id = row.get(RECORD_OPERATION_FIELD)
            if (
                attempt.kind not in (RECORD_OPERATION, RECORD_TRIGGER)
                or not isinstance(operation_id, str)
                or not operation_id
                or attempt.operation_id is not None
            ):
                raise ValueError(DETAIL_INVALID.format(detail="operation answer is malformed"))
            self.attempts[identifier] = Attempt(
                attempt.identifier,
                attempt.case,
                attempt.label,
                attempt.kind,
                attempt.state,
                attempt.parent,
                operation_id,
                attempt.session_id,
                attempt.evidence,
            )
            return
        if frozenset(row) == frozenset({RECORD_ID_FIELD, RECORD_SESSION_FIELD}):
            session_id = row.get(RECORD_SESSION_FIELD)
            if (
                attempt.kind != RECORD_SESSION
                or not isinstance(session_id, str)
                or not session_id
                or attempt.session_id
            ):
                raise ValueError(DETAIL_INVALID.format(detail="session answer is malformed"))
            self.attempts[identifier] = Attempt(
                attempt.identifier,
                attempt.case,
                attempt.label,
                attempt.kind,
                attempt.state,
                attempt.parent,
                attempt.operation_id,
                session_id,
                attempt.evidence,
            )
            return
        raise ValueError(DETAIL_RECORD_FIELDS)

    def _read_unknown(self, row: JsonObject, identifier: str) -> None:
        attempt = self._open(identifier)
        if (
            frozenset(row) != frozenset({RECORD_ID_FIELD, RECORD_KIND_FIELD, RECORD_STATE_FIELD})
            or attempt.kind == RECORD_UNKNOWN
            or row.get(RECORD_STATE_FIELD) != RECORD_OPEN
        ):
            raise ValueError(DETAIL_INVALID.format(detail="unknown attempt is malformed"))
        self.attempts[identifier] = Attempt(
            attempt.identifier,
            attempt.case,
            attempt.label,
            RECORD_UNKNOWN,
            RECORD_OPEN,
            attempt.parent,
            attempt.operation_id,
            attempt.session_id,
        )

    def _read_discharge(self, row: JsonObject, identifier: str) -> None:
        attempt = self._open(identifier)
        evidence = row.get(RECORD_EVIDENCE_FIELD)
        if (
            frozenset(row) != frozenset({RECORD_ID_FIELD, RECORD_STATE_FIELD, RECORD_EVIDENCE_FIELD})
            or attempt.kind in (RECORD_TRIGGER, RECORD_UNKNOWN)
            or not isinstance(evidence, str)
            or not evidence
            or (attempt.kind == RECORD_SESSION and attempt.session_id is None)
        ):
            raise ValueError(DETAIL_INVALID.format(detail="discharge record is malformed"))
        self.attempts[identifier] = Attempt(
            attempt.identifier,
            attempt.case,
            attempt.label,
            attempt.kind,
            RECORD_DISCHARGED,
            attempt.parent,
            attempt.operation_id,
            attempt.session_id,
            evidence,
        )

    def _validate_parents(self) -> None:
        for attempt in self.attempts.values():
            if attempt.parent is None:
                continue
            parent = self.attempts.get(attempt.parent)
            declared = self.closed_lists.get(attempt.case, {}).get(attempt.label)
            if (
                parent is None
                or parent.case != attempt.case
                or declared is None
                or declared[1] is None
                or parent.label != declared[1]
            ):
                raise ValueError(DETAIL_PARENT.format(case=attempt.case, label=attempt.label))
