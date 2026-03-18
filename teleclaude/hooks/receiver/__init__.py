"""Unified hook receiver for agent CLIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import configure_logging, get_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session as SqlSession

from teleclaude.config import config
from teleclaude.config.schema import PersonEntry
from teleclaude.constants import UI_MESSAGE_MAX_CHARS, is_internal_user_text
from teleclaude.core import db_models
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.identity import derive_identity_key
from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.models import JsonDict, SessionAdapterMetadata
from teleclaude.hooks.adapters import get_adapter
from teleclaude.hooks.adapters._stdin import read_stdin_payload
from teleclaude.hooks.checkpoint import get_checkpoint_content
from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_RECHECK_FLAG,
    consume_checkpoint_flag,
    is_checkpoint_disabled,
    set_checkpoint_flag,
)
from teleclaude.hooks.receiver import _session as receiver_session
from teleclaude.hooks.receiver._session import (
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
)
from teleclaude.utils.transcript import extract_workdir_from_transcript

if TYPE_CHECKING:
    pass

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

# Only these events are forwarded to daemon processing. Others are dropped.
# This prevents noisy intermediate hook traffic from reaching command handlers.
# Only events with actual handlers in the daemon - infrastructure events are dropped.
_HANDLED_EVENTS: frozenset[AgentHookEventType] = AgentHookEvents.RECEIVER_HANDLED


@dataclass(frozen=True)
class _NativeMetadataChange:
    previous_native_session_id: str | None
    previous_native_log_file: str | None
    native_session_id: str | None
    native_log_file: str | None


def _as_utc(value: datetime | None) -> datetime | None:
    """Convert a datetime to timezone-aware UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _load_session_row(session_id: str) -> db_models.Session | None:
    """Load a session row synchronously for hook processing."""
    with SqlSession(_create_sync_engine()) as db_session:
        return db_session.get(db_models.Session, session_id)


def _resolve_checkpoint_project_path(row: db_models.Session) -> str:
    """Resolve project_path, falling back to transcript-derived workdir."""
    transcript_path = getattr(row, "native_log_file", None)
    project_path = str(getattr(row, "project_path", "") or "")
    if not project_path and transcript_path:
        project_path = extract_workdir_from_transcript(transcript_path) or ""
    return project_path


def _resolve_agent_enum(agent: str) -> AgentName:
    """Resolve a hook agent string to an AgentName with default fallback."""
    try:
        return AgentName.from_str(agent)
    except ValueError:
        return AgentName.from_str(get_default_agent())


def _mark_checkpoint_seen(session_id: str, now: datetime) -> None:
    """Persist the latest checkpoint timestamp for a session."""
    with SqlSession(_create_sync_engine()) as db_session:
        update_row = db_session.get(db_models.Session, session_id)
        if update_row:
            update_row.last_checkpoint_at = now
            db_session.add(update_row)
            db_session.commit()


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
    """Return identity-key and person header metadata for memory injection."""
    row = _load_session_row(session_id)
    if not row:
        return None, None
    identity_key: str | None = None
    if row.adapter_metadata:
        adapter_meta = SessionAdapterMetadata.from_json(row.adapter_metadata)
        identity_key = derive_identity_key(adapter_meta)
    human_email = getattr(row, "human_email", None)
    if not human_email:
        return identity_key, None
    people = getattr(config, "people", [])
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
    details: dict[str, object] | None = None,
) -> dict[str, object]:
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
    # Keep CLEAR persistent across turns; only reset one-shot recheck limiter.
    consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)


def _maybe_checkpoint_output(
    session_id: str,
    agent: str,
    raw_data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
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

    stop_hook_active = bool(raw_data.get("stop_hook_active"))
    if stop_hook_active and consume_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG):
        logger.info("Checkpoint skipped (recheck limit reached)", session_id=session_id, agent=agent)
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
        transcript_path=transcript_path,
        agent_name=_resolve_agent_enum(agent),
        project_path=project_path,
        working_slug=working_slug,
        elapsed_since_turn_start_s=elapsed,
    )
    if not checkpoint_reason:
        logger.debug(
            "Checkpoint skipped: no turn-local changes for session %s (transcript=%s)",
            session_id,
            transcript_path or "<none>",
        )
        return None

    # Claude stop_hook_active indicates we already blocked once for this turn.
    # If no explicit clear marker is provided, allow at most one extra recheck.
    if stop_hook_active:
        set_checkpoint_flag(session_id, CHECKPOINT_RECHECK_FLAG)

    try:
        _mark_checkpoint_seen(session_id, now)
    except SQLAlchemyError as exc:
        logger.warning("Checkpoint DB update failed: %s", exc)
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
    """Render human-readable person header with expertise or proficiency."""
    name = person.name
    expertise = person.expertise
    proficiency = person.proficiency

    if not expertise:
        if proficiency:
            return f"Human in the loop: {name} ({proficiency})"
        return f"Human in the loop: {name}"

    lines = [f"Human in the loop: {name}", "Expertise:"]
    for domain, value in expertise.items():
        if isinstance(value, str):
            lines.append(f"  {domain}: {value}")
        else:
            default = value.get("default")
            sub_areas = {k: v for k, v in value.items() if k != "default"}
            if default and sub_areas:
                sub_str = ", ".join(f"{k}: {v}" for k, v in sub_areas.items())
                lines.append(f"  {domain}: {default} ({sub_str})")
            elif default:
                lines.append(f"  {domain}: {default}")
            elif sub_areas:
                sub_str = ", ".join(f"{k}: {v}" for k, v in sub_areas.items())
                lines.append(f"  {domain}: ({sub_str})")
    return "\n".join(lines)


def _print_memory_injection(cwd: str | None, adapter: object, session_id: str | None = None) -> None:
    """Print memory context to stdout for agent context injection via SessionStart hook."""
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

    context = _get_memory_context(project_name, identity_key=identity_key)
    if not context and not person_header:
        return

    if person_header:
        context = f"{person_header}\n{context}" if context else person_header

    logger.debug("Memory context fetched", project=project_name, length=len(context), identity_key=identity_key or "")
    payload = adapter.format_memory_injection(context)  # type: ignore[union-attr]
    if payload:
        print(payload)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TeleClaude hook receiver")
    parser.add_argument(
        "--agent",
        required=True,
        choices=AgentName.choices(),
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


def _enqueue_hook_event(
    session_id: str,
    event_type: str,
    data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON.
) -> None:
    """Persist hook event to local outbox for durable delivery."""
    now = datetime.now(UTC).isoformat()
    payload_json = json.dumps(data)

    with SqlSession(_create_sync_engine()) as session:
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


def _append_transcript_history(row: db_models.Session, previous_native_log_file: str) -> None:
    """Append the replaced transcript path to transcript_files."""
    try:
        loaded_chain = json.loads(row.transcript_files or "[]")
    except (json.JSONDecodeError, TypeError):
        loaded_chain = []
    chain = loaded_chain if isinstance(loaded_chain, list) else []
    if previous_native_log_file not in chain:
        chain.append(previous_native_log_file)
    row.transcript_files = json.dumps(chain)


def _path_exists(path_value: str | None) -> bool:
    """Return whether a path exists without surfacing filesystem resolution errors."""
    if not path_value:
        return False
    try:
        return Path(path_value).expanduser().exists()
    except (OSError, RuntimeError, ValueError):
        return False


def _log_native_metadata_change(
    *,
    session_id: str,
    agent: str,
    event_type: str,
    change: _NativeMetadataChange,
) -> None:
    """Log native metadata changes after the session row has been updated."""
    session_changed = bool(change.native_session_id and change.previous_native_session_id != change.native_session_id)
    native_log_changed = bool(change.native_log_file and change.previous_native_log_file != change.native_log_file)
    if not session_changed and not native_log_changed:
        return

    logger.info(
        "Native session metadata changed",
        session_id=session_id,
        agent=agent,
        event_type=event_type,
        native_session_id_before=(change.previous_native_session_id or ""),
        native_session_id_after=(change.native_session_id or ""),
        native_session_changed=session_changed,
        native_log_file_before=change.previous_native_log_file or "",
        native_log_file_after=change.native_log_file or "",
        native_log_changed=native_log_changed,
        old_path_exists=_path_exists(change.previous_native_log_file),
        new_path_exists=_path_exists(change.native_log_file),
    )


def _update_session_native_fields(
    session_id: str,
    *,
    agent: str,
    event_type: str,
    native_log_file: str | None = None,
    native_session_id: str | None = None,
) -> None:
    """Update native session fields directly on the session row.

    When native_log_file changes and the previous value is non-empty,
    the old path is appended to transcript_files before replacing native_log_file.
    """
    if not native_log_file and not native_session_id:
        return

    with SqlSession(_create_sync_engine()) as session:
        row = session.get(db_models.Session, session_id)
        if not row:
            return
        previous_native_session_id = row.native_session_id
        previous_native_log_file = row.native_log_file

        # Chain accumulation: preserve old transcript path before replacing
        if (
            native_log_file and previous_native_log_file and previous_native_log_file != native_log_file
        ):
            _append_transcript_history(row, previous_native_log_file)

        if native_log_file:
            row.native_log_file = native_log_file
        if native_session_id:
            row.native_session_id = native_session_id
        session.add(row)
        session.commit()

    change = _NativeMetadataChange(
        previous_native_session_id=previous_native_session_id,
        previous_native_log_file=previous_native_log_file,
        native_session_id=native_session_id,
        native_log_file=native_log_file,
    )
    _log_native_metadata_change(
        session_id=session_id,
        agent=agent,
        event_type=event_type,
        change=change,
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
        _enqueue_hook_event(
            session_id,
            "error",
            _build_receiver_error_payload(
                message=message,
                code=code,
                agent=args.agent,
                event_type=getattr(args, "event_type", None),
                details=details,
            ),
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


def _persist_native_metadata(
    *,
    session_id: str,
    agent: str,
    event_type: str,
    raw_native_session_id: str | None,
    raw_native_log_file: str | None,
) -> None:
    if raw_native_session_id:
        _update_session_native_fields(
            session_id,
            agent=agent,
            event_type=event_type,
            native_log_file=raw_native_log_file,
            native_session_id=raw_native_session_id,
        )
        return
    if raw_native_log_file:
        _update_session_native_fields(
            session_id,
            agent=agent,
            event_type=event_type,
            native_log_file=raw_native_log_file,
        )


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
        logger.warning(
            "Dropped empty user_prompt_submit hook event",
            agent=agent,
            session_id=session_id,
            native_session_id=(raw_native_session_id or ""),
            hook_event_name=str(data.get("hook_event_name") or ""),
            raw_event_type=event_type,
        )
        return True
    if is_internal_user_text(prompt_text):
        logger.debug(
            "Dropped system-injected user_prompt_submit",
            agent=agent,
            session_id=session_id,
        )
        return True
    _reset_checkpoint_flags(session_id)
    return False


def _maybe_inject_memory_context(
    *,
    event_type: str,
    cwd: str | None,
    adapter: object,
    session_id: str,
) -> None:
    if event_type != AgentHookEvents.AGENT_SESSION_START:
        return
    if cwd:
        project_name = Path(cwd).name
        logger.debug("Injecting memory index for session_start", project=project_name)
        _print_memory_injection(cwd, adapter, session_id=session_id)
        return
    logger.error("Skipping memory injection: no CWD provided (contract violation)")


def _maybe_emit_checkpoint_response(
    *,
    event_type: str,
    adapter: object,
    session_id: str,
    agent: str,
    raw_data: JsonDict,
) -> None:
    if event_type != AgentHookEvents.AGENT_STOP or not adapter.supports_hook_checkpoint:  # type: ignore[union-attr]
        return
    checkpoint_reason: str | None = None
    try:
        checkpoint_reason = _maybe_checkpoint_output(session_id, agent, raw_data)
    except (AttributeError, TypeError, ValueError, SQLAlchemyError) as exc:
        logger.warning(
            "Checkpoint eval crashed (ignored)",
            event_type=event_type,
            session_id=session_id,
            agent=agent,
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

    logger.trace(
        "Hook receiver start",
        argv=sys.argv,
        cwd=os.getcwd(),
        stdin_tty=sys.stdin.isatty(),
        has_event_arg=bool(args.event_type),
        agent=args.agent,
    )

    adapter = get_adapter(args.agent)

    raw_input, raw_event_type, raw_data = _parse_receiver_input(args, adapter)

    # log_raw = os.getenv("TELECLAUDE_HOOK_LOG_RAW") == "1"
    log_raw = True
    _log_raw_input(raw_input, log_raw=log_raw)

    event_type = _map_hook_event_type(args.agent, raw_event_type)

    if event_type not in _HANDLED_EVENTS:
        logger.debug(
            "Dropped unhandled hook event", event_type=event_type, raw_event_type=raw_event_type, agent=args.agent
        )
        sys.exit(0)

    data = adapter.normalize_payload(dict(raw_data))  # type: ignore[union-attr]
    raw_native_session_id, raw_native_log_file = _extract_native_hook_fields(data)

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

    if raw_native_session_id or raw_native_log_file:
        try:
            _persist_native_metadata(
                session_id=teleclaude_session_id,
                agent=args.agent,
                event_type=event_type,
                raw_native_session_id=raw_native_session_id,
                raw_native_log_file=raw_native_log_file,
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

    _maybe_inject_memory_context(
        event_type=event_type,
        cwd=args.cwd,
        adapter=adapter,
        session_id=teleclaude_session_id,
    )
    _maybe_emit_checkpoint_response(
        event_type=event_type,
        adapter=adapter,
        session_id=teleclaude_session_id,
        agent=args.agent,
        raw_data=raw_data,
    )

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(UTC).isoformat()

    _enqueue_hook_event(teleclaude_session_id, event_type, data)


__all__ = [*receiver_session.__all__, "_read_stdin", "_render_person_header", "main"]
