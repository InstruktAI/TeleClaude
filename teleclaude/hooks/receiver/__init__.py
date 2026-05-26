"""Unified hook receiver for agent CLIs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import configure_logging, get_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session as SqlSession
from sqlmodel import select

from teleclaude import paths as tc_paths
from teleclaude.config.loader import load_global_config
from teleclaude.constants import CHECKPOINT_PREFIX, DOMAIN_SCOPES, UI_MESSAGE_MAX_CHARS
from teleclaude.core import db_models
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.codex_transcript import is_codex_subagent_transcript
from teleclaude.core.conversation_messages import is_machine_originated_user_text
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.identity import derive_identity_key
from teleclaude.core.models import JsonDict
from teleclaude.hooks.adapters import get_adapter
from teleclaude.hooks.adapters.base import read_stdin_payload
from teleclaude.hooks.checkpoint import get_checkpoint_content
from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_RECHECK_FLAG,
    consume_checkpoint_flag,
    is_checkpoint_disabled,
)
from teleclaude.hooks.receiver._session import (
    _SESSION_EXPORTS,
    _create_sync_engine,
    _find_session_id_by_native,
    _get_cached_session_id,
    _get_memory_context,
    _get_session_map_path,
    _get_tmux_contract_session_id,
    _get_tmux_contract_tmpdir,
    _is_headless_route,
    _is_tmux_contract_session_compatible,
    _load_session_map,
    _persist_session_map,
    _resolve_hook_session_id,
    _resolve_or_refresh_session_id,
    _session_map_key,
    _write_session_map_atomic,
    get_outbox_session,
)
from teleclaude.utils.transcript import extract_workdir_from_transcript

if TYPE_CHECKING:
    from teleclaude.config.schema import PersonEntry

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

# Structured log event names for the domain-baseline SessionStart path.
# Production and tests reference these by name (Testing — String Assertions,
# mode #3: named-constant identity) instead of inlining the event string.
EVENT_COMMAND_DOMAIN_NOT_ALLOWLISTED = "command_domain_not_allowlisted"
EVENT_DOMAIN_BASELINE_UNAVAILABLE = "domain_baseline_unavailable"
_SESSION_EXPORT_BINDINGS = (
    _get_session_map_path,
    _get_tmux_contract_session_id,
    _get_tmux_contract_tmpdir,
    _is_tmux_contract_session_compatible,
    _load_session_map,
    _persist_session_map,
    _resolve_or_refresh_session_id,
    _session_map_key,
    _write_session_map_atomic,
)

_CODEX_HOOK_PROMPT_RE = re.compile(r"^\s*<hook_prompt\b", re.DOTALL)
_CLAUDE_HOOK_FEEDBACK_PREFIXES = ("Stop hook feedback:", "PreToolUse hook feedback:")
_CLAUDE_CLI_INTERNAL_PROMPT_RE = re.compile(r"^\s*<(task-notification|system-reminder)\b", re.DOTALL)

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
_HANDLED_EVENTS: frozenset[AgentHookEventType] = AgentHookEvents.RECEIVER_HANDLED
_CODEX_NOTIFY_DEBOUNCE_WINDOW_S = 10.0

# Receiver-side UPSERT coalesce windows. Within the window, a new emit for the
# same (session_id, event_type) overwrites the prior unclaimed row instead of
# inserting a new one — payload + timestamp are updated in place. Claimed rows
# (locked_at NOT NULL) are never replaced; the new emit falls through to INSERT.
#
# Event types not in this map insert one row per emit. The codex-specific
# 10 s window for agent_stop overrides the 1 s baseline below.
_HOOK_COALESCE_WINDOWS_S: dict[str, float] = {
    AgentHookEvents.TOOL_USE: 1.0,
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


def _resolve_identity_context(session_id: str) -> tuple[str | None, str | None]:
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
    return identity_key, _render_person_header(person)


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
    # Keep CLEAR persistent across turns; clear the per-turn fired marker so
    # the next turn's first checkpoint can fire.
    consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)


def _maybe_checkpoint_output(
    session_id: str,
    agent: str,
    raw_data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    *,
    outbox_db: str,
) -> str | None:
    """Evaluate whether to block an agent_stop with a checkpoint instruction.

    Returns the checkpoint reason string if a checkpoint is warranted, or None
    to let the stop pass through to the normal enqueue path. The caller is
    responsible for formatting the reason into agent-specific JSON via the adapter.
    """
    # Session-scoped persistent disable: while clear marker exists, skip checkpoints.
    if is_checkpoint_disabled(session_id):
        consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)
        logger.info("Checkpoint skipped (persistent clear flag)", session_id=session_id, agent=agent)
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
    transcript_path = getattr(row, "native_log_file", None)
    working_slug = getattr(row, "working_slug", None)
    project_path = _resolve_checkpoint_project_path(row)

    logger.debug("Checkpoint eval for session %s (%.1fs elapsed)", session_id, elapsed)

    checkpoint_reason = get_checkpoint_content(
        session_id=session_id,
        transcript_path=transcript_path,
        agent_name=_resolve_agent_enum(agent),
        project_path=project_path,
        native_session_id=getattr(row, "native_session_id", None),
        working_slug=working_slug,
        elapsed_since_turn_start_s=elapsed,
        turn_anchor_sha=getattr(row, "turn_anchor_sha", None),
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


def _render_person_header(person: PersonEntry) -> str:
    """Render human-readable header for the human who owns this session chain."""
    name = person.name
    expertise = person.expertise

    if not expertise:
        return f"Human owner: {name}"

    lines = [f"Human owner: {name}", "Expertise:"]
    for domain, value in expertise.items():
        lines.append(f"  {domain}: {value}")
    return "\n".join(lines)


def _resolve_command_domain_for_session(session_id: str) -> str | None:
    """Return the `command_domain` recorded on a session's origin_metadata.

    The CLI's `/sessions/run` endpoint resolves the dispatched slash command's
    `domain:` frontmatter and persists it on `origin_metadata.command_domain`.
    This helper lets the SessionStart hook discover that value so the
    domain-baseline content is injected BEFORE the agent processes the
    command's own Required reads.

    Returns the domain only when it matches the configured allowlist
    (``DOMAIN_SCOPES``). Anything else — unknown values, path-traversal
    attempts, malformed metadata — is rejected.
    """
    try:
        row = _load_session_row(session_id)
    except SQLAlchemyError:
        return None
    if not row or not row.origin_metadata:
        return None
    try:
        origin = json.loads(row.origin_metadata)
    except json.JSONDecodeError:
        return None
    if not isinstance(origin, dict):
        return None
    domain = origin.get("command_domain")
    if not isinstance(domain, str) or not domain:
        # origin_metadata is composite — keyed by origin type (terminal/web/discord),
        # each holding its own sub-dict. The command_domain set at dispatch lives
        # inside the dispatching origin's sub-dict, not at the top level.
        domain = next(
            (
                nested["command_domain"]
                for nested in origin.values()
                if isinstance(nested, dict)
                and isinstance(nested.get("command_domain"), str)
                and nested["command_domain"]
            ),
            None,
        )
    if not isinstance(domain, str) or not domain:
        return None
    if domain not in DOMAIN_SCOPES:
        logger.warning(EVENT_COMMAND_DOMAIN_NOT_ALLOWLISTED, session_id=session_id, domain=domain)
        return None
    return domain


class DomainBaselineUnavailable(RuntimeError):
    """Raised when a session's configured domain baseline cannot be loaded."""


def _load_domain_baseline_content(domain: str) -> str:
    """Return the inflated content of the named domain baseline.

    The deploy pipeline writes a single fully-expanded baseline file at
    ``~/.teleclaude/docs/<domain>/baseline.md`` per source manifest. This
    helper reads it for injection at SessionStart so the agent — including
    runtimes that do not auto-follow ``@`` refs — has the full domain
    process-enforcement baseline loaded before the first user message.

    The caller is expected to have validated ``domain`` against
    ``DOMAIN_SCOPES``. As defence-in-depth, the resolved path is verified to
    live under the canonical docs root before reading. Raises
    ``DomainBaselineUnavailable`` when the deployed baseline is missing,
    unreadable, or empty — the SessionStart hook surfaces this as a visible
    failure rather than silently dropping mandatory context.
    """
    docs_root = tc_paths.GLOBAL_SNIPPETS_DIR.resolve()
    candidate = (docs_root / domain / "baseline.md").resolve()
    if docs_root not in candidate.parents:
        raise DomainBaselineUnavailable(f"resolved baseline path {candidate} escapes {docs_root}")
    if not candidate.is_file():
        raise DomainBaselineUnavailable(f"deployed baseline missing at {candidate}")
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError as exc:
        raise DomainBaselineUnavailable(f"failed to read {candidate}: {exc}") from exc
    if not text.strip():
        raise DomainBaselineUnavailable(f"deployed baseline at {candidate} is empty")
    return text


def _print_additional_context(
    hook_event_name: str,
    cwd: str | None,
    adapter: object,
    session_id: str | None = None,
) -> None:
    """Print stdout additional context for hook events that support context injection."""
    project_name = Path(cwd).name if cwd else None
    if not project_name:
        return

    identity_key: str | None = None
    person_header: str | None = None
    if session_id:
        try:
            identity_key, person_header = _resolve_identity_context(session_id)
        except (SQLAlchemyError, TypeError, ValueError, json.JSONDecodeError):
            logger.debug("Identity/person resolution failed for session %s", (session_id or ""))

    domain_baseline: str | None = None
    if session_id:
        domain = _resolve_command_domain_for_session(session_id)
        if domain:
            try:
                domain_baseline = _load_domain_baseline_content(domain)
            except DomainBaselineUnavailable as exc:
                # Mandatory baseline cannot be silently dropped — surface a
                # visible warning so an operator/agent notices the gap. The
                # session still starts; the agent receives a short inline
                # notice instead of pre-loaded process enforcement.
                logger.error(
                    EVENT_DOMAIN_BASELINE_UNAVAILABLE,
                    session_id=session_id,
                    domain=domain,
                    error=str(exc),
                )
                domain_baseline = (
                    f"WARNING: mandatory '{domain}' domain baseline could not be loaded "
                    f"({exc}). Run `telec sync` to regenerate `~/.teleclaude/docs/{domain}/baseline.md`, "
                    "then continue."
                )

    context = _get_memory_context(project_name, identity_key=identity_key)
    if not context and not person_header and not domain_baseline:
        return

    parts: list[str] = []
    if domain_baseline:
        parts.append(domain_baseline)
    if person_header:
        parts.append(person_header)
    if context:
        parts.append(context)
    context = "\n\n".join(parts)

    logger.debug(
        "Additional context fetched", project=project_name, length=len(context), identity_key=identity_key or ""
    )
    payload = adapter.format_additional_context(hook_event_name, context)  # type: ignore[union-attr]
    if payload:
        print(payload)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TeleClaude hook receiver")
    parser.add_argument(
        "--agent",
        required=True,
        choices=(*AgentName.choices(), "agy"),
        help="Agent name for adapter selection",
    )
    parser.add_argument(
        "--cwd",
        default=None,
        help="Caller working directory for headless session attribution",
    )
    parser.add_argument("event_type", nargs="?", default=None, help="Hook event type")
    return parser.parse_args()


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


def _map_hook_event_type(agent: str, raw_event_type: str) -> str:
    event_type = raw_event_type
    agent_map = AgentHookEvents.HOOK_EVENT_MAP.get(agent, {})
    mapped_event_type = agent_map.get(raw_event_type)
    if mapped_event_type:
        event_type = mapped_event_type
        logger.debug("Mapped hook event: %s -> %s", raw_event_type, event_type)
    return event_type


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
) -> str | None:
    headless_route = _is_headless_route()
    try:
        teleclaude_session_id, cached_session_id, existing_id = _resolve_hook_session_id(
            agent=agent,
            event_type=event_type,
            native_session_id=raw_native_session_id,
            headless=headless_route,
            mint_events=adapter.mint_events,  # type: ignore[union-attr]
        )
    except ValueError as exc:
        logger.error(
            "Hook receiver contract violation",
            agent=agent,
            event_type=event_type,
            headless=headless_route,
            error=str(exc),
        )
        sys.exit(1)
    logger.debug(
        "Hook session resolution",
        agent=agent,
        headless=headless_route,
        event_type=event_type,
        cached_session_id=(cached_session_id or ""),
        existing_session_id=(existing_id or ""),
        resolved_session_id=(teleclaude_session_id or ""),
        native_session_id=(raw_native_session_id or ""),
    )
    if teleclaude_session_id:
        return teleclaude_session_id
    logger.debug(
        "Hook session has no TeleClaude mapping, dropping event",
        agent=agent,
        headless=headless_route,
        event_type=event_type,
        raw_event_type=raw_event_type,
        native_session_id=(raw_native_session_id or ""),
        cached_session_id=(cached_session_id or ""),
        existing_session_id=(existing_id or ""),
    )
    return None


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


def _is_teleclaude_system_prompt(prompt_text: str) -> bool:
    """Return True for TeleClaude-owned prompt envelopes that are not user input."""
    stripped = prompt_text.lstrip()
    if stripped.startswith(CHECKPOINT_PREFIX) or stripped.startswith("[TeleClaude Checkpoint]"):
        return True
    if stripped.startswith("[TeleClaude Notification]"):
        return True
    if stripped.startswith("[TeleClaude Input Request]"):
        return True
    if stripped.startswith("[TeleClaude Linked output") or stripped.startswith("[TeleClaude - Linked output"):
        return True
    return is_machine_originated_user_text(stripped)


def _is_system_injected_user_prompt(agent: str, prompt_text: str) -> bool:
    """Return True when a user_prompt_submit payload is an agent/runtime artifact."""
    stripped = prompt_text.lstrip()
    if _is_teleclaude_system_prompt(stripped):
        return True

    if agent == AgentName.CODEX.value and _CODEX_HOOK_PROMPT_RE.match(stripped):
        return True

    if agent == AgentName.CLAUDE.value:
        if stripped.startswith(_CLAUDE_HOOK_FEEDBACK_PREFIXES):
            return True
        if _CLAUDE_CLI_INTERNAL_PROMPT_RE.match(stripped):
            return True

    return False


def _handle_user_prompt_submit(
    event_type: str,
    data: JsonDict,
    agent: str,
    session_id: str,
    raw_native_session_id: str | None,
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
        return False
    if _is_system_injected_user_prompt(agent, prompt_text):
        logger.debug(
            "Dropped system-injected user_prompt_submit",
            agent=agent,
            session_id=session_id,
        )
        return True
    _reset_checkpoint_flags(session_id)
    return False


def _maybe_synthesize_session_start(
    *,
    adapter: object,
    event_type: str,
    session_id: str,
    raw_native_session_id: str | None,
    raw_native_log_file: str | None,
    cwd: str | None,
    context: _ReceiverOutboxContext,
) -> None:
    """Seed a synthetic session_start for CLIs that emit no native one.

    Antigravity (agy) opens a conversation with PreInvocation, not SessionStart.
    The daemon only creates/binds a session row on session_start, so the first
    activity event of an unbound conversation enqueues a synthetic session_start
    (ahead of the activity event) carrying the native id, transcript path, and
    cwd. The session_start machinery (row creation, native binding, AGENT_READY,
    context injection) then runs unchanged.
    """
    if not getattr(adapter, "synthesizes_session_start", False):
        return
    if event_type == AgentHookEvents.AGENT_SESSION_START or not raw_native_session_id:
        return
    # Already bound to a session row → a session_start has already been seeded.
    if _find_session_id_by_native(raw_native_session_id) is not None:
        return

    synthetic: JsonDict = {
        "session_id": raw_native_session_id,
        "native_session_id": raw_native_session_id,
        "agent_name": context.agent,
        "received_at": datetime.now(UTC).isoformat(),
        "synthetic_session_start": True,
    }
    if raw_native_log_file:
        synthetic["transcript_path"] = raw_native_log_file
        synthetic["native_log_file"] = raw_native_log_file
    if cwd:
        synthetic["cwd"] = cwd

    logger.debug(
        "Synthesizing session_start from first activity",
        agent=context.agent,
        session_id=session_id,
        native_session_id=raw_native_session_id,
        trigger_event=event_type,
    )
    enqueue_hook_event(
        session_id,
        AgentHookEvents.AGENT_SESSION_START,
        synthetic,
        outbox_db=context.outbox_db,
    )


def _maybe_emit_additional_context(
    *,
    raw_event_type: str,
    event_type: str,
    cwd: str | None,
    adapter: object,
    session_id: str,
) -> None:
    """Emit stdout additional context for context-injection hook events.

    This lane is distinct from checkpoint blocking on Stop.
    """
    if event_type != AgentHookEvents.AGENT_SESSION_START:
        return
    if cwd:
        project_name = Path(cwd).name
        logger.debug("Emitting additional context for session_start", project=project_name)
        _print_additional_context(raw_event_type, cwd, adapter, session_id=session_id)
        return
    logger.error("Skipping additional context: no CWD provided (contract violation)")


def _maybe_emit_checkpoint_response(
    *,
    event_type: str,
    adapter: object,
    session_id: str,
    raw_data: JsonDict,
    context: _ReceiverOutboxContext,
) -> None:
    if event_type != AgentHookEvents.AGENT_STOP or not adapter.supports_hook_checkpoint:  # type: ignore[union-attr]
        return
    checkpoint_reason: str | None = None
    try:
        checkpoint_reason = _maybe_checkpoint_output(session_id, context.agent, raw_data, outbox_db=context.outbox_db)
    except (AttributeError, TypeError, ValueError, SQLAlchemyError) as exc:
        logger.warning(
            "Checkpoint eval crashed (ignored)",
            event_type=event_type,
            session_id=session_id,
            agent=context.agent,
            error=str(exc),
        )
    if not checkpoint_reason:
        return
    checkpoint_json = adapter.format_checkpoint_response(checkpoint_reason)  # type: ignore[union-attr]
    if checkpoint_json:
        print(checkpoint_json)
        sys.exit(0)


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

    event_type = _map_hook_event_type(args.agent, raw_event_type)
    outbox_context = _ReceiverOutboxContext(agent=args.agent, event_type=event_type, outbox_db=_get_default_outbox_db())

    if event_type not in _HANDLED_EVENTS:
        logger.debug(
            "Dropped unhandled hook event", event_type=event_type, raw_event_type=raw_event_type, agent=args.agent
        )
        sys.exit(0)

    data = adapter.normalize_payload(dict(raw_data))  # type: ignore[union-attr]
    raw_native_session_id, raw_native_log_file = _extract_native_hook_fields(data)

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
        sys.exit(0)

    teleclaude_session_id = _resolve_receiver_session_id(
        args.agent,
        event_type,
        raw_event_type,
        raw_native_session_id,
        adapter,
    )
    if not teleclaude_session_id:
        sys.exit(0)

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
    )

    # Preserve native_session_id if present (needed for later tooling lookups)
    if raw_native_session_id:
        data["native_session_id"] = raw_native_session_id
    if raw_native_log_file:
        data["native_log_file"] = raw_native_log_file

    _maybe_synthesize_session_start(
        adapter=adapter,
        event_type=event_type,
        session_id=teleclaude_session_id,
        raw_native_session_id=raw_native_session_id,
        raw_native_log_file=raw_native_log_file,
        cwd=getattr(args, "cwd", None),
        context=outbox_context,
    )

    if raw_native_session_id or raw_native_log_file:
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
    ):
        return

    _maybe_emit_additional_context(
        raw_event_type=raw_event_type,
        event_type=event_type,
        cwd=args.cwd,
        adapter=adapter,
        session_id=teleclaude_session_id,
    )
    _maybe_emit_checkpoint_response(
        event_type=event_type,
        adapter=adapter,
        session_id=teleclaude_session_id,
        raw_data=raw_data,
        context=outbox_context,
    )

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


_RECEIVER_EXPORT_BINDINGS = (_read_stdin, _render_person_header)
