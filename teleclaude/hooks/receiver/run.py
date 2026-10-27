"""Unified hook receiver for agent CLIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import yaml
from instrukt_ai_logging import configure_logging, get_logger
from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.attributes import QueryableAttribute
from sqlmodel import select

from teleclaude import paths as tc_paths
from teleclaude.caller_identity import CliCaller, SessionIdentityError, caller_from_principal, resolve_session_principal
from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.config.loader import load_company_config_for_slug, load_global_config
from teleclaude.constants import UI_MESSAGE_MAX_CHARS, HeadlessBootstrapField, HookSourceKind
from teleclaude.core import db_models
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.codex_transcript import is_codex_subagent_transcript
from teleclaude.core.control_delivery import IDLE_WAKE_TEXT
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.events import (
    AGENT_STATUS_REASON_FIELD,
    RECEIVER_HANDLED_HOOK_EVENTS,
    AgentHookEvents,
    AgentHookEventType,
)
from teleclaude.core.hook_delivery import (
    HookResponseFlushError,
    HookResponseWriteError,
    emit_pending_control_payloads,
    resolve_initial_procedure_entry_id,
)
from teleclaude.core.identity import NoIdentityCliCaller, derive_identity_key, memory_person_reach
from teleclaude.core.injected_text import (
    TranscriptEntryKind,
    recognize_delivered_text,
    visible_user_segments,
    wake_occurrence_key,
)
from teleclaude.core.models import JsonDict, Session
from teleclaude.core.organization import CompanyMembership, resolve_organization
from teleclaude.core.session_ended import is_conversation_session
from teleclaude.core.session_status import AgentStatusReason
from teleclaude.git import GitCommandError
from teleclaude.hooks.adapters import get_adapter
from teleclaude.hooks.adapters.base import HookAdapter, HookNormalizationReason, read_stdin_payload
from teleclaude.hooks.adapters.contracts import (
    ContinueWithReason,
    HookEmission,
    HookResponseFormat,
    HookResponseKind,
)
from teleclaude.hooks.checkpoint import get_checkpoint_content
from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_CLEAR_FLAG,
    CHECKPOINT_RECHECK_FLAG,
    consume_checkpoint_flag,
    is_checkpoint_disabled,
)
from teleclaude.hooks.edit_declarations import (
    declare_certain_edit,
    hold_certain_edit,
    settle_certain_edit,
)
from teleclaude.hooks.receiver._command_shell import host_shell_context
from teleclaude.hooks.receiver._tool_admission import native_tool_denial_for_source
from teleclaude.hooks.receiver_args import parse_receiver_args
from teleclaude.hooks.session_map import (
    _SESSION_EXPORTS,
    _classify_hook_source,
    _find_session_id_by_native,
    _get_cached_session_id,
    _get_memory_context,
    _get_session_map_path,
    _get_tmux_contract_tmpdir,
    _in_own_tmux_pane,
    _is_tmux_contract_session_compatible,
    _load_projected_session_row,
    _load_session_map,
    _persist_session_map,
    _resolve_hook_session_id,
    _resolve_or_refresh_session_id,
    _session_map_key,
    _write_session_map_atomic,
    get_outbox_session,
)
from teleclaude.identity_reach import Reach, resolve_reach
from teleclaude.memory.curation import MemoryScope, memory_scope
from teleclaude.runtime.environment import (
    COMPACTION_LAUNCH_CONTEXT_FIELD,
    RUNTIME_RUN_ID_FIELD,
    CompactionLaunchContext,
    read_compaction_launch_context,
    read_runtime_run_id,
)
from teleclaude.session_identity import inspect_session_identity_marker
from teleclaude.session_scoping._extractors._common import CERTAIN_EDIT_TOOLS, _canonical_tool_name
from teleclaude.utils.transcript import (
    extract_workdir_from_transcript,
    is_runtime_artifact_text,
    normalize_runtime_user_text,
    unwrap_pasted_content,
)

if TYPE_CHECKING:
    from teleclaude.config.identity_schema import PersonEntry
    from teleclaude.config.schema import CompanyConfig

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")
_RECEIVER_CONTRACT_VIOLATION_LOG = "Hook receiver rejected an invalid event contract"
_RECEIVER_ERROR_REPORT_FAILURE_LOG = "Hook receiver error reporting failed"

# Structured log event name for SessionStart context composition.
EVENT_SESSION_START_CONTEXT_COMPOSED = "session_start_context_composed"
EVENT_HOOK_INGRESS_ACCEPTED = "hook_ingress_accepted"
EVENT_HOOK_NORMALIZATION_DECIDED = "hook_normalization_decided"
EVENT_HOOK_SESSION_RESOLVED = "session_resolved"
EVENT_HOOK_CHECKPOINT_FLAGS_RESET = "checkpoint_flags_reset"
EVENT_HOOK_CONTEXT_EMITTED = "hook_context_emitted"
EVENT_HOOK_PROFILE_SERIALIZED = "hook_profile_serialized"
EVENT_HOOK_PROVIDER_RESPONSE_EMITTED = "hook_provider_response_emitted"
EVENT_HOOK_OUTBOX_ENQUEUED = "hook_outbox_enqueued"
EVENT_CHECKPOINT_EVIDENCE_ADDRESS_RESOLVED = "checkpoint_evidence_address_resolved"
_MEMORY_CALLER_RESOLUTION_FAILED = "memory_context_caller_resolution_failed"
_MEMORY_SCOPE_RESOLUTION_FAILED = "memory_context_scope_resolution_failed"
_SESSION_EXPORT_BINDINGS = (
    _get_session_map_path,
    _get_tmux_contract_tmpdir,
    _is_tmux_contract_session_compatible,
    _load_session_map,
    _persist_session_map,
    _resolve_or_refresh_session_id,
    _session_map_key,
    _write_session_map_atomic,
)

HOOK_RECEIVER_EXPORTS = [
    *_SESSION_EXPORTS,
    "_read_stdin",
    "_render_person_header",
    "_write_session_map_atomic",
    "enqueue_checkpoint_seen",
    "enqueue_hook_event",
    "main",
]

# Only these events are forwarded to daemon processing. Others are dropped.
# This prevents noisy intermediate hook traffic from reaching command handlers.
# Only events with actual handlers in the daemon - infrastructure events are dropped.
_HANDLED_EVENTS: frozenset[AgentHookEventType] = RECEIVER_HANDLED_HOOK_EVENTS
_ATTENTION_EVENTS: frozenset[AgentHookEventType] = frozenset(
    {
        AgentHookEvents.AGENT_BLOCKED,
        AgentHookEvents.AGENT_TURN_FAILED,
    }
)
_AGENT_NAME_FIELD = "agent_name"
_RECEIVED_AT_FIELD = "received_at"
_RECEIVER_INGRESS_ID_FIELD = "receiver_ingress_id"
_NATIVE_EVENT_TYPE_FIELD = "native_event_type"
_NATIVE_EVENT_DETAILS_FIELD = "native_event_details"
_DEFERRED_FORWARD_LOG_EVENTS: frozenset[AgentHookEventType] = frozenset(
    {
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.USER_PROMPT_SUBMIT,
    }
)
_CODEX_NOTIFY_DEBOUNCE_WINDOW_S = 10.0
_HOOK_SESSION_NO_MAPPING = "Hook session has no TeleClaude mapping, dropping event"
_MANAGED_IDENTITY_FAILURE = "Managed hook identity could not be resolved, dropping event"
_MANAGED_DESCENDANT_SESSION_START_DROPPED = "Dropped managed descendant session_start"
_IDENTITY_PERSON_RESOLUTION_FAILED = "identity_person_resolution_failed"
_COMPANY_RESOLUTION_FAILED = "company_resolution_failed"
_HOOK_NORMALIZATION_FAILED = "Hook event normalization failed"
_PROMPT_FIELD = "prompt"
_HUMAN_STEERING_CONTEXT = (
    "Human steering. Apply stewardship, attunement, leadership, and the human contract. "
    "Develop the intent; do not promote this wording into requirements. Advance confirmed work. "
    "Bring new outcome interpretations back for confirmation. "
    "Literal execution requires the human's explicit designation."
)
_SOURCE_KIND_FIELD = "source_kind"
_EXECUTION_KIND_FIELD = "execution_kind"
_INVOCATION_NUM_FIELD = "invocationNum"
_FULLY_IDLE_FIELD = "fullyIdle"
_EXECUTION_NUM_FIELD = "executionNum"
_STEP_IDX_FIELD = "stepIdx"
_HUMAN_PROFILE_ROOT = "human"
_EMPTY_LOG_VALUE = ""
_MODEL_DUMP_MODE = "json"
_NATIVE_PRE_TOOL_USE_EVENT = "PreToolUse"
_NATIVE_POST_TOOL_USE_EVENT = "PostToolUse"
_TOOL_NAME_FIELD = "tool_name"
_TOOL_INPUT_FIELD = "tool_input"
_TOOL_CALL_ID_FIELD = "tool_call_id"
_TOOL_RESULT_ERROR_FIELD = "error"
_AGY_TOOL_RESULT_NAME = "agy_tool_result"
_CERTAIN_EDIT_DECLARATION_FAILED = "certain_edit_declaration_failed"
_DECLARATION_OPERATIONAL_ERRORS = (OSError, ValueError, SQLAlchemyError, yaml.YAMLError, GitCommandError)


class CertainEditAction(StrEnum):
    """Receiver action required by a recognized certain edit hook event."""

    DECLARE = "declare"
    HOLD = "hold"
    SETTLE = "settle"


def _enrich_headless_bootstrap(
    data: JsonDict,
    event_type: AgentHookEventType,
    source_kind: HookSourceKind,
) -> None:
    """Attach terminal identity only to receiver-authorized headless starts."""
    if event_type is AgentHookEvents.AGENT_SESSION_START and source_kind is HookSourceKind.HEADLESS:
        data[HeadlessBootstrapField.AUTHORIZATION] = True
        caller_email = read_current_session_email()
        if caller_email:
            data[HeadlessBootstrapField.CALLER_EMAIL] = caller_email
        else:
            data.pop(HeadlessBootstrapField.CALLER_EMAIL, None)
        return

    data.pop(HeadlessBootstrapField.AUTHORIZATION, None)
    data.pop(HeadlessBootstrapField.CALLER_EMAIL, None)


class HookNormalizationOutcome(StrEnum):
    """Receiver-observed result of provider event normalization."""

    FORWARDED = "forwarded"
    DROPPED = "dropped"


class ReceiverDropReason(StrEnum):
    """Receiver-owned reasons for drops after provider normalization."""

    CODEX_SUBAGENT = "codex_subagent"
    MANAGED_DESCENDANT_SESSION_START = "managed_descendant_session_start"
    NATIVE_SUBAGENT_DENIED = "native_subagent_denied"
    SYSTEM_INJECTED_PROMPT = "system_injected_prompt"
    UNHANDLED_EVENT = "unhandled_event"


class CheckpointEvidenceAddressSource(StrEnum):
    """Source of the complete native address used for checkpoint evidence."""

    HOOK = "hook"
    SESSION_ROW = "session_row"


# Receiver-side UPSERT coalesce windows. Within the window, a new emit for the
# same (session_id, event_type) overwrites the prior unclaimed row instead of
# inserting a new one — payload + timestamp are updated in place. Claimed rows
# (locked_at NOT NULL) are never replaced; the new emit falls through to INSERT.
#
# Event types not in this map insert one row per emit. The codex-specific
# 10 s window for agent_stop overrides the 1 s baseline below.
_HOOK_COALESCE_WINDOWS_S: dict[str, float] = {
    AgentHookEvents.AGENT_STOP: 1.0,
    AgentHookEvents.NATIVE_METADATA_UPDATE: 1.0,
}
_BLOCKED_REASON_BY_NORMALIZATION: dict[HookNormalizationReason, AgentStatusReason] = {
    HookNormalizationReason.MAPPED_EVENT: AgentStatusReason.NEEDS_INPUT,
    HookNormalizationReason.USAGE_LIMIT_WAIT: AgentStatusReason.QUOTA_WAIT,
}
_UNSUPPORTED_BLOCKED_NORMALIZATION_ERROR = "Blocked hook normalization requires a supported reason"


@dataclass(frozen=True)
class _ReceiverOutboxContext:
    """Shared receiver metadata for mutation events emitted to the outbox."""

    agent: str
    event_type: str
    outbox_db: str
    runtime_run_id: str | None = None
    launch_context: CompactionLaunchContext | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    """Convert a datetime to timezone-aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _get_default_outbox_db() -> str:
    """Return the canonical receiver outbox database path."""
    return str(get_outbox_db_path(tc_paths.TELECLAUDE_HOME))


def _load_session_row(
    session_id: str,
    *columns: QueryableAttribute[Any],
) -> db_models.Session | None:
    """Load only the session columns consumed by this hook-processing path."""
    return _load_projected_session_row(session_id, *columns)


def _resolve_checkpoint_project_path(row: db_models.Session) -> str:
    """Resolve project_path, falling back to transcript-derived workdir.

    For worktree sessions (subdir starts with "trees/"), combines project_path
    with subdir so branch detection runs against the worktree, not the repo root.
    """
    transcript_path = getattr(row, "native_log_file", None)
    project_path = str(getattr(row, "project_path", "") or "")
    if not project_path and transcript_path:
        project_path = extract_workdir_from_transcript(transcript_path) or ""
    subdir = str(getattr(row, "subdir", "") or "")
    if subdir and project_path:
        project_path = str(Path(project_path) / subdir)
    return project_path


def _certain_edit_action(
    agent: AgentName,
    event_type: AgentHookEventType,
    raw_event_type: str,
) -> CertainEditAction | None:
    """Resolve the certain-edit action only for provider-confirmed tool events."""
    if agent is AgentName.GEMINI:
        if raw_event_type == _NATIVE_PRE_TOOL_USE_EVENT and event_type == AgentHookEvents.PRE_TOOL_USE:
            return CertainEditAction.HOLD
        if raw_event_type == _NATIVE_POST_TOOL_USE_EVENT and event_type == AgentHookEvents.POST_TOOL_USE:
            return CertainEditAction.SETTLE
        return None
    if raw_event_type == _NATIVE_POST_TOOL_USE_EVENT and event_type == AgentHookEvents.POST_TOOL_USE:
        return CertainEditAction.DECLARE
    return None


def _maybe_declare_certain_edit(
    *,
    session_id: str,
    agent: AgentName,
    event_type: AgentHookEventType,
    raw_event_type: str,
    data: JsonDict,
) -> None:
    """Capture certain edit paths before a later hook branch can return early."""
    action = _certain_edit_action(agent, event_type, raw_event_type)
    if action is None:
        return

    tool_name = data.get(_TOOL_NAME_FIELD)
    display_tool_name = tool_name if isinstance(tool_name, str) else _AGY_TOOL_RESULT_NAME
    if action is not CertainEditAction.SETTLE:
        if not isinstance(tool_name, str) or _canonical_tool_name(tool_name) not in CERTAIN_EDIT_TOOLS[agent]:
            return
    try:
        if action is CertainEditAction.SETTLE:
            step_id = data.get(_TOOL_CALL_ID_FIELD)
            if not isinstance(step_id, str) or not step_id:
                raise ValueError(_TOOL_CALL_ID_FIELD)
            error = data.get(_TOOL_RESULT_ERROR_FIELD)
            succeeded = error is None or error == _EMPTY_LOG_VALUE
            settle_certain_edit(session_id, step_id, succeeded=succeeded)
            return

        tool_input = data.get(_TOOL_INPUT_FIELD)
        if not isinstance(tool_name, str) or not tool_name or not isinstance(tool_input, dict):
            raise ValueError(_TOOL_INPUT_FIELD)
        row = _load_session_row(
            session_id,
            cast(QueryableAttribute[Any], db_models.Session.project_path),
            cast(QueryableAttribute[Any], db_models.Session.native_log_file),
            cast(QueryableAttribute[Any], db_models.Session.subdir),
        )
        if row is None:
            raise ValueError(_AGENT_NAME_FIELD)
        checkout_path = _resolve_checkpoint_project_path(row)
        if not checkout_path:
            raise ValueError(_AGENT_NAME_FIELD)
        checkout = Path(checkout_path)
        if action is CertainEditAction.HOLD:
            step_id = data.get(_TOOL_CALL_ID_FIELD)
            if not isinstance(step_id, str) or not step_id:
                raise ValueError(_TOOL_CALL_ID_FIELD)
            hold_certain_edit(
                session_id,
                agent,
                step_id,
                tool_name,
                cast(Mapping[str, object], tool_input),
                checkout,
            )
        else:
            declare_certain_edit(
                session_id,
                agent,
                tool_name,
                cast(Mapping[str, object], tool_input),
                checkout,
            )
    # Antigravity's PreToolUse has not run the edit yet, so a bookkeeping error
    # must not turn an allowed write into a denied one. After PostToolUse, the
    # file may already be changed; surfacing an expected bookkeeping failure as
    # a tool failure can invite a duplicate edit against that changed file.
    except _DECLARATION_OPERATIONAL_ERRORS as exc:
        logger.warning(
            _CERTAIN_EDIT_DECLARATION_FAILED,
            session_id=session_id,
            tool=display_tool_name,
            error=str(exc),
        )


def _resolve_agent_enum(agent: str) -> AgentName:
    """Resolve a hook agent string to an AgentName with default fallback."""
    try:
        return AgentName.from_str(agent)
    except ValueError:
        return AgentName.from_str(get_default_agent())


def _resolve_turn_start(row: db_models.Session) -> datetime | None:
    """Return the start timestamp for the current turn."""
    turn_candidates = [
        timestamp
        for timestamp in (_as_utc(row.last_message_sent_at), _as_utc(row.last_checkpoint_at))
        if timestamp is not None
    ]
    return max(turn_candidates, default=None)


def _load_checkpoint_row(session_id: str) -> db_models.Session | None:
    """Load the session row for checkpoint evaluation."""
    try:
        return _load_session_row(
            session_id,
            cast(QueryableAttribute[Any], db_models.Session.last_message_sent_at),
            cast(QueryableAttribute[Any], db_models.Session.last_checkpoint_at),
            cast(QueryableAttribute[Any], db_models.Session.native_session_id),
            cast(QueryableAttribute[Any], db_models.Session.native_log_file),
            cast(QueryableAttribute[Any], db_models.Session.working_slug),
            cast(QueryableAttribute[Any], db_models.Session.project_path),
            cast(QueryableAttribute[Any], db_models.Session.subdir),
            cast(QueryableAttribute[Any], db_models.Session.role),
            cast(QueryableAttribute[Any], db_models.Session.job),
        )
    except SQLAlchemyError as exc:
        logger.debug("Checkpoint eval skipped (db error)", error=str(exc))
        return None


def _resolve_memory_caller(session_id: str) -> CliCaller:
    """Resolve the starting session principal through the identity contract."""
    row = _load_session_row(
        session_id,
        cast(QueryableAttribute[Any], db_models.Session.session_id),
        cast(QueryableAttribute[Any], db_models.Session.principal),
        cast(QueryableAttribute[Any], db_models.Session.human_email),
        cast(QueryableAttribute[Any], db_models.Session.human_role),
        cast(QueryableAttribute[Any], db_models.Session.role),
    )
    if row is None:
        return NoIdentityCliCaller()
    try:
        principal, _role = resolve_session_principal(row)
    except SessionIdentityError:
        return NoIdentityCliCaller()
    return caller_from_principal(principal)


def _resolve_memory_scope(session_id: str) -> tuple[MemoryScope, bool] | None:
    """The starting session's memory scope, and whether its context is a conversation's strictly resolved scope."""
    row = _load_session_row(
        session_id,
        cast(QueryableAttribute[Any], db_models.Session.session_id),
        cast(QueryableAttribute[Any], db_models.Session.origin_metadata),
        cast(QueryableAttribute[Any], db_models.Session.principal),
        cast(QueryableAttribute[Any], db_models.Session.human_email),
        cast(QueryableAttribute[Any], db_models.Session.human_role),
        cast(QueryableAttribute[Any], db_models.Session.role),
        cast(QueryableAttribute[Any], db_models.Session.project_path),
        cast(QueryableAttribute[Any], db_models.Session.subdir),
        cast(QueryableAttribute[Any], db_models.Session.config_subject),
        cast(QueryableAttribute[Any], db_models.Session.initiator_session_id),
    )
    if row is None:
        return None
    origin_metadata: JsonDict = {}
    if row.origin_metadata:
        parsed = json.loads(row.origin_metadata)
        if isinstance(parsed, dict):
            origin_metadata = parsed
    session = Session(
        session_id=row.session_id,
        computer_name="",
        tmux_session_name="",
        title="",
        origin_metadata=origin_metadata,
        principal=row.principal,
        human_email=row.human_email,
        human_role=row.human_role,
        role=row.role,
        project_path=row.project_path,
        subdir=row.subdir,
        config_subject=row.config_subject,
        initiator_session_id=row.initiator_session_id,
    )
    scope = memory_scope(session)
    return None if scope is None else (scope, is_conversation_session(session))


def _resolve_identity_context(
    session_id: str,
    *,
    receiver_ingress_id: str = _EMPTY_LOG_VALUE,
) -> tuple[str | None, str | None, bool]:
    """Return identity-key, person header, and whether memberships were listed."""
    row = _load_session_row(
        session_id,
        cast(QueryableAttribute[Any], db_models.Session.origin_metadata),
        cast(QueryableAttribute[Any], db_models.Session.human_email),
    )
    if not row:
        return None, None, False
    identity_key: str | None = None
    if row.origin_metadata:
        try:
            origin = json.loads(row.origin_metadata)
            if isinstance(origin, dict):
                identity_key = derive_identity_key(origin)
        except json.JSONDecodeError:
            pass
    human_email = getattr(row, "human_email", None)
    if not human_email:
        return identity_key, None, False
    people = load_global_config().people
    person = next((person for person in people if person.email == human_email), None)
    if person is None:
        return identity_key, None, False
    memberships: tuple[CompanyMembership, ...] = ()
    memberships_listed = False
    if person.slug is not None:
        memberships = resolve_organization(person.slug).memberships
        memberships_listed = True
    person_header = _render_person_header(
        person,
        memberships=memberships,
        receiver_ingress_id=receiver_ingress_id,
        session_id=session_id,
    )
    return identity_key, person_header, memberships_listed


def _build_receiver_error_payload(
    *,
    message: str,
    code: str,
    agent: str,
    event_type: str | None,
    details: dict[str, object] | None = None,  # guard: loose-dict - dynamic payload
) -> dict[str, object]:  # guard: loose-dict - dynamic payload
    """Construct a normalized error payload for the hook outbox."""
    payload = dict(details or {})
    payload.update({"agent": agent, "event_type": event_type, "code": code})
    return {
        "message": message,
        "source": "hook_receiver",
        "code": code,
        "details": payload,
        "severity": "error",
        "retryable": False,
    }


def _reset_checkpoint_flags(session_id: str) -> None:
    # New user input starts a fresh checkpoint turn. This resets the turn
    # latches only — disclaimer lifetime is bound to dirty state, not turns.
    consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)
    consume_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG)


def _maybe_checkpoint_output(
    session_id: str,
    agent: str,
    hook_data: JsonDict,
    *,
    outbox_db: str,
    receiver_ingress_id: str,
) -> str | None:
    """Evaluate whether to block an agent_stop with a checkpoint instruction.

    Returns the checkpoint reason string if a checkpoint is warranted, or None
    to let the stop pass through to the normal enqueue path. The caller is
    responsible for formatting the reason into agent-specific JSON via the adapter.
    """
    # Turn-scoped manual clear: while the marker exists, skip checkpoints for this turn.
    if is_checkpoint_disabled(session_id):
        consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)
        logger.info("Checkpoint skipped (turn-scoped clear flag)", session_id=session_id, agent=agent)
        return None

    row = _load_checkpoint_row(session_id)
    if not row:
        return None

    now = datetime.now(UTC)
    turn_start = _resolve_turn_start(row)
    if not turn_start:
        logger.debug("Checkpoint skipped (no turn start) for session %s", session_id)
        return None

    elapsed = (now - turn_start).total_seconds()
    row_native_session_id = getattr(row, "native_session_id", None)
    row_transcript_path = getattr(row, "native_log_file", None)
    hook_native_session_id, hook_transcript_path = _extract_native_hook_fields(hook_data)
    if hook_native_session_id and hook_transcript_path:
        native_session_id = hook_native_session_id
        transcript_path = hook_transcript_path
        address_source = CheckpointEvidenceAddressSource.HOOK
    else:
        native_session_id = row_native_session_id
        transcript_path = row_transcript_path
        address_source = CheckpointEvidenceAddressSource.SESSION_ROW
    working_slug = getattr(row, "working_slug", None)
    project_path = _resolve_checkpoint_project_path(row)

    logger.debug("Checkpoint eval for session %s (%.1fs elapsed)", session_id, elapsed)
    logger.info(
        EVENT_CHECKPOINT_EVIDENCE_ADDRESS_RESOLVED,
        receiver_ingress_id=receiver_ingress_id,
        session_id=session_id,
        native_session_id=(native_session_id or _EMPTY_LOG_VALUE),
        transcript_path=(transcript_path or _EMPTY_LOG_VALUE),
        address_source=address_source,
    )

    checkpoint_reason = get_checkpoint_content(
        session_id=session_id,
        transcript_path=transcript_path,
        agent_name=_resolve_agent_enum(agent),
        project_path=project_path,
        native_session_id=native_session_id,
        working_slug=working_slug,
        elapsed_since_turn_start_s=elapsed,
        role=getattr(row, "role", None),
        job=getattr(row, "job", None),
        receiver_ingress_id=receiver_ingress_id,
    )
    if not checkpoint_reason:
        logger.debug(
            "Checkpoint skipped: no turn-local changes for session %s (transcript=%s)",
            session_id,
            transcript_path or "<none>",
        )
        return None

    enqueue_checkpoint_seen(
        session_id=session_id,
        checkpoint_at=now.isoformat(),
        outbox_db=outbox_db,
    )
    logger.info(
        "Checkpoint payload prepared",
        route="hook",
        session=session_id,
        agent=agent,
        transcript_present=bool(transcript_path),
        project_path=project_path or "",
        working_slug=working_slug or "",
        payload_len=len(checkpoint_reason),
    )

    return checkpoint_reason


def _render_person_header(
    person: PersonEntry,
    *,
    memberships: tuple[CompanyMembership, ...] = (),
    receiver_ingress_id: str = _EMPTY_LOG_VALUE,
    session_id: str = _EMPTY_LOG_VALUE,
) -> str:
    """Render the complete non-null person entry, with company memberships, as human-readable YAML."""
    person_data = person.model_dump(mode=_MODEL_DUMP_MODE, exclude_none=True)
    if memberships:
        person_data["memberships"] = [
            {"company": membership.company_slug, "role": membership.role.value} for membership in memberships
        ]
    included_fields = list(person_data)
    logger.info(
        EVENT_HOOK_PROFILE_SERIALIZED,
        receiver_ingress_id=receiver_ingress_id,
        session_id=session_id,
        root=_HUMAN_PROFILE_ROOT,
        included_fields=included_fields,
        included_field_count=len(included_fields),
    )
    return yaml.safe_dump(
        {_HUMAN_PROFILE_ROOT: person_data},
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()


def _render_company_header(company: CompanyConfig) -> str:
    """Render the company-profile header — the company-scoped twin of the person header."""
    name = company.name or company.slug or "Company"
    description = (company.description or "").strip()
    if not description:
        return f"Company: {name}"
    return f"Company: {name}\n{description}"


def _resolve_company_header(session_id: str) -> tuple[str | None, str | None]:
    """Resolve the session's company slug and its rendered profile header.

    The SESSION's own company determines the header — never the project it
    happens to stand in. A session created without a company carries no
    header; an unknown company cannot reach the row at all, because the
    create door validates it before the row ever exists.
    """
    row = _load_session_row(
        session_id,
        cast(QueryableAttribute[Any], db_models.Session.company),
    )
    if not row:
        return None, None
    company_slug = getattr(row, "company", None)
    if not company_slug:
        return None, None
    company_config = load_company_config_for_slug(company_slug)
    if company_config is None:
        return company_slug, None
    return company_slug, _render_company_header(company_config)


def _print_additional_context(
    cwd: str | None,
    session_id: str,
    *,
    provider: str,
    receiver_ingress_id: str,
) -> str | None:
    """Gather startup context; the boundary owns the single eventual response."""
    scope: MemoryScope | None = None
    strict_scope = False
    try:
        resolved_scope = _resolve_memory_scope(session_id)
        if resolved_scope is not None:
            scope, strict_scope = resolved_scope
    except (SQLAlchemyError, TypeError, ValueError, OSError, RuntimeError):
        logger.error(_MEMORY_SCOPE_RESOLUTION_FAILED, session_id=session_id, exc_info=True)
    project_name = scope.namespace if scope is not None else (Path(cwd).name if cwd else None)
    if not project_name:
        return None

    identity_key: str | None = scope.person.identity_key if scope is not None else None
    person_header: str | None = None
    memberships_listed = False
    try:
        legacy_identity_key, person_header, memberships_listed = _resolve_identity_context(
            session_id,
            receiver_ingress_id=receiver_ingress_id,
        )
        if scope is None:
            identity_key = legacy_identity_key
    except (SQLAlchemyError, TypeError, ValueError, json.JSONDecodeError):
        logger.debug(_IDENTITY_PERSON_RESOLUTION_FAILED, session_id=session_id)

    company: str | None = None
    company_header: str | None = None
    try:
        company, company_header = _resolve_company_header(session_id)
    except (OSError, ValueError):
        logger.debug(_COMPANY_RESOLUTION_FAILED, project_name=project_name)

    def resolve_memory_reach() -> Reach:
        if scope is not None:
            return memory_person_reach(scope.person)
        try:
            return resolve_reach(_resolve_memory_caller(session_id))
        except (SQLAlchemyError, TypeError, ValueError):
            logger.error(_MEMORY_CALLER_RESOLUTION_FAILED, session_id=session_id, exc_info=True)
            return resolve_reach(NoIdentityCliCaller())

    memory_context = _get_memory_context(
        project_name,
        resolve_memory_reach,
        identity_key=identity_key,
        strict_identity_keys=scope.identity_keys if strict_scope and scope is not None else None,
    )
    shell_context = host_shell_context()
    if not memory_context and not person_header and not company_header and not shell_context:
        logger.info(
            EVENT_SESSION_START_CONTEXT_COMPOSED,
            session_id=session_id,
            domain_baseline_injected=False,
            additional_context_emitted=False,
            company_context_present=False,
            company=company or "",
            person_context_present=False,
            memory_context_present=False,
            command_shell_context_present=False,
            memberships_listed=memberships_listed,
        )
        return None

    parts: list[str] = []
    if company_header:
        parts.append(company_header)
    if person_header:
        parts.append(person_header)
    if memory_context:
        parts.append(memory_context)
    if shell_context:
        parts.append(shell_context)
    context = "\n\n".join(parts)

    logger.debug(
        "Additional context fetched", project=project_name, length=len(context), identity_key=identity_key or ""
    )
    logger.info(
        EVENT_SESSION_START_CONTEXT_COMPOSED,
        session_id=session_id,
        domain_baseline_injected=False,
        additional_context_emitted=bool(context),
        company_context_present=bool(company_header),
        company=company or "",
        person_context_present=bool(person_header),
        memory_context_present=bool(memory_context),
        command_shell_context_present=bool(shell_context),
        memberships_listed=memberships_listed,
    )
    return context


def _parse_args() -> argparse.Namespace:
    return parse_receiver_args()


# guard: loose-dict-func - Raw stdin JSON payload at process boundary.
def _read_stdin() -> tuple[str, dict[str, object]]:
    return read_stdin_payload()


def _log_raw_input(raw_input: str, *, log_raw: bool) -> None:
    if not raw_input:
        return
    truncated = len(raw_input) > UI_MESSAGE_MAX_CHARS
    if log_raw:
        logger.trace(
            "receiver raw input",
            raw=raw_input[:UI_MESSAGE_MAX_CHARS],
            raw_len=len(raw_input),
            truncated=truncated,
        )
    else:
        logger.trace(
            "receiver raw input",
            raw_len=len(raw_input),
            truncated=truncated,
        )


def _serialize_outbox_payload(
    payload: str | Mapping[str, object],  # guard: loose-dict - Hook payload is dynamic JSON.
) -> str:
    """Serialize an outbox payload while accepting pre-encoded JSON for tests."""
    if isinstance(payload, str):
        return payload
    return json.dumps(dict(payload))


def _attach_launch_context(payload: JsonDict, context: _ReceiverOutboxContext) -> None:
    """Carry immutable launch identities beside normalized provider fields."""
    if context.launch_context is not None:
        payload[COMPACTION_LAUNCH_CONTEXT_FIELD] = cast(JsonValue, context.launch_context.to_payload())
    if context.runtime_run_id is not None:
        payload[RUNTIME_RUN_ID_FIELD] = context.runtime_run_id


def enqueue_hook_event(
    session_id: str,
    event_type: str,
    payload: str | Mapping[str, object],  # guard: loose-dict - Hook payload is dynamic JSON.
    *,
    outbox_db: str,
    latest_wins_within_s: float | None = None,
) -> None:
    """Persist hook event to local outbox for durable delivery."""
    now = datetime.now(UTC).isoformat()
    payload_json = _serialize_outbox_payload(payload)

    with get_outbox_session(outbox_db) as session:
        if latest_wins_within_s and latest_wins_within_s > 0:
            cutoff = datetime.now(UTC).timestamp() - latest_wins_within_s
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()
            hook_outbox_table = cast(Any, db_models.HookOutbox).__table__
            stmt = (
                select(db_models.HookOutbox)
                .where(db_models.HookOutbox.session_id == session_id)
                .where(db_models.HookOutbox.event_type == event_type)
                .where(hook_outbox_table.c.created_at >= cutoff_iso)
                .where(hook_outbox_table.c.locked_at.is_(None))
                .order_by(hook_outbox_table.c.created_at.desc(), hook_outbox_table.c.id.desc())
                .limit(1)
            )
            existing = session.exec(stmt).first()
            if existing is not None:
                existing.payload = payload_json
                existing.created_at = now
                existing.next_attempt_at = now
                existing.attempt_count = 0
                existing.last_error = None
                session.add(existing)
                session.commit()
                return
        row = db_models.HookOutbox(
            session_id=session_id,
            event_type=event_type,
            payload=payload_json,
            created_at=now,
            next_attempt_at=now,
            attempt_count=0,
        )
        session.add(row)
        session.commit()


def _attach_attention_observation(
    data: JsonDict,
    event_type: AgentHookEventType,
    raw_event_type: str,
    raw_data: JsonDict,
    receiver_ingress_id: str,
) -> None:
    """Preserve receiver-owned provenance and unnormalized provider evidence."""
    if event_type not in _ATTENTION_EVENTS:
        return
    data[_RECEIVER_INGRESS_ID_FIELD] = receiver_ingress_id
    data[_NATIVE_EVENT_TYPE_FIELD] = raw_event_type
    data[_NATIVE_EVENT_DETAILS_FIELD] = dict(raw_data)


def enqueue_checkpoint_seen(
    session_id: str,
    *,
    checkpoint_at: str,
    outbox_db: str,
) -> None:
    """Persist a checkpoint_seen mutation event to the outbox."""
    enqueue_hook_event(
        session_id,
        AgentHookEvents.CHECKPOINT_SEEN,
        {"checkpoint_at": checkpoint_at},
        outbox_db=outbox_db,
    )


def _emit_receiver_error_best_effort(
    message: str,
    code: str,
    args: argparse.Namespace,
    details: dict[str, object] | None = None,  # guard: loose-dict - Error details are context-specific.
    raw_data: dict[str, object] | None = None,  # guard: loose-dict - Raw hook payload for best-effort context.
) -> None:
    """Best-effort error emission for receiver contract violations."""
    try:
        raw_native_session_id = None
        if raw_data is not None:
            # Try canonical name first, then Codex raw name as fallback
            raw_id = raw_data.get("session_id") or raw_data.get("thread-id")
            if isinstance(raw_id, str):
                raw_native_session_id = raw_id
        session_id = _get_cached_session_id(args.agent, raw_native_session_id)
        if not session_id:
            session_id = _find_session_id_by_native(raw_native_session_id)
        logger.error(
            _RECEIVER_CONTRACT_VIOLATION_LOG,
            agent=args.agent,
            event_type=getattr(args, "event_type", None),
            code=code,
            session_id=session_id,
        )
        if not session_id:
            return
        enqueue_hook_event(
            session_id,
            "error",
            _build_receiver_error_payload(
                message=message,
                code=code,
                agent=args.agent,
                event_type=getattr(args, "event_type", None),
                details=details,
            ),
            outbox_db=_get_default_outbox_db(),
        )
    except SQLAlchemyError as exc:
        logger.error(
            _RECEIVER_ERROR_REPORT_FAILURE_LOG,
            agent=args.agent,
            event_type=getattr(args, "event_type", None),
            code=code,
            error=repr(exc),
            exc_info=True,
        )


def _parse_receiver_input(args: argparse.Namespace, adapter: HookAdapter) -> tuple[str, str, JsonDict]:
    try:
        return adapter.parse_input(args)
    except json.JSONDecodeError:
        _emit_receiver_error_best_effort(
            message="Invalid hook payload JSON",
            code="HOOK_INVALID_JSON",
            args=args,
        )
        sys.exit(1)
    except ValueError as exc:
        _emit_receiver_error_best_effort(
            message=str(exc),
            code="HOOK_PAYLOAD_NOT_OBJECT",
            args=args,
        )
        sys.exit(1)


def _log_normalization_decision(
    *,
    receiver_ingress_id: str,
    provider: str,
    raw_event_type: str,
    outcome: HookNormalizationOutcome,
    reason: StrEnum,
    event_type: str | None,
    native_session_id: str | None,
) -> None:
    logger.info(
        EVENT_HOOK_NORMALIZATION_DECIDED,
        receiver_ingress_id=receiver_ingress_id,
        provider=provider,
        raw_event=raw_event_type,
        outcome=outcome,
        reason=reason,
        normalized_event=(event_type or _EMPTY_LOG_VALUE),
        native_session_id=(native_session_id or _EMPTY_LOG_VALUE),
    )


def _emit_provider_response(
    payload: str,
    *,
    response_kind: HookResponseKind,
    response_format: HookResponseFormat,
    provider: str,
    raw_event_type: str,
    receiver_ingress_id: str,
    session_id: str | None,
) -> None:
    try:
        sys.stdout.write(f"{payload}\n")
    except OSError as exc:
        raise HookResponseWriteError(str(exc)) from exc
    try:
        sys.stdout.flush()
    except OSError as exc:
        raise HookResponseFlushError(str(exc)) from exc
    logger.info(
        EVENT_HOOK_PROVIDER_RESPONSE_EMITTED,
        receiver_ingress_id=receiver_ingress_id,
        provider=provider,
        raw_event=raw_event_type,
        response_kind=response_kind,
        response_format=response_format,
        session_id=(session_id or _EMPTY_LOG_VALUE),
    )


def _emit_hook_emission(
    emission: HookEmission,
    *,
    provider: str,
    raw_event_type: str,
    receiver_ingress_id: str,
    session_id: str | None,
) -> None:
    """Commit one adapter-rendered emission to provider stdout."""
    _emit_provider_response(
        emission.payload,
        response_kind=emission.response_kind,
        response_format=emission.response_format,
        provider=provider,
        raw_event_type=raw_event_type,
        receiver_ingress_id=receiver_ingress_id,
        session_id=session_id,
    )


def _handle_native_tool_admission(
    *,
    adapter: HookAdapter,
    raw_event_type: str,
    data: JsonDict,
    provider: str,
    receiver_ingress_id: str,
    native_session_id: str | None,
) -> bool:
    """Deny declared native-tool intents on managed sources before resolution."""
    intent = adapter.native_tool_intent(raw_event_type, data)
    if intent is None:
        return False
    marker_state, _ = inspect_session_identity_marker()
    source_kind = _classify_hook_source(marker_state, _in_own_tmux_pane())
    denial = native_tool_denial_for_source(intent, source_kind)
    if denial is None:
        return False

    _log_normalization_decision(
        receiver_ingress_id=receiver_ingress_id,
        provider=provider,
        raw_event_type=raw_event_type,
        outcome=HookNormalizationOutcome.DROPPED,
        reason=ReceiverDropReason.NATIVE_SUBAGENT_DENIED,
        event_type=None,
        native_session_id=native_session_id,
    )
    _emit_hook_emission(
        adapter.render_tool_denial(raw_event_type, denial),
        provider=provider,
        raw_event_type=raw_event_type,
        receiver_ingress_id=receiver_ingress_id,
        session_id=None,
    )
    return True


def _success_response_kind(
    event_type: str | None,
    reason: HookNormalizationReason,
) -> HookResponseKind:
    if reason is HookNormalizationReason.LATER_INVOCATION:
        return HookResponseKind.NEUTRAL
    if event_type == AgentHookEvents.PRE_TOOL_USE:
        return HookResponseKind.TOOL_ALLOW
    if event_type == AgentHookEvents.AGENT_STOP or reason is HookNormalizationReason.PROVIDER_NOT_IDLE:
        return HookResponseKind.STOP_ALLOW
    return HookResponseKind.NEUTRAL


def _emit_success_response_if_supported(
    *,
    adapter: HookAdapter,
    raw_event_type: str,
    event_type: str | None,
    reason: HookNormalizationReason,
    provider: str,
    receiver_ingress_id: str,
    session_id: str | None,
) -> bool:
    success_response = adapter.format_success_response(raw_event_type)
    if not success_response:
        return False
    _emit_provider_response(
        success_response,
        response_kind=_success_response_kind(event_type, reason),
        response_format=HookResponseFormat.JSON,
        provider=provider,
        raw_event_type=raw_event_type,
        receiver_ingress_id=receiver_ingress_id,
        session_id=session_id,
    )
    return True


def _extract_native_hook_fields(data: JsonDict) -> tuple[str | None, str | None]:
    raw_native_session_id: str | None = None
    raw_id = data.get("session_id")
    if isinstance(raw_id, str):
        raw_native_session_id = raw_id

    raw_native_log_file: str | None = None
    raw_log = data.get("transcript_path")
    if isinstance(raw_log, str):
        raw_native_log_file = raw_log
    return raw_native_session_id, raw_native_log_file


def _attach_blocked_status_reason(
    data: JsonDict,
    event_type: AgentHookEventType,
    normalization_reason: HookNormalizationReason,
) -> None:
    """Carry the adapter's blocked classification into the typed event payload."""
    if event_type is not AgentHookEvents.AGENT_BLOCKED:
        return
    blocked_reason = _BLOCKED_REASON_BY_NORMALIZATION.get(normalization_reason)
    if blocked_reason is None:
        raise ValueError(_UNSUPPORTED_BLOCKED_NORMALIZATION_ERROR)
    data[AGENT_STATUS_REASON_FIELD] = blocked_reason.value


def _resolve_receiver_session_id(
    agent: str,
    event_type: str,
    raw_event_type: str,
    raw_native_session_id: str | None,
    adapter: HookAdapter,
    execution_kind: str | None,
) -> tuple[str | None, HookSourceKind]:
    marker_state, marker_session_id = inspect_session_identity_marker()
    source_kind = _classify_hook_source(marker_state, _in_own_tmux_pane())
    try:
        teleclaude_session_id, cached_session_id, existing_id = _resolve_hook_session_id(
            agent=agent,
            event_type=event_type,
            native_session_id=raw_native_session_id,
            source_kind=source_kind,
            marker_state=marker_state,
            marker_session_id=marker_session_id,
            mint_events=adapter.mint_events,
        )
    except ValueError as exc:
        logger.error(
            "Hook receiver contract violation",
            agent=agent,
            event_type=event_type,
            source_kind=source_kind,
            marker_state=marker_state,
            error=str(exc),
        )
        sys.exit(1)
    logger.debug(
        "Hook session resolution",
        agent=agent,
        source_kind=source_kind,
        marker_state=marker_state,
        event_type=event_type,
        cached_session_id=(cached_session_id or ""),
        existing_session_id=(existing_id or ""),
        resolved_session_id=(teleclaude_session_id or ""),
        native_session_id=(raw_native_session_id or ""),
        execution_kind=(execution_kind or ""),
    )
    if teleclaude_session_id:
        return teleclaude_session_id, source_kind
    drop_message = (
        _MANAGED_IDENTITY_FAILURE if source_kind is HookSourceKind.MANAGED_DESCENDANT else _HOOK_SESSION_NO_MAPPING
    )
    logger.debug(
        drop_message,
        agent=agent,
        source_kind=source_kind,
        marker_state=marker_state,
        event_type=event_type,
        raw_event_type=raw_event_type,
        native_session_id=(raw_native_session_id or ""),
        cached_session_id=(cached_session_id or ""),
        existing_session_id=(existing_id or ""),
        execution_kind=(execution_kind or ""),
    )
    return None, source_kind


def _enqueue_native_metadata_update(
    *,
    session_id: str,
    raw_native_session_id: str | None,
    raw_native_log_file: str | None,
    context: _ReceiverOutboxContext,
) -> None:
    payload: JsonDict = {
        "agent": context.agent,
        "source_event_type": context.event_type,
    }
    if raw_native_session_id is not None:
        payload["native_session_id"] = raw_native_session_id
    if raw_native_log_file is not None:
        payload["native_log_file"] = raw_native_log_file
    _attach_launch_context(payload, context)
    enqueue_hook_event(
        session_id,
        AgentHookEvents.NATIVE_METADATA_UPDATE,
        payload,
        outbox_db=context.outbox_db,
        latest_wins_within_s=_HOOK_COALESCE_WINDOWS_S.get(AgentHookEvents.NATIVE_METADATA_UPDATE),
    )


def _enqueue_native_session_refresh(
    *,
    session_id: str,
    native_session_id: str | None,
    context: _ReceiverOutboxContext,
) -> None:
    payload: JsonDict = {
        "agent": context.agent,
        "source_event_type": context.event_type,
        "native_session_id": native_session_id,
    }
    _attach_launch_context(payload, context)
    enqueue_hook_event(
        session_id,
        AgentHookEvents.NATIVE_SESSION_REFRESH,
        payload,
        outbox_db=context.outbox_db,
    )


def _persist_native_metadata(
    *,
    session_id: str,
    raw_native_session_id: str | None,
    raw_native_log_file: str | None,
    context: _ReceiverOutboxContext,
) -> None:
    if not raw_native_session_id and not raw_native_log_file:
        return

    row = _load_session_row(
        session_id,
        cast(QueryableAttribute[Any], db_models.Session.native_session_id),
    )
    if (
        row
        and raw_native_session_id is not None
        and row.native_session_id
        and row.native_session_id != raw_native_session_id
    ):
        _enqueue_native_session_refresh(
            session_id=session_id,
            native_session_id=raw_native_session_id,
            context=context,
        )

    _enqueue_native_metadata_update(
        session_id=session_id,
        raw_native_session_id=raw_native_session_id,
        raw_native_log_file=raw_native_log_file,
        context=context,
    )


def _is_system_injected_user_prompt(agent: str, prompt_text: str) -> bool:
    """Return True when a user_prompt_submit payload is an agent/runtime artifact."""
    return is_runtime_artifact_text(agent, prompt_text)


def _handle_user_prompt_submit(
    event_type: str,
    data: JsonDict,
    agent: str,
    session_id: str,
    raw_native_session_id: str | None,
    receiver_ingress_id: str,
    initial_procedure_entry_id: str | None,
) -> bool:
    if event_type != AgentHookEvents.USER_PROMPT_SUBMIT:
        return False
    prompt_value = data.get(_PROMPT_FIELD)
    prompt_text = unwrap_pasted_content(prompt_value) if isinstance(prompt_value, str) else ""
    # The CLI's paste framing is transport, never content: strip it here, on the
    # payload every downstream consumer reads, so classification and the
    # forwarded event both see the text the sender actually submitted.
    if prompt_text != prompt_value:
        data[_PROMPT_FIELD] = prompt_text
    if not prompt_text.strip():
        logger.debug(
            "Allowing empty user_prompt_submit hook event",
            agent=agent,
            session_id=session_id,
            native_session_id=(raw_native_session_id or ""),
            hook_event_name=str(data.get("hook_event_name") or ""),
            raw_event_type=event_type,
        )
        _reset_checkpoint_flags(session_id)
        logger.info(
            EVENT_HOOK_CHECKPOINT_FLAGS_RESET,
            receiver_ingress_id=receiver_ingress_id,
            provider=agent,
            session_id=session_id,
        )
        return False
    if _is_system_injected_user_prompt(agent, prompt_text):
        if prompt_text == IDLE_WAKE_TEXT or wake_occurrence_key(prompt_text) is not None:
            _reset_checkpoint_flags(session_id)
            return False
        if initial_procedure_entry_id is not None:
            _reset_checkpoint_flags(session_id)
            return False
        logger.debug(
            "Dropped system-injected user_prompt_submit",
            agent=agent,
            session_id=session_id,
        )
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=agent,
            raw_event_type=event_type,
            outcome=HookNormalizationOutcome.DROPPED,
            reason=ReceiverDropReason.SYSTEM_INJECTED_PROMPT,
            event_type=None,
            native_session_id=raw_native_session_id,
        )
        return True
    _reset_checkpoint_flags(session_id)
    logger.info(
        EVENT_HOOK_CHECKPOINT_FLAGS_RESET,
        receiver_ingress_id=receiver_ingress_id,
        provider=agent,
        session_id=session_id,
    )
    return False


def _maybe_emit_additional_context(
    *,
    event_type: str,
    cwd: str | None,
    session_id: str,
    provider: str,
    receiver_ingress_id: str,
    hook_data: JsonDict,
) -> str | None:
    """Compose additional context for the boundary's single provider response.

    This lane is distinct from checkpoint blocking on Stop.
    """
    if event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
        prompt = hook_data.get(_PROMPT_FIELD)
        if not isinstance(prompt, str) or is_runtime_artifact_text(provider, prompt):
            return None
        prompt = recognize_delivered_text(prompt, AgentName.from_str(provider))
        prompt = normalize_runtime_user_text(provider, prompt)
        if any(kind is TranscriptEntryKind.ORDINARY for kind, _ in visible_user_segments(prompt)):
            return _HUMAN_STEERING_CONTEXT
        return None
    if event_type != AgentHookEvents.AGENT_SESSION_START:
        return None
    if cwd:
        project_name = Path(cwd).name
        logger.debug("Emitting additional context for session_start", project=project_name)
        return _print_additional_context(
            cwd,
            session_id=session_id,
            provider=provider,
            receiver_ingress_id=receiver_ingress_id,
        )
    logger.error("Skipping additional context: no CWD provided (contract violation)")
    logger.info(
        EVENT_SESSION_START_CONTEXT_COMPOSED,
        session_id=session_id,
        domain_baseline_injected=False,
        additional_context_emitted=False,
        company_context_present=False,
        person_context_present=False,
        memory_context_present=False,
    )
    return None


def _maybe_emit_checkpoint_response(
    *,
    event_type: str,
    adapter: HookAdapter,
    session_id: str,
    hook_data: JsonDict,
    context: _ReceiverOutboxContext,
    raw_event_type: str,
    receiver_ingress_id: str,
) -> str | None:
    if event_type != AgentHookEvents.AGENT_STOP or not adapter.supports_hook_checkpoint:
        return None
    checkpoint_reason: str | None = None
    try:
        checkpoint_reason = _maybe_checkpoint_output(
            session_id,
            context.agent,
            hook_data,
            outbox_db=context.outbox_db,
            receiver_ingress_id=receiver_ingress_id,
        )
    except (AttributeError, TypeError, ValueError, SQLAlchemyError) as exc:
        logger.warning(
            "Checkpoint eval crashed (ignored)",
            event_type=event_type,
            session_id=session_id,
            agent=context.agent,
            error=str(exc),
        )
    if not checkpoint_reason:
        return None
    return checkpoint_reason


def _maybe_emit_boundary_response(
    *,
    event_type: str,
    adapter: HookAdapter,
    session_id: str,
    hook_data: JsonDict,
    context: _ReceiverOutboxContext,
    raw_event_type: str,
    receiver_ingress_id: str,
    additional_context: str | None,
    initial_procedure_entry_id: str | None,
    procedure_wake_occurrence_id: str | None,
) -> bool:
    """Emit checkpoint continuations independently of control delivery."""
    checkpoint_reason = _maybe_emit_checkpoint_response(
        event_type=event_type,
        adapter=adapter,
        session_id=session_id,
        hook_data=hook_data,
        context=context,
        raw_event_type=raw_event_type,
        receiver_ingress_id=receiver_ingress_id,
    )

    def write_emission(emission: HookEmission) -> None:
        _emit_hook_emission(
            emission,
            provider=context.agent,
            raw_event_type=raw_event_type,
            receiver_ingress_id=receiver_ingress_id,
            session_id=session_id,
        )

    if checkpoint_reason is not None:
        write_emission(adapter.render_response(raw_event_type, ContinueWithReason(checkpoint_reason)))
        return True

    return emit_pending_control_payloads(
        adapter=adapter,
        raw_event_type=raw_event_type,
        session_id=session_id,
        provider=context.agent,
        internal_event=event_type,
        receiver_ingress_id=receiver_ingress_id,
        write_emission=write_emission,
        initial_procedure_entry_id=initial_procedure_entry_id,
        procedure_wake_occurrence_id=procedure_wake_occurrence_id,
        additional_context=additional_context,
    )


def _run_ordinary_hook_effects(
    *,
    launch_context: CompactionLaunchContext | None,
    adapter: HookAdapter,
    event_type: AgentHookEventType,
    data: JsonDict,
    agent: str,
    session_id: str,
    raw_native_session_id: str | None,
    receiver_ingress_id: str,
    cwd: str | None,
    outbox_context: _ReceiverOutboxContext,
    raw_event_type: str,
) -> tuple[bool, bool]:
    """Return whether processing stops and whether a provider response was emitted."""
    if launch_context is not None:
        return False, False
    initial_procedure_entry_id: str | None = None
    procedure_wake_occurrence_id: str | None = None
    if event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
        prompt_value = data.get(_PROMPT_FIELD)
        prompt_text = unwrap_pasted_content(prompt_value) if isinstance(prompt_value, str) else ""
        if _is_system_injected_user_prompt(agent, prompt_text):
            canonical_prompt = recognize_delivered_text(prompt_text, AgentName.from_str(agent))
            procedure_wake_occurrence_id = wake_occurrence_key(canonical_prompt)
            initial_procedure_entry_id = resolve_initial_procedure_entry_id(
                session_id=session_id,
                prompt_text=canonical_prompt,
            )
    if _handle_user_prompt_submit(
        event_type,
        data,
        agent,
        session_id,
        raw_native_session_id,
        receiver_ingress_id,
        initial_procedure_entry_id,
    ):
        return True, False
    _maybe_declare_certain_edit(
        session_id=session_id,
        agent=AgentName.from_str(agent),
        event_type=event_type,
        raw_event_type=raw_event_type,
        data=data,
    )
    additional_context = _maybe_emit_additional_context(
        event_type=event_type,
        cwd=cwd,
        session_id=session_id,
        provider=agent,
        receiver_ingress_id=receiver_ingress_id,
        hook_data=data,
    )
    response_emitted = _maybe_emit_boundary_response(
        event_type=event_type,
        adapter=adapter,
        session_id=session_id,
        hook_data=data,
        context=outbox_context,
        raw_event_type=raw_event_type,
        receiver_ingress_id=receiver_ingress_id,
        additional_context=additional_context,
        initial_procedure_entry_id=initial_procedure_entry_id,
        procedure_wake_occurrence_id=procedure_wake_occurrence_id,
    )
    # Context augments the original event; it does not consume the human prompt.
    # Checkpoint/control-only responses retain their existing terminal behavior.
    stop_processing = (
        response_emitted and event_type != AgentHookEvents.AGENT_SESSION_START and additional_context is None
    )
    return stop_processing, response_emitted


# guard: loose-dict-func - Main path processes raw hook payload boundaries.
def main() -> None:
    """Parse a hook event and enqueue it for daemon processing."""
    args = _parse_args()
    args.agent = AgentName.from_str(args.agent).value
    launch_context = read_compaction_launch_context()
    runtime_run_id = read_runtime_run_id()

    logger.debug(
        "Hook receiver start",
        argv=sys.argv,
        cwd=os.getcwd(),
        stdin_tty=sys.stdin.isatty(),
        has_event_arg=bool(args.event_type),
        agent=args.agent,
    )

    adapter = get_adapter(args.agent)

    raw_input, raw_event_type, raw_data = _parse_receiver_input(args, adapter)
    _log_raw_input(raw_input, log_raw=True)
    data = adapter.normalize_payload(dict(raw_data))
    if launch_context is not None:
        data[COMPACTION_LAUNCH_CONTEXT_FIELD] = cast(JsonValue, launch_context.to_payload())
    raw_native_session_id, raw_native_log_file = _extract_native_hook_fields(data)
    receiver_ingress_id = str(uuid4())
    invocation_num = raw_data.get(_INVOCATION_NUM_FIELD)
    fully_idle = raw_data.get(_FULLY_IDLE_FIELD)
    execution_num = raw_data.get(_EXECUTION_NUM_FIELD)
    step_idx = raw_data.get(_STEP_IDX_FIELD)
    logger.info(
        EVENT_HOOK_INGRESS_ACCEPTED,
        receiver_ingress_id=receiver_ingress_id,
        provider=args.agent,
        raw_event=raw_event_type,
        native_session_id=(raw_native_session_id or _EMPTY_LOG_VALUE),
        invocation_num=(
            invocation_num if isinstance(invocation_num, int) and not isinstance(invocation_num, bool) else None
        ),
        fully_idle=(fully_idle if isinstance(fully_idle, bool) else None),
        execution_num=(
            execution_num if isinstance(execution_num, int) and not isinstance(execution_num, bool) else None
        ),
        step_idx=(step_idx if isinstance(step_idx, int) and not isinstance(step_idx, bool) else None),
    )
    try:
        normalization = adapter.normalize_event(raw_event_type, raw_data)
    except ValueError as exc:
        logger.error(
            _HOOK_NORMALIZATION_FAILED,
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event=raw_event_type,
            error=str(exc),
        )
        sys.exit(1)

    if _handle_native_tool_admission(
        adapter=adapter,
        raw_event_type=raw_event_type,
        data=data,
        provider=args.agent,
        receiver_ingress_id=receiver_ingress_id,
        native_session_id=raw_native_session_id,
    ):
        return

    event_type = normalization.event_type
    if event_type is None:
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event_type=raw_event_type,
            outcome=HookNormalizationOutcome.DROPPED,
            reason=normalization.reason,
            event_type=None,
            native_session_id=raw_native_session_id,
        )
        _emit_success_response_if_supported(
            adapter=adapter,
            raw_event_type=raw_event_type,
            event_type=event_type,
            reason=normalization.reason,
            provider=args.agent,
            receiver_ingress_id=receiver_ingress_id,
            session_id=None,
        )
        return

    if event_type not in _HANDLED_EVENTS:
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event_type=raw_event_type,
            outcome=HookNormalizationOutcome.DROPPED,
            reason=ReceiverDropReason.UNHANDLED_EVENT,
            event_type=None,
            native_session_id=raw_native_session_id,
        )
        return

    event_type = AgentHookEvents(event_type)
    _attach_blocked_status_reason(data, event_type, normalization.reason)
    outbox_context = _ReceiverOutboxContext(
        agent=args.agent,
        event_type=event_type,
        outbox_db=_get_default_outbox_db(),
        runtime_run_id=runtime_run_id,
        launch_context=launch_context,
    )
    execution_kind = adapter.classify_execution_kind(data)

    # Drop Codex subagent events BEFORE session resolution. Session resolution
    # persists `codex:<native_id> -> <teleclaude_session>` to the session map,
    # which for a subagent native id would silently bind it to the parent
    # session — violating the Session Identity Truth Spec.
    if args.agent == AgentName.CODEX.value and is_codex_subagent_transcript(raw_native_log_file):
        logger.debug(
            "subagent_drop",
            session_id="",
            agent=args.agent,
            native_session_id=(raw_native_session_id or ""),
            native_log_file=(raw_native_log_file or ""),
            caller="receiver.main",
        )
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event_type=raw_event_type,
            outcome=HookNormalizationOutcome.DROPPED,
            reason=ReceiverDropReason.CODEX_SUBAGENT,
            event_type=None,
            native_session_id=raw_native_session_id,
        )
        return

    if event_type not in _DEFERRED_FORWARD_LOG_EVENTS:
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event_type=raw_event_type,
            outcome=HookNormalizationOutcome.FORWARDED,
            reason=normalization.reason,
            event_type=event_type,
            native_session_id=raw_native_session_id,
        )

    teleclaude_session_id, source_kind = _resolve_receiver_session_id(
        args.agent,
        event_type,
        raw_event_type,
        raw_native_session_id,
        adapter,
        execution_kind,
    )
    if not teleclaude_session_id:
        return

    logger.info(
        EVENT_HOOK_SESSION_RESOLVED,
        receiver_ingress_id=receiver_ingress_id,
        provider=args.agent,
        session_id=teleclaude_session_id,
        native_session_id=(raw_native_session_id or _EMPTY_LOG_VALUE),
        source_kind=source_kind,
    )

    if event_type == AgentHookEvents.AGENT_SESSION_START and source_kind is HookSourceKind.MANAGED_DESCENDANT:
        logger.debug(
            _MANAGED_DESCENDANT_SESSION_START_DROPPED,
            agent=args.agent,
            session_id=teleclaude_session_id,
            native_session_id=(raw_native_session_id or ""),
        )
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event_type=raw_event_type,
            outcome=HookNormalizationOutcome.DROPPED,
            reason=ReceiverDropReason.MANAGED_DESCENDANT_SESSION_START,
            event_type=None,
            native_session_id=raw_native_session_id,
        )
        _emit_success_response_if_supported(
            adapter=adapter,
            raw_event_type=raw_event_type,
            event_type=None,
            reason=normalization.reason,
            provider=args.agent,
            receiver_ingress_id=receiver_ingress_id,
            session_id=teleclaude_session_id,
        )
        return

    if event_type == AgentHookEvents.AGENT_SESSION_START:
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event_type=raw_event_type,
            outcome=HookNormalizationOutcome.FORWARDED,
            reason=normalization.reason,
            event_type=event_type,
            native_session_id=raw_native_session_id,
        )

    logger.debug(
        "Hook event received",
        event_type=event_type,
        session_id=teleclaude_session_id,
        agent=args.agent,
    )

    logger.debug(
        "Hook payload summary",
        event_type=event_type,
        agent=args.agent,
        session_id=teleclaude_session_id,
        raw_native_session_id=raw_native_session_id,
        raw_transcript_path=raw_native_log_file,
        source_kind=source_kind,
        execution_kind=(execution_kind or ""),
    )

    # Preserve native_session_id if present (needed for later tooling lookups)
    if raw_native_session_id:
        data["native_session_id"] = raw_native_session_id
    if raw_native_log_file:
        data["native_log_file"] = raw_native_log_file
    data[_SOURCE_KIND_FIELD] = source_kind
    data[_EXECUTION_KIND_FIELD] = execution_kind
    _enrich_headless_bootstrap(data, event_type, source_kind)

    if (
        launch_context is None
        and (raw_native_session_id or raw_native_log_file)
        and source_kind is not HookSourceKind.MANAGED_DESCENDANT
    ):
        try:
            _persist_native_metadata(
                session_id=teleclaude_session_id,
                raw_native_session_id=raw_native_session_id,
                raw_native_log_file=raw_native_log_file,
                context=outbox_context,
            )
        except SQLAlchemyError as exc:
            logger.warning(
                "Hook metadata update failed (ignored)",
                event_type=event_type,
                session_id=teleclaude_session_id,
                agent=args.agent,
                error=str(exc),
            )

    cwd = getattr(args, "cwd", None)
    if isinstance(cwd, str) and cwd:
        data["cwd"] = cwd

    if event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
        _log_normalization_decision(
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event_type=raw_event_type,
            outcome=HookNormalizationOutcome.FORWARDED,
            reason=normalization.reason,
            event_type=event_type,
            native_session_id=raw_native_session_id,
        )

    stop_processing, response_emitted = _run_ordinary_hook_effects(
        launch_context=launch_context,
        adapter=adapter,
        event_type=event_type,
        data=data,
        agent=args.agent,
        session_id=teleclaude_session_id,
        raw_native_session_id=raw_native_session_id,
        receiver_ingress_id=receiver_ingress_id,
        cwd=args.cwd,
        outbox_context=outbox_context,
        raw_event_type=raw_event_type,
    )
    if stop_processing:
        return

    data[_AGENT_NAME_FIELD] = args.agent
    data[_RECEIVED_AT_FIELD] = datetime.now(UTC).isoformat()
    _attach_launch_context(data, outbox_context)
    _attach_attention_observation(data, event_type, raw_event_type, raw_data, receiver_ingress_id)

    debounce_window_s = _HOOK_COALESCE_WINDOWS_S.get(event_type)
    if args.agent == AgentName.CODEX.value and event_type == AgentHookEvents.AGENT_STOP:
        # Codex emits many stops per turn; the wider window absorbs the burst.
        debounce_window_s = _CODEX_NOTIFY_DEBOUNCE_WINDOW_S
    enqueue_hook_event(
        teleclaude_session_id,
        event_type,
        data,
        outbox_db=outbox_context.outbox_db,
        latest_wins_within_s=debounce_window_s,
    )
    logger.info(
        EVENT_HOOK_OUTBOX_ENQUEUED,
        receiver_ingress_id=receiver_ingress_id,
        provider=args.agent,
        session_id=teleclaude_session_id,
        native_session_id=(raw_native_session_id or _EMPTY_LOG_VALUE),
        event_type=event_type,
    )
    if not response_emitted:
        _emit_success_response_if_supported(
            adapter=adapter,
            raw_event_type=raw_event_type,
            event_type=event_type,
            reason=normalization.reason,
            provider=args.agent,
            receiver_ingress_id=receiver_ingress_id,
            session_id=teleclaude_session_id,
        )


_RECEIVER_EXPORT_BINDINGS = (_read_stdin, _render_person_header)
