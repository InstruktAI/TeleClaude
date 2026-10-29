"""Render and parse compact GitHub comment envelopes around closed workflow records."""

from __future__ import annotations

import json
from collections.abc import Container, Mapping, Sequence
from enum import StrEnum
from typing import Literal

from pydantic import Field

from teleclaude.closed_model import ClosedModel
from teleclaude.core.todos_db._github_artifacts import CommittedArtifact, CommittedEntry

STATE_ARTIFACT_NAME = "workflow-state"
_SCHEMA_VERSION = "schema_version"
_LEGACY_SCHEMA = 1
_NATIVE_SCHEMA = 2
_STATE_CONTENT_POINTER = "state_content_pointer"
_RECORD_MARKER = "<!-- teleclaude:workflow-record:v1:"
_LEDGER_MARKER = "<!-- teleclaude:workflow-ledger:v1:"
_COMMENT_SEPARATOR = " -->\n"
WORKFLOW_COMMENT_BODY_LIMIT = 50_000
_EMPTY = ""
_LINE_BREAK = "\n"
_ENVELOPE_KEY_VALUE_SEPARATOR = ":"
_WORK_ITEM = "work item"
_RECORD_MARKER_MISSING = "Workflow record marker is missing"
_NON_SCALAR_FIELD = "Workflow snapshot contains a non-scalar field"
_JSON_AMPERSAND = "&"
_JSON_LT = "<"
_JSON_GT = ">"
_JSON_AMP_ESCAPE = "\\u0026"
_JSON_LT_ESCAPE = "\\u003c"
_JSON_GT_ESCAPE = "\\u003e"
_COMMENT_CLOSE = " -->"
_ENVELOPE_OPEN = "["
_ENVELOPE_CLOSE = "]"
_ENVELOPE_SEPARATOR = " "


class CommentEnvelopeField(StrEnum):
    """Closed set of visible fields allowed in a workflow comment envelope."""

    ACTION = "action"
    PHASE = "phase"
    REVISION = "rev"
    SESSION = "session"
    ROLE = "role"
    HOLD = "hold"
    COMMIT = "commit"
    TRANSACTION = "tx"
    PART = "part"
    NAME = "name"
    VERSION = "version"
    ISSUE = "issue"
    ROUND = "round"
    COMPUTER = "computer"
    PROJECT = "project"
    REPOSITORY = "repository"


class CommentEnvelopeAction(StrEnum):
    """Closed set of event kinds exposed in a workflow comment envelope."""

    RECORD = "record"
    LEDGER = "ledger"
    ARTIFACT = "artifact"
    ARTIFACT_REMOVED = "artifact-removed"
    QUESTION = "question"
    PULL_REQUEST = "pull-request"
    REVIEW = "review"
    DELIVERED = "delivered"
    BOARD = "board"
    BOARD_CLAIM = "board-claim"


_ACTION_FIELD = CommentEnvelopeField.ACTION
_PHASE_FIELD = CommentEnvelopeField.PHASE
_REV_FIELD = CommentEnvelopeField.REVISION
_SESSION_FIELD = CommentEnvelopeField.SESSION
_ROLE_FIELD = CommentEnvelopeField.ROLE
_HOLD_FIELD = CommentEnvelopeField.HOLD
_COMMIT_FIELD = CommentEnvelopeField.COMMIT
_TX_FIELD = CommentEnvelopeField.TRANSACTION
_RECORD_ACTION = CommentEnvelopeAction.RECORD
_LEDGER_ACTION = CommentEnvelopeAction.LEDGER


class WorkflowField(StrEnum):
    """Closed set of serialized workflow field names read by this module."""

    SLUG = "slug"
    LINEAGE = "lineage"
    DEPENDS_ON = "depends_on"
    LIFECYCLE_PHASE = "lifecycle_phase"
    ACTIVE_RUNNER = "active_runner"
    DELIVERED_COMMIT = "delivered_commit"
    CREATED_AT = "created_at"
    EDITOR = "editor"
    LOGIN = "login"
    DELETED_AT = "deletedAt"
    DIFF = "diff"
    STATUS = "status"
    STATE = "state"
    HOLD_AUDIT = "hold_audit"
    REASON = "reason"
    ID = "id"
    NAME = "name"
    VERSION_ID = "version_id"
    DIGEST = "digest"
    CONTENT = "content"
    UPDATED_BY = "updated_by"
    UPDATED_AT = "updated_at"
    ISSUE_NUMBER = "issue_number"
    BASE_REVISION = "base_revision"
    ITEM_ID = "item_id"
    ISSUE_WATERMARK = "issue_watermark"
    LEDGER_WATERMARK = "ledger_watermark"
    LEDGER_ISSUE_NUMBER = "ledger_issue_number"
    NODE_ID = "node_id"
    RECORD_COMMENT_ID = "record_comment_id"
    REVISION = "revision"
    TODO = "todo"
    ARTIFACTS = "artifacts"
    TITLE = "title"
    PRESENT = "present"
    COMMITTED = "committed"
    PENDING = "pending"


class WorkflowTodoStatus(StrEnum):
    """Workflow status values used to reflect removed and delivered items."""

    ACTIVE = "active"
    DELIVERED = "delivered"
    REMOVED = "removed"
    PURGED = "purged"


Scalar = str | int | float | bool | None
Row = dict[str, Scalar]


class LedgerRecordTable(StrEnum):
    """Closed set of append-only project record tables carried by the ledger."""

    COMMIT_REVIEW = "commit_review"
    DOCUMENTATION_TRANSFER = "documentation_transfer"


class ArtifactVersionEntry(ClosedModel):
    """One saved artifact version a committed record names: its place in the artifact's history and its digest.

    GitHub records only which account saved a version and when, and every platform save carries the same App, so
    the workflow writer and the version's original time live here.
    """

    ordinal: int = Field(ge=1)
    digest: str
    updated_by: str | None = None
    created_at: str | None = None


class ArtifactRecord(ClosedModel):
    """Where one workflow artifact lives on the issue and the versions GitHub still serves of it, oldest first."""

    artifact_number: int = Field(gt=0)
    present: bool = True
    entries: list[ArtifactVersionEntry] = Field(default_factory=list)


class ItemRevision(ClosedModel):
    """One complete committed snapshot of a work item."""

    item_id: str
    revision: int = Field(ge=0)
    todo: Row
    state: Row | None = None
    state_content_pointer: ArtifactRecord | None = None
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    artifacts: dict[str, ArtifactRecord] = Field(default_factory=dict)


class PendingRevision(ClosedModel):
    """Revision awaiting its enclosing repository ledger commit point."""

    transaction_id: str
    revision: ItemRevision


class WorkflowRecord(ClosedModel):
    """Machine record carried by the platform-owned issue comment."""

    schema_version: Literal[1, 2] = 2
    committed: ItemRevision
    pending: PendingRevision | None = None

    @property
    def native_artifacts(self) -> bool:
        """Whether the record names its artifacts as native issue artifacts."""
        return self.schema_version == _NATIVE_SCHEMA


class LedgerItem(ClosedModel):
    """Issue and revision made effective by one repository transaction."""

    issue_number: int = Field(gt=0)
    revision: int = Field(ge=0)


class LedgerProjectRecord(ClosedModel):
    """Project-level review or transfer row made effective by a transaction."""

    table: LedgerRecordTable
    row_id: int = Field(gt=0)
    remote_record_id: str | None = None
    data: Row


class LedgerCommit(ClosedModel):
    """One atomic store transaction represented by a single ledger comment."""

    transaction_id: str
    items: list[LedgerItem] = Field(default_factory=list)
    project_records: list[LedgerProjectRecord] = Field(default_factory=list)


def make_item_revision(
    item_id: str,
    revision: int,
    todo: Mapping[str, object],
    state: Mapping[str, object] | None,
    dependencies: Sequence[Mapping[str, object]],
    artifact_records: Mapping[str, ArtifactRecord],
    state_content_pointer: ArtifactRecord | None = None,
) -> ItemRevision:
    """Build the closed serializable snapshot model from database row values."""
    return ItemRevision(
        item_id=item_id,
        revision=revision,
        todo=_scalar_row(todo),
        state=_scalar_row(state) if state is not None else None,
        state_content_pointer=state_content_pointer,
        dependencies=[{str(key): str(value) for key, value in row.items()} for row in dependencies],
        artifacts=dict(artifact_records),
    )


def render_record_comment(record: WorkflowRecord, effective_state: Mapping[str, object] | None = None) -> str:
    """Render a concise issue envelope plus a bounded encoded machine record."""
    payload_line = _RECORD_MARKER + _safe_json(record.model_dump_json()) + _COMMENT_CLOSE
    return _render_record_comment(record, effective_state, payload_line)


def _render_record_comment(
    record: WorkflowRecord,
    effective_state: Mapping[str, object] | None,
    payload_line: str,
) -> str:
    revision = record.pending.revision if record.pending is not None else record.committed
    todo = revision.todo
    audit = effective_state.get(WorkflowField.HOLD_AUDIT) if effective_state is not None else None
    hold_reason = audit.get(WorkflowField.REASON) if isinstance(audit, Mapping) else None
    envelope = render_comment_envelope(
        (
            (_ACTION_FIELD, _RECORD_ACTION),
            (_PHASE_FIELD, _value_or_none(effective_state, WorkflowField.LIFECYCLE_PHASE)),
            (_REV_FIELD, revision.revision),
            (_SESSION_FIELD, _value_or_none(effective_state, WorkflowField.ACTIVE_RUNNER)),
            (_HOLD_FIELD, effective_state.get(_HOLD_FIELD) is True if effective_state is not None else False),
            (_COMMIT_FIELD, todo.get(WorkflowField.DELIVERED_COMMIT)),
        )
    )
    visible = [envelope]
    if (
        effective_state is not None
        and effective_state.get(_HOLD_FIELD) is True
        and isinstance(hold_reason, str)
        and hold_reason
    ):
        visible.append(hold_reason)
    return _LINE_BREAK.join(visible) + _LINE_BREAK + payload_line + _LINE_BREAK


def reenvelope_record_comment(
    body: str, record: WorkflowRecord, effective_state: Mapping[str, object] | None = None
) -> str:
    """Replace only a record comment's readable prefix, preserving its exact machine payload."""
    payload_line = _RECORD_MARKER + _marker_payload(body, _RECORD_MARKER) + _COMMENT_CLOSE
    return _render_record_comment(record, effective_state, payload_line)


def parse_record_comment(body: str) -> WorkflowRecord:
    """Decode one platform record from its marker and validate its closed schema.

    A schema-1 record parses with its content pointers dropped: its item is not yet republished.
    """
    values = json.loads(_marker_payload(body, _RECORD_MARKER))
    if isinstance(values, dict) and values.get(_SCHEMA_VERSION) == _LEGACY_SCHEMA:
        for revision in (values.get(WorkflowField.COMMITTED), _pending_revision(values)):
            if isinstance(revision, dict):
                revision.pop(WorkflowField.ARTIFACTS, None)
                revision.pop(_STATE_CONTENT_POINTER, None)
    return WorkflowRecord.model_validate(values)


def committed_artifacts(revision: ItemRevision) -> tuple[CommittedArtifact, ...]:
    """The artifacts a revision names, in the form the working copy mirrors; a removed artifact is not named."""
    records = [*revision.artifacts.items()]
    if revision.state_content_pointer is not None:
        records.append((STATE_ARTIFACT_NAME, revision.state_content_pointer))
    return tuple(
        CommittedArtifact(
            name,
            record.artifact_number,
            tuple(
                CommittedEntry(entry.ordinal, entry.digest, entry.updated_by, entry.created_at)
                for entry in record.entries
            ),
        )
        for name, record in records
        if record.present
    )


def render_ledger_commit(commit: LedgerCommit) -> str:
    """Render one concise ledger envelope and its hidden machine transaction."""
    payload = _safe_json(commit.model_dump_json())
    envelope = render_comment_envelope(((_ACTION_FIELD, _LEDGER_ACTION), (_TX_FIELD, commit.transaction_id)))
    return envelope + _LINE_BREAK + _LEDGER_MARKER + payload + _COMMENT_SEPARATOR


def reenvelope_ledger_comment(body: str, commit: LedgerCommit) -> str:
    """Replace only a ledger comment's readable prefix, preserving its exact machine payload."""
    payload_line = _LEDGER_MARKER + _marker_payload(body, _LEDGER_MARKER) + _COMMENT_CLOSE
    envelope = render_comment_envelope(((_ACTION_FIELD, _LEDGER_ACTION), (_TX_FIELD, commit.transaction_id)))
    return envelope + _LINE_BREAK + payload_line + _LINE_BREAK


def render_comment_envelope(fields: Sequence[tuple[CommentEnvelopeField, Scalar]]) -> str:
    """Render structured non-empty comment fields in their supplied order."""
    rendered: list[str] = []
    for key, value in fields:
        if value is None or value is False or value == _EMPTY:
            continue
        rendered.append(key if value is True else f"{key}{_ENVELOPE_KEY_VALUE_SEPARATOR}{value}")
    return _ENVELOPE_OPEN + _ENVELOPE_SEPARATOR.join(rendered) + _ENVELOPE_CLOSE


def comment_envelope_fields(body: str) -> dict[str, str]:
    """Read the `key:value` fields of the envelope a comment or body opens with; empty when it has none."""
    line = body.split(_LINE_BREAK, 1)[0].strip()
    if not (line.startswith(_ENVELOPE_OPEN) and line.endswith(_ENVELOPE_CLOSE)):
        return {}
    fields: dict[str, str] = {}
    for part in line[1:-1].split(_ENVELOPE_SEPARATOR):
        key, separator, value = part.partition(_ENVELOPE_KEY_VALUE_SEPARATOR)
        if separator:
            fields[key] = value
    return fields


def _pending_revision(values: Mapping[str, object]) -> object:
    pending = values.get(WorkflowField.PENDING)
    return pending.get(WorkflowField.REVISION) if isinstance(pending, dict) else None


def parse_ledger_commit(body: str) -> LedgerCommit:
    """Decode a trusted ledger transaction."""
    return LedgerCommit.model_validate_json(_marker_payload(body, _LEDGER_MARKER))


def effective_revision(record: WorkflowRecord, committed_transactions: Container[str]) -> ItemRevision:
    """Apply a pending snapshot only when its transaction has a ledger commit entry."""
    pending = record.pending
    if pending is not None and pending.transaction_id in committed_transactions:
        return pending.revision
    return record.committed


def trusted_comment_body(
    *,
    author: str | None,
    editor: str | None,
    body: str,
    edits: Sequence[Mapping[str, object]],
    history_complete: bool,
    bot_login: str,
) -> str | None:
    """Return the bot's latest write, refusing non-bot authors and incomplete recovery."""
    if author != bot_login:
        return None
    if editor is None or editor == bot_login:
        return body
    if not history_complete:
        return None
    for edit in edits:
        actor = edit.get(WorkflowField.EDITOR)
        login = actor.get(WorkflowField.LOGIN) if isinstance(actor, Mapping) else None
        if login != bot_login:
            continue
        if edit.get(WorkflowField.DELETED_AT) is not None:
            return None
        diff = edit.get(WorkflowField.DIFF)
        return diff if isinstance(diff, str) else None
    return None


def has_record_marker(body: str) -> bool:
    """Tell whether a trusted comment carries a record marker line."""
    return _has_marker_line(body, _RECORD_MARKER)


def has_ledger_marker(body: str) -> bool:
    """Tell whether a trusted comment carries a ledger marker line."""
    return _has_marker_line(body, _LEDGER_MARKER)


def _marker_payload(body: str, marker: str) -> str:
    for line in body.splitlines():
        if line.startswith(marker) and line.endswith(_COMMENT_CLOSE):
            return line[len(marker) : -4]
    raise ValueError(_RECORD_MARKER_MISSING)


def _safe_json(serialized: str) -> str:
    """Keep a readable JSON machine block inside an HTML comment."""
    return (
        serialized.replace(_JSON_AMPERSAND, _JSON_AMP_ESCAPE)
        .replace(_JSON_LT, _JSON_LT_ESCAPE)
        .replace(_JSON_GT, _JSON_GT_ESCAPE)
    )


def _has_marker_line(body: str, marker: str) -> bool:
    return any(line.startswith(marker) and line.endswith(_COMMENT_CLOSE) for line in body.splitlines())


def _scalar_row(row: Mapping[str, object] | None) -> Row:
    if row is None:
        return {}
    result: Row = {}
    for key, value in row.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            result[str(key)] = value
        else:
            raise ValueError(_NON_SCALAR_FIELD)
    return result


def _value_or_none(values: Mapping[str, object] | None, name: str) -> str | None:
    value = values.get(name) if values is not None else None
    return str(value) if value is not None else None
