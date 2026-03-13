"""Unified hook receiver for agent CLIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from teleclaude.config.schema import PersonEntry

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.config import config
from teleclaude.constants import UI_MESSAGE_MAX_CHARS, is_internal_user_text
from teleclaude.core import db_models
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.hooks.adapters import get_adapter
from teleclaude.hooks.checkpoint_flags import (
    CHECKPOINT_RECHECK_FLAG,
    consume_checkpoint_flag,
    is_checkpoint_disabled,
    set_checkpoint_flag,
)
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

configure_logging("teleclaude")
logger = get_logger("teleclaude.hooks.receiver")

# Only these events are forwarded to daemon processing. Others are dropped.
# This prevents noisy intermediate hook traffic from reaching command handlers.
# Only events with actual handlers in the daemon - infrastructure events are dropped.
_HANDLED_EVENTS: frozenset[AgentHookEventType] = AgentHookEvents.RECEIVER_HANDLED


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

    from sqlmodel import Session as SqlSession

    try:
        with SqlSession(_create_sync_engine()) as db_session:
            row = db_session.get(db_models.Session, session_id)
    except Exception as exc:
        logger.debug("Checkpoint eval skipped (db error)", error=str(exc))
        return None

    if not row:
        return None

    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    checkpoint_at = _as_utc(row.last_checkpoint_at)
    message_at = _as_utc(row.last_message_sent_at)
    now = datetime.now(UTC)

    # Turn start = most recent input event (real user message or previous checkpoint)
    turn_candidates = [dt for dt in (message_at, checkpoint_at) if dt is not None]
    turn_start = max(turn_candidates, default=None)
    if not turn_start:
        logger.debug("Checkpoint skipped (no turn start) for session %s", session_id)
        return None

    elapsed = (now - turn_start).total_seconds()

    # Capture session fields before the DB update re-fetches row
    transcript_path = getattr(row, "native_log_file", None)
    working_slug = getattr(row, "working_slug", None)

    logger.debug("Checkpoint eval for session %s (%.1fs elapsed)", session_id, elapsed)

    # Build context-aware checkpoint message from git diff + transcript
    from teleclaude.hooks.checkpoint import get_checkpoint_content

    # Prefer persisted session project_path (source of truth). Fall back to
    # transcript-derived workdir only when project_path is missing.
    project_path = str(getattr(row, "project_path", "") or "")
    if not project_path and transcript_path:
        from teleclaude.utils.transcript import extract_workdir_from_transcript

        project_path = extract_workdir_from_transcript(transcript_path) or ""
    try:
        agent_enum = AgentName.from_str(agent)
    except ValueError:
        agent_enum = AgentName.from_str(get_default_agent())
    checkpoint_reason = get_checkpoint_content(
        transcript_path=transcript_path,
        agent_name=agent_enum,
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

    # Checkpoint warranted — update DB and return agent-specific blocking JSON
    try:
        with SqlSession(_create_sync_engine()) as db_session:
            update_row = db_session.get(db_models.Session, session_id)
            if update_row:
                update_row.last_checkpoint_at = now
                db_session.add(update_row)
                db_session.commit()
    except Exception as exc:
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
        elif isinstance(value, dict):
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

    # Resolve identity_key from session adapter metadata for identity-scoped memories
    identity_key: str | None = None
    person_header: str | None = None
    if session_id:
        try:
            from sqlmodel import Session as SqlSession

            from teleclaude.core.identity import derive_identity_key
            from teleclaude.core.models import SessionAdapterMetadata

            with SqlSession(_create_sync_engine()) as db_session:
                row = db_session.get(db_models.Session, session_id)
                if row:
                    if row.adapter_metadata:
                        adapter_meta = SessionAdapterMetadata.from_json(row.adapter_metadata)
                        identity_key = derive_identity_key(adapter_meta)
                    human_email = getattr(row, "human_email", None)
                    if human_email:
                        person = next(
                            (p for p in config.people if p.email == human_email),
                            None,
                        )
                        if person:
                            person_header = _render_person_header(person)
        except Exception:
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
    raw_input = ""
    data: dict[str, object] = {}
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read()
        if raw_input.strip():
            parsed = json.loads(raw_input)
            if not isinstance(parsed, dict):
                raise ValueError("Hook stdin payload must be a JSON object")
            data = cast(dict[str, object], parsed)
    return raw_input, data


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
    from sqlmodel import Session as SqlSession

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
    from sqlmodel import Session as SqlSession

    with SqlSession(_create_sync_engine()) as session:
        row = session.get(db_models.Session, session_id)
        if not row:
            return
        previous_native_session_id = row.native_session_id
        previous_native_log_file = row.native_log_file

        # Chain accumulation: preserve old transcript path before replacing
        transcript_changed = bool(
            native_log_file and previous_native_log_file and previous_native_log_file != native_log_file
        )
        if transcript_changed:
            chain: list[str] = []
            try:
                chain = json.loads(row.transcript_files or "[]")
            except (json.JSONDecodeError, TypeError):
                chain = []
            if previous_native_log_file not in chain:
                chain.append(previous_native_log_file)
            row.transcript_files = json.dumps(chain)

        if native_log_file:
            row.native_log_file = native_log_file
        if native_session_id:
            row.native_session_id = native_session_id
        session.add(row)
        session.commit()

        session_changed = bool(native_session_id and previous_native_session_id != native_session_id)
        transcript_changed_log = bool(native_log_file and previous_native_log_file != native_log_file)
        if not session_changed and not transcript_changed_log:
            return

        old_path = Path(previous_native_log_file).expanduser() if previous_native_log_file else None
        new_path = Path(native_log_file).expanduser() if native_log_file else None
        old_exists = bool(old_path and old_path.exists())
        new_exists = bool(new_path and new_path.exists())

        logger.info(
            "Native session metadata changed",
            session_id=session_id,
            agent=agent,
            event_type=event_type,
            native_session_id_before=(previous_native_session_id or ""),
            native_session_id_after=(native_session_id or ""),
            native_session_changed=session_changed,
            native_log_file_before=previous_native_log_file or "",
            native_log_file_after=native_log_file or "",
            native_log_changed=transcript_changed_log,
            old_path_exists=old_exists,
            new_path_exists=new_exists,
        )


# guard: loose-dict-func - Main path processes raw hook payload boundaries.
def _emit_receiver_error_best_effort(
    *,
    agent: str,
    event_type: str | None,
    message: str,
    code: str,
    details: dict[str, object] | None = None,  # guard: loose-dict - Error details are context-specific.
    raw_data: dict[str, object] | None = None,  # guard: loose-dict - Raw hook payload for best-effort context.
) -> None:
    """Best-effort error emission for receiver contract violations."""
    payload = dict(details or {})
    payload.update(
        {
            "agent": agent,
            "event_type": event_type,
            "code": code,
        }
    )

    try:
        raw_native_session_id = None
        if raw_data is not None:
            # Try canonical name first, then Codex raw name as fallback
            raw_id = raw_data.get("session_id") or raw_data.get("thread-id")
            if isinstance(raw_id, str):
                raw_native_session_id = raw_id
        session_id = _get_cached_session_id(agent, raw_native_session_id)
        if not session_id:
            session_id = _find_session_id_by_native(raw_native_session_id)
        if not session_id:
            logger.error(
                "Receiver error with unknown session",
                agent=agent,
                event_type=event_type,
                code=code,
                message=message,
            )
            return
        _enqueue_hook_event(
            session_id,
            "error",
            {
                "message": message,
                "source": "hook_receiver",
                "code": code,
                "details": payload,
                "severity": "error",
                "retryable": False,
            },
        )
    except Exception as exc:
        logger.error("Receiver error reporting failed", error=str(exc), code=code)


# guard: loose-dict-func - Main path processes raw hook payload boundaries.
def main() -> None:
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

    # Parse input via adapter (agent-specific input format)
    try:
        raw_input, raw_event_type, raw_data = adapter.parse_input(args)
    except json.JSONDecodeError:
        _emit_receiver_error_best_effort(
            agent=args.agent,
            event_type=getattr(args, "event_type", None),
            message="Invalid hook payload JSON",
            code="HOOK_INVALID_JSON",
        )
        sys.exit(1)
    except ValueError as exc:
        _emit_receiver_error_best_effort(
            agent=args.agent,
            event_type=getattr(args, "event_type", None),
            message=str(exc),
            code="HOOK_PAYLOAD_NOT_OBJECT",
        )
        sys.exit(1)

    # log_raw = os.getenv("TELECLAUDE_HOOK_LOG_RAW") == "1"
    log_raw = True
    _log_raw_input(raw_input, log_raw=log_raw)

    # Map agent-specific event_type to TeleClaude internal event_type
    event_type = raw_event_type
    agent_map = AgentHookEvents.HOOK_EVENT_MAP.get(args.agent, {})

    # Contract boundary: event names are trusted; only exact mapping is allowed.
    mapped_event_type = agent_map.get(raw_event_type)

    # Use mapped event if found, otherwise keep original (for direct events like 'tool_done')
    if mapped_event_type:
        event_type = mapped_event_type
        logger.debug("Mapped hook event: %s -> %s", raw_event_type, event_type)

    # Event types outside the handled contract are ignored by design.
    if event_type not in _HANDLED_EVENTS:
        logger.debug(
            "Dropped unhandled hook event", event_type=event_type, raw_event_type=raw_event_type, agent=args.agent
        )
        sys.exit(0)

    headless_route = _is_headless_route()

    # Normalize payload: maps agent-specific field names to canonical internal names.
    # After this, all agents use: session_id, transcript_path, prompt, message.
    data = adapter.normalize_payload(dict(raw_data))

    # Extract native identity from normalized data (agent-agnostic)
    raw_native_session_id: str | None = None
    raw_id = data.get("session_id")
    if isinstance(raw_id, str):
        raw_native_session_id = raw_id

    raw_native_log_file: str | None = None
    raw_log = data.get("transcript_path")
    if isinstance(raw_log, str):
        raw_native_log_file = raw_log

    try:
        teleclaude_session_id, cached_session_id, existing_id = _resolve_hook_session_id(
            agent=args.agent,
            event_type=event_type,
            native_session_id=raw_native_session_id,
            headless=headless_route,
            mint_events=adapter.mint_events,
        )
    except ValueError as exc:
        logger.error(
            "Hook receiver contract violation",
            agent=args.agent,
            event_type=event_type,
            headless=headless_route,
            error=str(exc),
        )
        sys.exit(1)
    logger.debug(
        "Hook session resolution",
        agent=args.agent,
        headless=headless_route,
        event_type=event_type,
        cached_session_id=(cached_session_id or ""),
        existing_session_id=(existing_id or ""),
        resolved_session_id=(teleclaude_session_id or ""),
        native_session_id=(raw_native_session_id or ""),
    )
    if not teleclaude_session_id:
        logger.debug(
            "Hook session has no TeleClaude mapping, dropping event",
            agent=args.agent,
            headless=headless_route,
            event_type=event_type,
            raw_event_type=raw_event_type,
            native_session_id=(raw_native_session_id or ""),
            cached_session_id=(cached_session_id or ""),
            existing_session_id=(existing_id or ""),
        )
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
            _update_session_native_fields(
                teleclaude_session_id,
                agent=args.agent,
                event_type=event_type,
                native_log_file=raw_native_log_file,
                native_session_id=raw_native_session_id,
            )
        except Exception as exc:  # Best-effort update; never fail hook.
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

    # Guard: Some Gemini BeforeAgent hooks arrive with an empty prompt.
    # These are not real user turns and must not overwrite last_message_sent.
    if event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
        prompt_value = data.get("prompt")
        prompt_text = prompt_value if isinstance(prompt_value, str) else ""
        if not prompt_text.strip():
            logger.warning(
                "Dropped empty user_prompt_submit hook event",
                agent=args.agent,
                session_id=teleclaude_session_id,
                native_session_id=(raw_native_session_id or ""),
                hook_event_name=str(data.get("hook_event_name") or ""),
                raw_event_type=str(raw_event_type or ""),
            )
            return
        if is_internal_user_text(prompt_text):
            logger.debug(
                "Dropped system-injected user_prompt_submit",
                agent=args.agent,
                session_id=teleclaude_session_id,
            )
            return
        _reset_checkpoint_flags(teleclaude_session_id)

    # Inject memory index into STDOUT for SessionStart (Agent Context)
    if event_type == AgentHookEvents.AGENT_SESSION_START:
        cwd = args.cwd
        if cwd:
            project_name = Path(cwd).name
            logger.debug("Injecting memory index for session_start", project=project_name)
            _print_memory_injection(cwd, adapter, session_id=teleclaude_session_id)
        else:
            logger.error("Skipping memory injection: no CWD provided (contract violation)")

    # Hook-based checkpoint: skip for agents that don't support hook blocking.
    # If checkpoint fires: print blocking JSON, exit 0, skip enqueue (agent continues).
    # If no checkpoint: fall through to enqueue (real stop enters the system).
    if event_type == AgentHookEvents.AGENT_STOP and adapter.supports_hook_checkpoint:
        checkpoint_reason: str | None = None
        try:
            checkpoint_reason = _maybe_checkpoint_output(teleclaude_session_id, args.agent, raw_data)
        except Exception as exc:
            logger.warning(
                "Checkpoint eval crashed (ignored)",
                event_type=event_type,
                session_id=teleclaude_session_id,
                agent=args.agent,
                error=str(exc),
            )
        if checkpoint_reason:
            checkpoint_json = adapter.format_checkpoint_response(checkpoint_reason)
            if checkpoint_json:
                print(checkpoint_json)
                sys.exit(0)

    data["agent_name"] = args.agent
    data["received_at"] = datetime.now(UTC).isoformat()

    _enqueue_hook_event(teleclaude_session_id, event_type, data)


__all__ = [
    # Re-exported from _session
    "_create_sync_engine",
    "_find_session_id_by_native",
    "_get_cached_session_id",
    "_get_memory_context",
    "_get_session_map_path",
    "_get_tmux_contract_session_id",
    "_get_tmux_contract_tmpdir",
    "_is_headless_route",
    "_is_tmux_contract_session_compatible",
    "_load_session_map",
    "_persist_session_map",
    "_read_stdin",
    "_render_person_header",
    "_resolve_hook_session_id",
    "_resolve_or_refresh_session_id",
    "_session_map_key",
    "_write_session_map_atomic",
    # Public API
    "main",
]
