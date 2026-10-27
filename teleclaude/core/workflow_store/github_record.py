"""Render and parse compact GitHub comment envelopes around closed workflow records."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field

from teleclaude.closed_model import ClosedModel

_RECORD_MARKER = "<!-- teleclaude:workflow-record:v1:"
_LEDGER_MARKER = "<!-- teleclaude:workflow-ledger:v1:"
_CONTENT_MARKER = "<!-- teleclaude:workflow-content:v1:"
_HISTORY_MARKER = "<!-- teleclaude:workflow-artifact-history:v1:"
_COMMENT_SEPARATOR = " -->\n"
WORKFLOW_COMMENT_BODY_LIMIT = 50_000
_CONTENT_CHUNK_SIZE = 50_000
_ENCODING = "utf-8"
_EMPTY = ""
_LINE_BREAK = "\n"
_LINE_ENDINGS = "\r\n"
_ENVELOPE_KEY_VALUE_SEPARATOR = ":"
_PART_INDEX_SEPARATOR = "/"
_WORK_ITEM = "work item"
_ASCII = "ascii"
_CONTENT_MARKER_INCOMPLETE = "Workflow content marker is incomplete"
_CONTENT_MARKER_MISSING = "Workflow content marker is missing"
_CONTENT_NO_PARTS = "Workflow content has no parts"
_CONTENT_PARTS_INCOMPLETE = "Workflow content parts are incomplete"
_CONTENT_PARTS_DISAGREE = "Workflow content parts disagree"
_CONTENT_DIGEST_MISMATCH = "Workflow content digest does not match"
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
_ENVELOPE_LINE_SEPARATOR = "\n"


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


_ACTION_FIELD = CommentEnvelopeField.ACTION
_PHASE_FIELD = CommentEnvelopeField.PHASE
_REV_FIELD = CommentEnvelopeField.REVISION
_SESSION_FIELD = CommentEnvelopeField.SESSION
_ROLE_FIELD = CommentEnvelopeField.ROLE
_HOLD_FIELD = CommentEnvelopeField.HOLD
_COMMIT_FIELD = CommentEnvelopeField.COMMIT
_TX_FIELD = CommentEnvelopeField.TRANSACTION
_PART_FIELD = CommentEnvelopeField.PART
_NAME_FIELD = CommentEnvelopeField.NAME
_VERSION_FIELD = CommentEnvelopeField.VERSION
_RECORD_ACTION = CommentEnvelopeAction.RECORD
_LEDGER_ACTION = CommentEnvelopeAction.LEDGER
_HISTORY_CHAIN_INCOMPLETE = "Artifact history chain is incomplete"
_HISTORY_CHAIN_CYCLE = "Artifact history chain contains a cycle"
_HISTORY_IDENTITY_MISMATCH = "Artifact history identity does not match its pointer"


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
    REMOTE_VERSION_ID = "remote_version_id"
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
    COMMENT_IDS = "comment_ids"
    HEAD_COMMENT_ID = "head_comment_id"
    METADATA = "metadata"
    PRESENT = "present"


class WorkflowTodoStatus(StrEnum):
    """Workflow status values used to reflect removed and delivered items."""

    ACTIVE = "active"
    DELIVERED = "delivered"
    REMOVED = "removed"
    PURGED = "purged"


class ArtifactHistoryAction(StrEnum):
    """Artifact history events recorded outside the bounded current record."""

    VERSION = "version"
    REMOVED = "removed"


Scalar = str | int | float | bool | None
Row = dict[str, Scalar]


class LedgerRecordTable(StrEnum):
    """Closed set of append-only project record tables carried by the ledger."""

    COMMIT_REVIEW = "commit_review"
    DOCUMENTATION_TRANSFER = "documentation_transfer"


class ArtifactPointer(ClosedModel):
    """References the append-only comments for one artifact version."""

    digest: str
    version: int
    remote_version_id: str | None = None
    head_comment_id: int | None = None
    present: bool = True
    comment_ids: list[int] = Field(default_factory=list)
    metadata: Row = Field(default_factory=dict)


class ItemRevision(ClosedModel):
    """One complete committed snapshot of a work item."""

    item_id: str
    revision: int = Field(ge=0)
    todo: Row
    state: Row | None = None
    state_content_pointer: ArtifactPointer | None = None
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    artifacts: dict[str, list[ArtifactPointer]] = Field(default_factory=dict)


class PendingRevision(ClosedModel):
    """Revision awaiting its enclosing repository ledger commit point."""

    transaction_id: str
    revision: ItemRevision


class WorkflowRecord(ClosedModel):
    """Machine record carried by the platform-owned issue comment."""

    schema_version: Literal[1] = 1
    committed: ItemRevision
    pending: PendingRevision | None = None


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


class ContentHeader(ClosedModel):
    """Identity and digest for one part of an artifact or state comment."""

    item_id: str
    name: str
    version: str | int
    digest: str
    part: int = Field(ge=1)
    parts: int = Field(ge=1)


class ArtifactHistoryNode(ClosedModel):
    """One bounded append-only artifact-version link in the issue comment history."""

    item_id: str
    name: str
    action: ArtifactHistoryAction = ArtifactHistoryAction.VERSION
    remote_version_id: str | None = None
    digest: str | None = None
    metadata: Row = Field(default_factory=dict)
    previous_comment_id: int | None = None
    legacy_comment_ids: list[int] = Field(default_factory=list)


class HistoryComment(Protocol):
    """Comment attributes needed to authenticate an artifact history chain."""

    @property
    def database_id(self) -> int: ...

    @property
    def body(self) -> str: ...

    @property
    def author(self) -> str | None: ...

    @property
    def editor(self) -> str | None: ...

    @property
    def edit_history(self) -> Sequence[Mapping[str, object]]: ...

    @property
    def history_complete(self) -> bool: ...


@dataclass(frozen=True)
class ResolvedArtifactVersion:
    """One version and content recovered from an artifact pointer chain."""

    pointer: ArtifactPointer
    content: str
    head_comment_id: int | None
    content_comment_ids: tuple[int, ...]
    action: ArtifactHistoryAction = ArtifactHistoryAction.VERSION


ContentGroupKey = tuple[str, str, str | int, str]
ContentGroupValue = tuple[int, ContentHeader, str]


def make_item_revision(
    item_id: str,
    revision: int,
    todo: Mapping[str, object],
    state: Mapping[str, object] | None,
    dependencies: Sequence[Mapping[str, object]],
    artifact_pointers: Mapping[str, list[ArtifactPointer]],
    state_content_pointer: ArtifactPointer | None = None,
) -> ItemRevision:
    """Build the closed serializable snapshot model from database row values."""
    return ItemRevision(
        item_id=item_id,
        revision=revision,
        todo=_scalar_row(todo),
        state=_scalar_row(state) if state is not None else None,
        state_content_pointer=state_content_pointer,
        dependencies=[{str(key): str(value) for key, value in row.items()} for row in dependencies],
        artifacts=dict(artifact_pointers),
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
    """Decode one platform record from its marker and validate its closed schema."""
    return WorkflowRecord.model_validate_json(_marker_payload(body, _RECORD_MARKER))


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


def reenvelope_artifact_history_comment(
    body: str, envelope_fields: Sequence[tuple[CommentEnvelopeField, Scalar]]
) -> str:
    """Add a readable envelope while preserving an artifact history payload byte-for-byte."""
    payload_line = _HISTORY_MARKER + _marker_payload(body, _HISTORY_MARKER) + _COMMENT_CLOSE
    return render_comment_envelope(envelope_fields) + _LINE_BREAK + payload_line + _LINE_BREAK


def render_comment_envelope(fields: Sequence[tuple[CommentEnvelopeField, Scalar]]) -> str:
    """Render structured non-empty comment fields in their supplied order."""
    rendered: list[str] = []
    for key, value in fields:
        if value is None or value is False or value == _EMPTY:
            continue
        rendered.append(key if value is True else f"{key}{_ENVELOPE_KEY_VALUE_SEPARATOR}{value}")
    return _ENVELOPE_OPEN + _ENVELOPE_SEPARATOR.join(rendered) + _ENVELOPE_CLOSE


def artifact_version_envelope_fields(name: str, ordinal: int) -> tuple[tuple[CommentEnvelopeField, Scalar], ...]:
    """Return the closed envelope fields for one artifact version."""
    return (
        (_ACTION_FIELD, CommentEnvelopeAction.ARTIFACT),
        (_NAME_FIELD, name),
        (_VERSION_FIELD, ordinal),
    )


def state_version_envelope_fields(revision: int) -> tuple[tuple[CommentEnvelopeField, Scalar], ...]:
    """Return the closed envelope fields for one workflow state version."""
    return ((_ACTION_FIELD, _RECORD_ACTION), (_REV_FIELD, revision))


def parse_ledger_commit(body: str) -> LedgerCommit:
    """Decode a trusted ledger transaction."""
    return LedgerCommit.model_validate_json(_marker_payload(body, _LEDGER_MARKER))


def render_artifact_history_node(
    node: ArtifactHistoryNode,
    *,
    envelope_fields: Sequence[tuple[CommentEnvelopeField, Scalar]] | None = None,
) -> str:
    """Render one bounded history link, optionally as a standalone enveloped comment."""
    payload = _HISTORY_MARKER + _safe_json(node.model_dump_json()) + _COMMENT_CLOSE
    if envelope_fields is None:
        return payload + _LINE_BREAK
    return render_comment_envelope(envelope_fields) + _LINE_BREAK + payload + _LINE_BREAK


def render_standalone_artifact_history_comment(node: ArtifactHistoryNode, version_ordinal: int | None = None) -> str:
    """Render an artifact history event with its readable standalone-comment envelope."""
    fields: tuple[tuple[CommentEnvelopeField, Scalar], ...]
    if node.action is ArtifactHistoryAction.REMOVED:
        fields = ((_ACTION_FIELD, CommentEnvelopeAction.ARTIFACT_REMOVED), (_NAME_FIELD, node.name))
    else:
        if version_ordinal is None:
            raise ValueError(_HISTORY_IDENTITY_MISMATCH)
        fields = (
            (_ACTION_FIELD, CommentEnvelopeAction.ARTIFACT),
            (_NAME_FIELD, node.name),
            (_VERSION_FIELD, version_ordinal),
        )
    return render_artifact_history_node(node, envelope_fields=fields)


def parse_artifact_history_node(body: str) -> ArtifactHistoryNode:
    """Decode a trusted artifact-history link."""
    return ArtifactHistoryNode.model_validate_json(_marker_payload(body, _HISTORY_MARKER))


def effective_revision(record: WorkflowRecord, committed_transactions: Container[str]) -> ItemRevision:
    """Apply a pending snapshot only when its transaction has a ledger commit entry."""
    pending = record.pending
    if pending is not None and pending.transaction_id in committed_transactions:
        return pending.revision
    return record.committed


def latest_artifact_pointer(pointers: Sequence[ArtifactPointer]) -> ArtifactPointer:
    """Select the latest source version using its persisted creation time."""
    return max(
        pointers,
        key=lambda pointer: (
            str(pointer.metadata.get(WorkflowField.CREATED_AT) or _EMPTY),
            pointer.remote_version_id or str(pointer.version),
        ),
    )


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


def resolve_artifact_history(
    pointer: ArtifactPointer,
    item_id: str,
    name: str,
    comments: Sequence[HistoryComment],
    bot_login: str,
) -> tuple[ResolvedArtifactVersion, ...]:
    """Recover one artifact's committed version chain from its current record pointer."""
    by_id = {comment.database_id: comment for comment in comments}
    content_groups = _content_groups(comments, bot_login)
    if pointer.head_comment_id is None:
        content, content_comment_ids = _legacy_pointer_content(pointer, item_id, name, by_id, bot_login)
        return (
            ResolvedArtifactVersion(
                pointer,
                content,
                pointer.comment_ids[0] if pointer.comment_ids else None,
                content_comment_ids,
            ),
        )
    resolved: list[ResolvedArtifactVersion] = []
    visited: set[int] = set()
    comment_id: int | None = pointer.head_comment_id
    first_node = True
    while comment_id is not None:
        if comment_id in visited:
            raise ValueError(_HISTORY_CHAIN_CYCLE)
        visited.add(comment_id)
        comment = by_id.get(comment_id)
        trusted = trusted_comment_body(
            author=comment.author if comment is not None else None,
            editor=comment.editor if comment is not None else None,
            body=comment.body if comment is not None else _EMPTY,
            edits=comment.edit_history if comment is not None else (),
            history_complete=comment.history_complete if comment is not None else False,
            bot_login=bot_login,
        )
        if trusted is None:
            raise ValueError(_HISTORY_CHAIN_INCOMPLETE)
        node = parse_artifact_history_node(trusted)
        if node.item_id != item_id or node.name != name:
            raise ValueError(_HISTORY_IDENTITY_MISMATCH)
        if node.action is ArtifactHistoryAction.REMOVED:
            resolved.append(
                ResolvedArtifactVersion(
                    pointer.model_copy(update={WorkflowField.PRESENT: False}),
                    _EMPTY,
                    comment_id,
                    (),
                    ArtifactHistoryAction.REMOVED,
                )
            )
            comment_id = node.previous_comment_id
            first_node = False
            continue
        if (
            node.remote_version_id is None
            or node.digest is None
            or (first_node and node.digest != pointer.digest)
            or (first_node and pointer.remote_version_id not in (None, node.remote_version_id))
        ):
            raise ValueError(_HISTORY_IDENTITY_MISMATCH)
        content, content_comment_ids = _history_node_content(node, by_id, content_groups, bot_login)
        version_value = node.metadata.get(WorkflowField.VERSION_ID)
        version = version_value if isinstance(version_value, int) else pointer.version
        resolved_pointer = ArtifactPointer(
            digest=node.digest,
            version=version,
            remote_version_id=node.remote_version_id,
            head_comment_id=comment_id,
            comment_ids=list(node.legacy_comment_ids),
            metadata=dict(node.metadata),
        )
        resolved.append(ResolvedArtifactVersion(resolved_pointer, content, comment_id, content_comment_ids))
        comment_id = node.previous_comment_id
        first_node = False
    return tuple(resolved)


def _legacy_pointer_content(
    pointer: ArtifactPointer,
    item_id: str,
    name: str,
    by_id: Mapping[int, HistoryComment],
    bot_login: str,
) -> tuple[str, tuple[int, ...]]:
    parts: list[tuple[ContentHeader, str]] = []
    for comment_id in pointer.comment_ids:
        comment = by_id.get(comment_id)
        trusted = trusted_comment_body(
            author=comment.author if comment is not None else None,
            editor=comment.editor if comment is not None else None,
            body=comment.body if comment is not None else _EMPTY,
            edits=comment.edit_history if comment is not None else (),
            history_complete=comment.history_complete if comment is not None else False,
            bot_login=bot_login,
        )
        if trusted is None:
            raise ValueError(_HISTORY_CHAIN_INCOMPLETE)
        header, content = parse_content_comment(trusted)
        if (
            header.item_id != item_id
            or header.name != name
            or header.version != (pointer.remote_version_id or pointer.version)
            or header.digest != pointer.digest
        ):
            raise ValueError(_HISTORY_IDENTITY_MISMATCH)
        parts.append((header, content))
    return join_content_comments(parts), tuple(pointer.comment_ids)


def _history_node_content(
    node: ArtifactHistoryNode,
    by_id: Mapping[int, HistoryComment],
    content_groups: Mapping[ContentGroupKey, Sequence[ContentGroupValue]],
    bot_login: str,
) -> tuple[str, tuple[int, ...]]:
    if node.legacy_comment_ids:
        parts: list[tuple[ContentHeader, str]] = []
        expected_version = node.metadata.get(WorkflowField.VERSION_ID)
        for comment_id in node.legacy_comment_ids:
            comment = by_id.get(comment_id)
            trusted = trusted_comment_body(
                author=comment.author if comment is not None else None,
                editor=comment.editor if comment is not None else None,
                body=comment.body if comment is not None else _EMPTY,
                edits=comment.edit_history if comment is not None else (),
                history_complete=comment.history_complete if comment is not None else False,
                bot_login=bot_login,
            )
            if trusted is None:
                raise ValueError(_HISTORY_CHAIN_INCOMPLETE)
            header, content = parse_content_comment(trusted)
            if (
                header.item_id != node.item_id
                or header.name != node.name
                or header.version != expected_version
                or header.digest != node.digest
            ):
                raise ValueError(_HISTORY_IDENTITY_MISMATCH)
            parts.append((header, content))
        return join_content_comments(parts), tuple(node.legacy_comment_ids)
    if node.remote_version_id is None or node.digest is None:
        raise ValueError(_HISTORY_IDENTITY_MISMATCH)
    group = content_groups.get((node.item_id, node.name, node.remote_version_id, node.digest), ())
    parts = [(header, content) for _comment_id, header, content in group]
    return join_content_comments(parts), tuple(comment_id for comment_id, _header, _content in group)


def _content_groups(
    comments: Sequence[HistoryComment], bot_login: str
) -> dict[ContentGroupKey, list[ContentGroupValue]]:
    groups: dict[ContentGroupKey, list[ContentGroupValue]] = {}
    for comment in comments:
        body = trusted_comment_body(
            author=comment.author,
            editor=comment.editor,
            body=comment.body,
            edits=comment.edit_history,
            history_complete=comment.history_complete,
            bot_login=bot_login,
        )
        if body is None or not is_content_comment(body):
            continue
        try:
            header, content = parse_content_comment(body)
        except ValueError:
            continue
        key = (header.item_id, header.name, header.version, header.digest)
        groups.setdefault(key, []).append((comment.database_id, header, content))
    return groups


def split_content_comments(
    item_id: str,
    name: str,
    version: str | int,
    digest: str,
    content: str,
    *,
    envelope_fields: Sequence[tuple[CommentEnvelopeField, Scalar]] = (),
    history_node: ArtifactHistoryNode | None = None,
) -> tuple[str, ...]:
    """Split content into bounded comments whose parts join to the original bytes."""
    chunks = tuple(
        content[index : index + _CONTENT_CHUNK_SIZE] for index in range(0, len(content), _CONTENT_CHUNK_SIZE)
    )
    if not chunks:
        chunks = (_EMPTY,)
    bodies: list[str] = []
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        header = ContentHeader(item_id=item_id, name=name, version=version, digest=digest, part=index, parts=total)
        encoded = base64.urlsafe_b64encode(header.model_dump_json().encode(_ENCODING)).decode(_ASCII)
        prefix: list[str] = []
        if envelope_fields:
            fields = (
                (*envelope_fields, (_PART_FIELD, f"{index}{_PART_INDEX_SEPARATOR}{total}"))
                if total > 1
                else envelope_fields
            )
            prefix.append(render_comment_envelope(fields))
        if index == total and history_node is not None:
            prefix.append(render_artifact_history_node(history_node).rstrip(_LINE_BREAK))
        prefix.append(_CONTENT_MARKER + encoded + _COMMENT_SEPARATOR + chunk)
        bodies.append(_ENVELOPE_LINE_SEPARATOR.join(prefix))
    return tuple(bodies)


def split_artifact_version_comments(
    item_id: str,
    name: str,
    version: str | int,
    digest: str,
    content: str,
    ordinal: int,
    history_node: ArtifactHistoryNode,
) -> tuple[str, ...]:
    """Render one artifact version with its visible envelope and hidden history link."""
    return split_content_comments(
        item_id,
        name,
        version,
        digest,
        content,
        envelope_fields=artifact_version_envelope_fields(name, ordinal),
        history_node=history_node,
    )


def split_state_version_comments(
    item_id: str,
    name: str,
    revision: int,
    digest: str,
    content: str,
) -> tuple[str, ...]:
    """Render one workflow state version with its visible record envelope."""
    return split_content_comments(
        item_id,
        name,
        revision,
        digest,
        content,
        envelope_fields=state_version_envelope_fields(revision),
    )


def render_enveloped_content_comment(
    header: ContentHeader,
    content: str,
    envelope_fields: Sequence[tuple[CommentEnvelopeField, Scalar]],
    history_node: ArtifactHistoryNode | None = None,
    history_payload_line: str | None = None,
) -> str:
    """Backfill one existing content part without changing its identity or payload bytes."""
    fields = (
        (*envelope_fields, (_PART_FIELD, f"{header.part}{_PART_INDEX_SEPARATOR}{header.parts}"))
        if header.parts > 1
        else envelope_fields
    )
    encoded = base64.urlsafe_b64encode(header.model_dump_json().encode(_ENCODING)).decode(_ASCII)
    prefix = [render_comment_envelope(fields)]
    if history_payload_line is not None:
        prefix.append(history_payload_line)
    elif history_node is not None:
        prefix.append(render_artifact_history_node(history_node).rstrip(_LINE_BREAK))
    prefix.append(_CONTENT_MARKER + encoded + _COMMENT_SEPARATOR + content)
    return _ENVELOPE_LINE_SEPARATOR.join(prefix)


def artifact_history_payload_line(body: str) -> str:
    """Return the trusted history marker line without changing its serialized payload."""
    return _HISTORY_MARKER + _marker_payload(body, _HISTORY_MARKER) + _COMMENT_CLOSE


def parse_content_comment(body: str) -> tuple[ContentHeader, str]:
    """Decode a content part without interpreting its free-text payload."""
    content_body = _strip_content_comment_envelope(body)
    marker_end = content_body.find(_COMMENT_SEPARATOR)
    if marker_end < 0:
        raise ValueError(_CONTENT_MARKER_INCOMPLETE)
    marker = content_body[:marker_end]
    if not marker.startswith(_CONTENT_MARKER):
        raise ValueError(_CONTENT_MARKER_MISSING)
    encoded = marker[len(_CONTENT_MARKER) :]
    payload = base64.urlsafe_b64decode(encoded.encode(_ASCII))
    return ContentHeader.model_validate_json(payload), content_body[marker_end + len(_COMMENT_SEPARATOR) :]


def is_content_comment(body: str) -> bool:
    """Identify the platform content envelope before inspecting embedded text."""
    return _strip_content_comment_envelope(body).startswith(_CONTENT_MARKER)


def _strip_content_comment_envelope(body: str) -> str:
    """Remove the optional readable envelope and history link before content data."""
    lines = body.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index].rstrip(_LINE_ENDINGS)
        if (line.startswith(_ENVELOPE_OPEN) and line.endswith(_ENVELOPE_CLOSE)) or line.startswith(_HISTORY_MARKER):
            index += 1
            continue
        break
    return _EMPTY.join(lines[index:])


def has_record_marker(body: str) -> bool:
    """Tell whether a trusted comment carries a record marker line."""
    return _has_marker_line(body, _RECORD_MARKER)


def has_ledger_marker(body: str) -> bool:
    """Tell whether a trusted comment carries a ledger marker line."""
    return _has_marker_line(body, _LEDGER_MARKER)


def has_artifact_history_marker(body: str) -> bool:
    """Tell whether a trusted comment carries an artifact history link."""
    return _has_marker_line(body, _HISTORY_MARKER)


def join_content_comments(parts: Sequence[tuple[ContentHeader, str]]) -> str:
    """Reassemble ordered parts and verify identity, completeness and digest."""
    if not parts:
        raise ValueError(_CONTENT_NO_PARTS)
    ordered = sorted(parts, key=lambda part: part[0].part)
    first = ordered[0][0]
    if len(ordered) != first.parts:
        raise ValueError(_CONTENT_PARTS_INCOMPLETE)
    if any(
        header.item_id != first.item_id
        or header.name != first.name
        or header.version != first.version
        or header.digest != first.digest
        or header.parts != first.parts
        or header.part != index
        for index, (header, _) in enumerate(ordered, start=1)
    ):
        raise ValueError(_CONTENT_PARTS_DISAGREE)
    content = _EMPTY.join(value for _, value in ordered)
    digest = hashlib.sha256(content.encode(_ENCODING)).hexdigest()
    if digest != first.digest:
        raise ValueError(_CONTENT_DIGEST_MISMATCH)
    return content


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
