"""Unified hook receiver for agent CLIs."""

from __future__ import annotations

import argparse
import hashlib
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
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session as SqlSession
from sqlmodel import select

from teleclaude import paths as tc_paths
from teleclaude.config.loader import load_company_config, load_global_config, load_project_config
from teleclaude.constants import UI_MESSAGE_MAX_CHARS, HookSourceKind
from teleclaude.core import db_models
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.codex_transcript import is_codex_subagent_transcript
from teleclaude.core.control_delivery import IDLE_WAKE_TEXT
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.events import AgentHookEventCatalog, AgentHookEvents, AgentHookEventType
from teleclaude.core.identity import derive_identity_key
from teleclaude.core.injected_text import EnvelopeField, EnvelopeName, render_xml_envelope, semantic_envelope
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters import get_adapter
from teleclaude.hooks.adapters.base import HookAdapter, HookNormalizationReason, HookResponseKind, read_stdin_payload
from teleclaude.hooks.checkpoint import get_checkpoint_content
from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_CLEAR_FLAG,
    CHECKPOINT_COMMIT_OBLIGATIONS_FLAG,
    CHECKPOINT_RECHECK_FLAG,
    consume_checkpoint_flag,
    is_checkpoint_disabled,
)
from teleclaude.hooks.receiver._session import (
    _SESSION_EXPORTS,
    _classify_hook_source,
    _create_sync_engine,
    _find_session_id_by_native,
    _get_cached_session_id,
    _get_memory_context,
    _get_session_map_path,
    _get_tmux_contract_tmpdir,
    _is_tmux_contract_session_compatible,
    _load_session_map,
    _persist_session_map,
    _resolve_hook_session_id,
    _resolve_or_refresh_session_id,
    _session_map_key,
    _write_session_map_atomic,
    get_outbox_session,
)
from teleclaude.hooks.receiver_args import parse_receiver_args
from teleclaude.session_identity import inspect_session_identity_marker
from teleclaude.utils.transcript import extract_workdir_from_transcript, is_runtime_artifact_text

if TYPE_CHECKING:
    from teleclaude.config.schema import CompanyConfig, PersonEntry

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

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
EVENT_CONTROL_DELIVERY_TERMINAL = "control_delivery_batch_terminal"
EVENT_CONTROL_DELIVERY_HOOK_ARRIVAL = "control_delivery_hook_arrival"
EVENT_CHECKPOINT_EVIDENCE_ADDRESS_RESOLVED = "checkpoint_evidence_address_resolved"
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
_HANDLED_EVENTS: frozenset[AgentHookEventType] = AgentHookEventCatalog.RECEIVER_HANDLED
_DEFERRED_FORWARD_LOG_EVENTS: frozenset[AgentHookEventType] = frozenset(
    {
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.USER_PROMPT_SUBMIT,
    }
)
_CODEX_NOTIFY_DEBOUNCE_WINDOW_S = 10.0
_TMUX_ENV = "TMUX"
_HOOK_SESSION_NO_MAPPING = "Hook session has no TeleClaude mapping, dropping event"
_MANAGED_IDENTITY_FAILURE = "Managed hook identity could not be resolved, dropping event"
_MANAGED_DESCENDANT_SESSION_START_DROPPED = "Dropped managed descendant session_start"
_IDENTITY_PERSON_RESOLUTION_FAILED = "identity_person_resolution_failed"
_COMPANY_RESOLUTION_FAILED = "company_resolution_failed"
_HOOK_NORMALIZATION_FAILED = "Hook event normalization failed"
_SOURCE_KIND_FIELD = "source_kind"
_HEADLESS_BOOTSTRAP_FIELD = "headless_bootstrap"
_EXECUTION_KIND_FIELD = "execution_kind"
_INVOCATION_NUM_FIELD = "invocationNum"
_FULLY_IDLE_FIELD = "fullyIdle"
_EXECUTION_NUM_FIELD = "executionNum"
_STEP_IDX_FIELD = "stepIdx"
_HUMAN_PROFILE_ROOT = "human"
_EMPTY_LOG_VALUE = ""
_MODEL_DUMP_MODE = "json"


class HookNormalizationOutcome(StrEnum):
    """Receiver-observed result of provider event normalization."""

    FORWARDED = "forwarded"
    DROPPED = "dropped"


class ReceiverDropReason(StrEnum):
    """Receiver-owned reasons for drops after provider normalization."""

    CODEX_SUBAGENT = "codex_subagent"
    MANAGED_DESCENDANT_SESSION_START = "managed_descendant_session_start"
    SYSTEM_INJECTED_PROMPT = "system_injected_prompt"
    UNHANDLED_EVENT = "unhandled_event"


class HookResponseFormat(StrEnum):
    """Serialization formats committed to provider stdout."""

    JSON = "json"
    PLAIN_TEXT = "plain_text"


class ControlDeliveryEligibility(StrEnum):
    NOT_DELIVERY_BOUNDARY = "not_delivery_boundary"
    NO_PENDING = "no_pending"
    DRAINED = "drained"


class ControlDeliveryTerminalReason(StrEnum):
    OK = "ok"
    WRITE_FAILED = "write_failed"
    FLUSH_FAILED = "flush_failed"
    ROWS_ABSENT = "rows_absent"


class HookResponseWriteError(OSError):
    """A provider response could not be written to stdout."""


class HookResponseFlushError(OSError):
    """A provider response was written but stdout could not be flushed."""


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
    AgentHookEvents.PRE_TOOL_USE: 1.0,
    AgentHookEvents.AGENT_STOP: 1.0,
    AgentHookEvents.NATIVE_METADATA_UPDATE: 1.0,
}


@dataclass(frozen=True)
class _ReceiverOutboxContext:
    """Shared receiver metadata for mutation events emitted to the outbox."""

    agent: str
    event_type: str
    outbox_db: str


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


def _load_session_row(session_id: str) -> db_models.Session | None:
    """Load a session row synchronously for hook processing."""
    with SqlSession(_create_sync_engine()) as db_session:
        return db_session.get(db_models.Session, session_id)


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
        return _load_session_row(session_id)
    except SQLAlchemyError as exc:
        logger.debug("Checkpoint eval skipped (db error)", error=str(exc))
        return None


def _resolve_identity_context(
    session_id: str,
    *,
    receiver_ingress_id: str = _EMPTY_LOG_VALUE,
) -> tuple[str | None, str | None]:
    """Return identity-key and person header metadata for additional context."""
    row = _load_session_row(session_id)
    if not row:
        return None, None
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
        return identity_key, None
    people = load_global_config().people
    person = next((person for person in people if person.email == human_email), None)
    if person is None:
        return identity_key, None
    return identity_key, _render_person_header(
        person,
        receiver_ingress_id=receiver_ingress_id,
        session_id=session_id,
    )


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
    # New user input starts a fresh checkpoint turn.
    consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)
    consume_checkpoint_flag(session_id, CHECKPOINT_CLEAR_FLAG)
    consume_checkpoint_flag(session_id, CHECKPOINT_COMMIT_OBLIGATIONS_FLAG)


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
        turn_anchor_sha=getattr(row, "turn_anchor_sha", None),
        system_role=getattr(row, "system_role", None),
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
    receiver_ingress_id: str = _EMPTY_LOG_VALUE,
    session_id: str = _EMPTY_LOG_VALUE,
) -> str:
    """Render the complete non-null person entry as human-readable YAML."""
    person_data = person.model_dump(mode=_MODEL_DUMP_MODE, exclude_none=True)
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


def _resolve_company_header(cwd: str | None) -> str | None:
    """Resolve the active project's company-profile header, or ``None``.

    The PROJECT determines the company (a project belongs to exactly one company),
    not the owning human's company set. No project context, no project ``company``,
    or an unknown company yields no header — never another company's profile.
    """
    if not cwd:
        return None
    project_yml = Path(cwd) / tc_paths.ConfigFileName.OVERLAY
    if not project_yml.exists():
        return None
    company_slug = load_project_config(project_yml).company
    if not company_slug:
        return None
    company_yml = tc_paths.COMPANIES_ROOT / company_slug / tc_paths.ConfigFileName.OVERLAY
    if not company_yml.exists():
        # A declared-but-unconfigured company is a misconfiguration, not a no-op:
        # surface it visibly rather than silently injecting nothing (which reads as
        # "no company"). No other company's profile is leaked.
        logger.warning("project_company_unconfigured", company=company_slug)
        return (
            f"WARNING: this project declares company '{company_slug}', but no such company is "
            f"configured under {tc_paths.COMPANIES_ROOT}. No company profile injected — fix the "
            "project's `company:` membership or onboard the company."
        )
    return _render_company_header(load_company_config(company_yml))


def _print_additional_context(
    hook_event_name: str,
    cwd: str | None,
    adapter: object,
    session_id: str,
    *,
    provider: str,
    receiver_ingress_id: str,
) -> str | None:
    """Gather startup context; the boundary owns the single eventual response."""
    project_name = Path(cwd).name if cwd else None
    if not project_name:
        return None

    identity_key: str | None = None
    person_header: str | None = None
    try:
        identity_key, person_header = _resolve_identity_context(
            session_id,
            receiver_ingress_id=receiver_ingress_id,
        )
    except (SQLAlchemyError, TypeError, ValueError, json.JSONDecodeError):
        logger.debug(_IDENTITY_PERSON_RESOLUTION_FAILED, session_id=session_id)

    company_header: str | None = None
    try:
        company_header = _resolve_company_header(cwd)
    except (OSError, ValueError):
        logger.debug(_COMPANY_RESOLUTION_FAILED, project_name=project_name)

    memory_context = _get_memory_context(project_name, identity_key=identity_key)
    if not memory_context and not person_header and not company_header:
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

    parts: list[str] = []
    if company_header:
        parts.append(company_header)
    if person_header:
        parts.append(person_header)
    if memory_context:
        parts.append(memory_context)
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
        person_context_present=bool(person_header),
        memory_context_present=bool(memory_context),
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
        if not session_id:
            logger.error(
                "Receiver error with unknown session",
                agent=args.agent,
                event_type=getattr(args, "event_type", None),
                code=code,
                message=message,
            )
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
        logger.error("Receiver error reporting failed", error=str(exc), code=code)


def _parse_receiver_input(args: argparse.Namespace, adapter: object) -> tuple[str, str, JsonDict]:
    try:
        return adapter.parse_input(args)  # type: ignore[union-attr]
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
    adapter: object,
    raw_event_type: str,
    event_type: str | None,
    reason: HookNormalizationReason,
    provider: str,
    receiver_ingress_id: str,
    session_id: str | None,
) -> bool:
    success_response = adapter.format_success_response(raw_event_type)  # type: ignore[union-attr]
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


def _resolve_receiver_session_id(
    agent: str,
    event_type: str,
    raw_event_type: str,
    raw_native_session_id: str | None,
    adapter: object,
    execution_kind: str | None,
) -> tuple[str | None, HookSourceKind]:
    marker_state, marker_session_id = inspect_session_identity_marker()
    source_kind = _classify_hook_source(marker_state, bool(os.getenv(_TMUX_ENV)))
    try:
        teleclaude_session_id, cached_session_id, existing_id = _resolve_hook_session_id(
            agent=agent,
            event_type=event_type,
            native_session_id=raw_native_session_id,
            source_kind=source_kind,
            marker_state=marker_state,
            marker_session_id=marker_session_id,
            mint_events=adapter.mint_events,  # type: ignore[union-attr]
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
    enqueue_hook_event(
        session_id,
        AgentHookEvents.NATIVE_SESSION_REFRESH,
        {
            "agent": context.agent,
            "source_event_type": context.event_type,
            "native_session_id": native_session_id,
        },
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

    row = _load_session_row(session_id)
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
) -> bool:
    if event_type != AgentHookEvents.USER_PROMPT_SUBMIT:
        return False
    prompt_value = data.get("prompt")
    prompt_text = prompt_value if isinstance(prompt_value, str) else ""
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
        if prompt_text == IDLE_WAKE_TEXT:
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
    raw_event_type: str,
    event_type: str,
    cwd: str | None,
    adapter: object,
    session_id: str,
    provider: str,
    receiver_ingress_id: str,
) -> str | None:
    """Emit stdout additional context for context-injection hook events.

    This lane is distinct from checkpoint blocking on Stop.
    """
    if event_type != AgentHookEvents.AGENT_SESSION_START:
        return None
    if cwd:
        project_name = Path(cwd).name
        logger.debug("Emitting additional context for session_start", project=project_name)
        return _print_additional_context(
            raw_event_type,
            cwd,
            adapter,
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
    adapter: object,
    session_id: str,
    hook_data: JsonDict,
    context: _ReceiverOutboxContext,
    raw_event_type: str,
    receiver_ingress_id: str,
) -> str | None:
    if event_type != AgentHookEvents.AGENT_STOP or not adapter.supports_hook_checkpoint:  # type: ignore[union-attr]
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


def _render_control_payload(row: db_models.ControlDelivery) -> str:
    """Render one persisted semantic control payload at its hook boundary."""
    if row.envelope_name is None:
        return row.body
    raw_fields = json.loads(row.envelope_fields_json or "{}")
    if not isinstance(raw_fields, dict) or not all(isinstance(value, str) for value in raw_fields.values()):
        raise ValueError("control payload has invalid semantic envelope fields")
    fields = {EnvelopeField(name): value for name, value in raw_fields.items()}
    return render_xml_envelope(semantic_envelope(EnvelopeName(row.envelope_name), fields=fields, body=row.body))


def _emit_pending_control_payloads(
    *,
    adapter: object,
    raw_event_type: str,
    session_id: str,
    provider: str,
    internal_event: str,
    receiver_ingress_id: str,
    checkpoint_reason: str | None = None,
    startup_context: str | None = None,
) -> bool:
    """Drain one session's ordered control batch at an adapter-declared boundary."""
    delivery_events = getattr(adapter, "delivery_events", frozenset())
    if raw_event_type not in {event.value for event in delivery_events}:
        logger.info(
            EVENT_CONTROL_DELIVERY_HOOK_ARRIVAL,
            session_id=session_id,
            runtime=provider,
            native_event=raw_event_type,
            internal_event=internal_event,
            eligibility=ControlDeliveryEligibility.NOT_DELIVERY_BOUNDARY,
        )
        return False

    with SqlSession(_create_sync_engine()) as db_session:
        table = cast(Any, db_models.ControlDelivery).__table__
        db_session.connection().exec_driver_sql("BEGIN IMMEDIATE")  # guard: raw-sql
        rows = db_session.exec(
            select(db_models.ControlDelivery)
            .where(db_models.ControlDelivery.session_id == session_id)
            .where(table.c.outcome.is_(None))
            .order_by(table.c.id.asc())
        ).all()
        if not rows:
            db_session.commit()
            logger.info(
                EVENT_CONTROL_DELIVERY_HOOK_ARRIVAL,
                session_id=session_id,
                runtime=provider,
                native_event=raw_event_type,
                internal_event=internal_event,
                eligibility=ControlDeliveryEligibility.NO_PENDING,
            )
            if startup_context is not None:
                _emit_provider_response(
                    adapter.format_additional_context(raw_event_type, startup_context),  # type: ignore[union-attr]
                    response_kind=HookResponseKind.STARTUP_CONTEXT,
                    response_format=HookResponseFormat.JSON,
                    provider=provider,
                    raw_event_type=raw_event_type,
                    receiver_ingress_id=receiver_ingress_id,
                    session_id=session_id,
                )
                return True
            if checkpoint_reason is None:
                return False
            checkpoint_json = adapter.format_checkpoint_response(checkpoint_reason)  # type: ignore[union-attr]
            if checkpoint_json:
                _emit_provider_response(
                    checkpoint_json,
                    response_kind=adapter.checkpoint_response_kind,  # type: ignore[union-attr]
                    response_format=HookResponseFormat.JSON,
                    provider=provider,
                    raw_event_type=raw_event_type,
                    receiver_ingress_id=receiver_ingress_id,
                    session_id=session_id,
                )
                return True
            return False
        row_ids = [row.id for row in rows if row.id is not None]
        logger.info(
            EVENT_CONTROL_DELIVERY_HOOK_ARRIVAL,
            session_id=session_id,
            runtime=provider,
            native_event=raw_event_type,
            internal_event=internal_event,
            eligibility=ControlDeliveryEligibility.DRAINED,
        )
        context = "\n\n".join(
            part for part in (startup_context, *(_render_control_payload(row) for row in rows)) if part
        )
        payload = adapter.format_event_response(checkpoint_reason, raw_event_type, context)  # type: ignore[union-attr]
        try:
            _emit_provider_response(
                payload,
                response_kind=(
                    cast(HookAdapter, adapter).checkpoint_response_kind
                    if checkpoint_reason is not None
                    else HookResponseKind.STARTUP_CONTEXT
                ),
                response_format=HookResponseFormat.JSON if payload != context else HookResponseFormat.PLAIN_TEXT,
                provider=provider,
                raw_event_type=raw_event_type,
                receiver_ingress_id=receiver_ingress_id,
                session_id=session_id,
            )
        except (HookResponseWriteError, HookResponseFlushError) as exc:
            terminal_outcome = db_models.ControlDeliveryOutcome.FAILED.value
            db_session.exec(
                update(table)
                .where(table.c.session_id == session_id)
                .where(table.c.id.in_(row_ids))
                .where(table.c.outcome.is_(None))
                .values(outcome=terminal_outcome, terminal_at=datetime.now(UTC).isoformat())
            )
            db_session.commit()
            logger.info(
                EVENT_CONTROL_DELIVERY_TERMINAL,
                session_id=session_id,
                row_ids=row_ids,
                runtime=provider,
                internal_event=internal_event,
                body_digest=hashlib.sha256(payload.encode()).hexdigest(),
                outcome="failed",
                reason=(
                    ControlDeliveryTerminalReason.FLUSH_FAILED
                    if isinstance(exc, HookResponseFlushError)
                    else ControlDeliveryTerminalReason.WRITE_FAILED
                ),
            )
            raise
        terminal_outcome = db_models.ControlDeliveryOutcome.DELIVERED.value
        db_session.exec(
            update(table)
            .where(table.c.session_id == session_id)
            .where(table.c.id.in_(row_ids))
            .where(table.c.outcome.is_(None))
            .values(outcome=terminal_outcome, terminal_at=datetime.now(UTC).isoformat())
        )
        db_session.commit()
    logger.info(
        EVENT_CONTROL_DELIVERY_TERMINAL,
        receiver_ingress_id=receiver_ingress_id,
        session_id=session_id,
        raw_event=raw_event_type,
        outcome=terminal_outcome,
        row_ids=row_ids,
        batch_size=len(row_ids),
        runtime=provider,
        internal_event=internal_event,
        body_digest=hashlib.sha256(payload.encode()).hexdigest(),
        reason=ControlDeliveryTerminalReason.OK,
    )
    return True


def _maybe_emit_boundary_response(
    *,
    event_type: str,
    adapter: object,
    session_id: str,
    hook_data: JsonDict,
    context: _ReceiverOutboxContext,
    raw_event_type: str,
    receiver_ingress_id: str,
    startup_context: str | None,
) -> bool:
    """Prioritize checkpoint safety, then emit one pending control batch."""
    checkpoint_reason = _maybe_emit_checkpoint_response(
        event_type=event_type,
        adapter=adapter,
        session_id=session_id,
        hook_data=hook_data,
        context=context,
        raw_event_type=raw_event_type,
        receiver_ingress_id=receiver_ingress_id,
    )
    return _emit_pending_control_payloads(
        adapter=adapter,
        raw_event_type=raw_event_type,
        session_id=session_id,
        provider=context.agent,
        internal_event=event_type,
        receiver_ingress_id=receiver_ingress_id,
        checkpoint_reason=checkpoint_reason,
        startup_context=startup_context,
    )


# guard: loose-dict-func - Main path processes raw hook payload boundaries.
def main() -> None:
    """Parse a hook event and enqueue it for daemon processing."""
    args = _parse_args()
    args.agent = AgentName.from_str(args.agent).value

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
    data = adapter.normalize_payload(dict(raw_data))  # type: ignore[union-attr]
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
        normalization = adapter.normalize_event(raw_event_type, raw_data)  # type: ignore[union-attr]
    except ValueError as exc:
        logger.error(
            _HOOK_NORMALIZATION_FAILED,
            receiver_ingress_id=receiver_ingress_id,
            provider=args.agent,
            raw_event=raw_event_type,
            error=str(exc),
        )
        sys.exit(1)

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

    outbox_context = _ReceiverOutboxContext(agent=args.agent, event_type=event_type, outbox_db=_get_default_outbox_db())
    execution_kind = adapter.classify_execution_kind(data)  # type: ignore[union-attr]

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
    if event_type == AgentHookEvents.AGENT_SESSION_START and source_kind is HookSourceKind.HEADLESS:
        data[_HEADLESS_BOOTSTRAP_FIELD] = True
    else:
        data.pop(_HEADLESS_BOOTSTRAP_FIELD, None)

    if (raw_native_session_id or raw_native_log_file) and source_kind is not HookSourceKind.MANAGED_DESCENDANT:
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

    if _handle_user_prompt_submit(
        event_type,
        data,
        args.agent,
        teleclaude_session_id,
        raw_native_session_id,
        receiver_ingress_id,
    ):
        return

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

    startup_context = _maybe_emit_additional_context(
        raw_event_type=raw_event_type,
        event_type=event_type,
        cwd=args.cwd,
        adapter=adapter,
        session_id=teleclaude_session_id,
        provider=args.agent,
        receiver_ingress_id=receiver_ingress_id,
    )
    if _maybe_emit_boundary_response(
        event_type=event_type,
        adapter=adapter,
        session_id=teleclaude_session_id,
        hook_data=data,
        context=outbox_context,
        raw_event_type=raw_event_type,
        receiver_ingress_id=receiver_ingress_id,
        startup_context=startup_context,
    ):
        return

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(UTC).isoformat()

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
    if startup_context is None:
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
