"""Polling coordinator for tmux activity detection and transcript-driven fanout.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and central transcript-driven delivery.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import codex_prompt_submit, session_cleanup, tmux_bridge
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentOutputPayload,
    AgentSessionStartPayload,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import (
    OutputChanged,
    OutputPoller,
    ProcessExited,
)
from teleclaude.core.summarizer import generate_session_title
from teleclaude.core.tool_activity import truncate_tool_preview
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    extract_last_turn_boundary_timestamp,
    extract_last_user_message_with_timestamp,
    extract_recent_transcript_turns,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)
OUTPUT_METRICS_SUMMARY_INTERVAL_S = 30.0


@dataclass
class CodexTurnState:
    """Per-session state for synthetic codex turn/tool events."""

    turn_active: bool = False
    in_tool: bool = False
    prompt_visible_last: bool = False
    initialized: bool = False
    last_tool_signature: str = ""


_codex_turn_state: dict[str, CodexTurnState] = {}


@dataclass
class OutputMetricsState:
    """Aggregated output metrics for cadence/fanout observability."""

    ticks: int = 0
    fanout_chars: int = 0
    last_tick_at: float | None = None
    cadence_samples_s: list[float] = field(default_factory=list)
    last_summary_at: float = 0.0


_output_metrics_state: dict[str, OutputMetricsState] = {}
_title_projection_signatures: dict[str, tuple[tuple[str, str], ...]] = {}


def _percentile(values: list[float], pct: float) -> float | None:
    """Return a percentile from sorted or unsorted numeric samples."""
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * pct)
    index = max(0, min(index, len(ordered) - 1))
    return ordered[index]


def _build_transcript_output_update(session: "Session") -> tuple[str, datetime, bool] | None:
    """Render transcript-backed output for one session turn.

    Uses the start-of-turn anchor (last genuine user message timestamp) as the
    cursor, so every render produces the full cumulative view of the current
    turn. Edit-based platforms (Discord, Telegram) replace the tracking message
    with the accumulating view; append-based chunking (char_offset) is handled
    downstream by the adapter.
    """
    transcript_path = session.native_log_file
    active_agent = session.active_agent
    if not transcript_path or not active_agent:
        return None

    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        logger.warning("Invalid active_agent %r for transcript output", active_agent)
        return None

    turn_cursor = extract_last_turn_boundary_timestamp(transcript_path, agent_name)
    assistant_messages = get_assistant_messages_since(transcript_path, agent_name, since_timestamp=turn_cursor)
    if not assistant_messages:
        return None

    renderable_block_count = count_renderable_assistant_blocks(
        transcript_path,
        agent_name,
        since_timestamp=turn_cursor,
        include_tools=True,
        include_tool_results=False,
    )
    is_multi = renderable_block_count > 1

    if is_multi:
        message, last_ts = render_agent_output(
            transcript_path,
            agent_name,
            include_tools=True,
            include_tool_results=False,
            since_timestamp=turn_cursor,
            include_timestamps=False,
        )
    else:
        message, last_ts = render_clean_agent_output(
            transcript_path,
            agent_name,
            since_timestamp=turn_cursor,
        )

    if not message or not isinstance(last_ts, datetime):
        return None
    return message, last_ts, is_multi


def _log_output_metrics_summary(session_id: str, state: OutputMetricsState, *, reason: str) -> None:
    if state.ticks <= 0:
        return

    avg_cadence = sum(state.cadence_samples_s) / len(state.cadence_samples_s) if state.cadence_samples_s else None
    p95_cadence = _percentile(state.cadence_samples_s, 0.95)
    logger.info(
        "Output cadence summary",
        session_id=session_id,
        reason=reason,
        tick_count=state.ticks,
        fanout_chars=state.fanout_chars,
        avg_cadence_s=round(avg_cadence, 3) if avg_cadence is not None else None,
        p95_cadence_s=round(p95_cadence, 3) if p95_cadence is not None else None,
    )


def _record_output_tick(session_id: str, output_len: int) -> None:
    """Record output cadence/fanout metrics with periodic summaries."""
    now = time.time()
    state = _output_metrics_state.get(session_id)
    if state is None:
        state = OutputMetricsState(last_summary_at=now)
        _output_metrics_state[session_id] = state

    if state.last_tick_at is not None:
        state.cadence_samples_s.append(max(0.0, now - state.last_tick_at))
    state.last_tick_at = now
    state.ticks += 1
    state.fanout_chars += max(0, output_len)

    if now - state.last_summary_at >= OUTPUT_METRICS_SUMMARY_INTERVAL_S:
        _log_output_metrics_summary(session_id, state, reason="periodic")
        state.ticks = 0
        state.fanout_chars = 0
        state.cadence_samples_s.clear()
        state.last_summary_at = now


def _clear_output_metrics(session_id: str) -> None:
    """Drop per-session output metrics state, logging trailing samples once."""
    state = _output_metrics_state.pop(session_id, None)
    if state:
        _log_output_metrics_summary(session_id, state, reason="final")
    _title_projection_signatures.pop(session_id, None)


def _mark_codex_turn_started(session_id: str) -> None:
    """Mark a Codex turn as active when user submit is inferred."""
    state = _codex_turn_state.get(session_id)
    if state is None:
        state = CodexTurnState()
        _codex_turn_state[session_id] = state
    state.turn_active = True


seed_codex_prompt_from_message = codex_prompt_submit.seed_codex_prompt_from_message
CodexInputState = codex_prompt_submit.CodexInputState
_codex_input_state = codex_prompt_submit._codex_input_state  # pylint: disable=protected-access
_find_prompt_input = codex_prompt_submit._find_prompt_input  # pylint: disable=protected-access
_has_agent_marker = codex_prompt_submit._has_agent_marker  # pylint: disable=protected-access
_has_live_prompt_marker = codex_prompt_submit._has_live_prompt_marker  # pylint: disable=protected-access
_is_live_agent_marker_line = codex_prompt_submit._is_live_agent_marker_line  # pylint: disable=protected-access
_is_suggestion_styled = codex_prompt_submit._is_suggestion_styled  # pylint: disable=protected-access
_strip_suggestion_segments = codex_prompt_submit._strip_suggestion_segments  # pylint: disable=protected-access


async def _emit_synthetic_codex_event(  # pylint: disable=too-many-arguments
    session_id: str,
    event_type: str,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
    *,
    tool_name: str | None = None,
    tool_preview: str | None = None,
    text: str | None = None,
) -> None:
    """Emit a synthetic Codex event through the regular agent event handler."""
    raw = {
        "synthetic": True,
        "source": "codex_output_effects",
    }
    if tool_name:
        raw["tool_name"] = tool_name
    if tool_preview:
        raw["tool_preview"] = truncate_tool_preview(tool_preview)
    if text:
        raw["text"] = text

    if event_type in (AgentHookEvents.TOOL_USE, AgentHookEvents.TOOL_DONE):
        payload = AgentOutputPayload(raw=raw)
    else:
        return

    await emit_agent_event(
        AgentEventContext(
            session_id=session_id,
            event_type=event_type,  # type: ignore[arg-type]
            data=payload,
        )
    )


async def _maybe_emit_codex_turn_events(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    session_id: str,
    active_agent: str | None,
    current_output: str,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
    *,
    enable_synthetic_turn_events: bool,
) -> None:
    """Infer synthetic tool events from visible Codex terminal effects."""
    if active_agent != "codex" or not enable_synthetic_turn_events:
        return

    state = _codex_turn_state.get(session_id)
    if state is None:
        state = CodexTurnState()
        _codex_turn_state[session_id] = state

    prompt_visible = codex_prompt_submit._has_live_prompt_marker(current_output)  # pylint: disable=protected-access
    responding = codex_prompt_submit._is_live_agent_responding(current_output)  # pylint: disable=protected-access
    tool_match = codex_prompt_submit._find_recent_tool_action(current_output)  # pylint: disable=protected-access
    raw_tool_action = tool_match[0] if tool_match else None
    raw_tool_signature = tool_match[1] if tool_match else ""
    raw_tool_preview = tool_match[2] if tool_match else ""
    if not state.initialized:
        state.initialized = True
        state.prompt_visible_last = prompt_visible
        if prompt_visible and raw_tool_signature:
            # Baseline stale scrollback on first sight to avoid startup false positives.
            state.last_tool_signature = raw_tool_signature

    is_new_tool_signature = bool(raw_tool_signature and raw_tool_signature != state.last_tool_signature)
    # Prompt-visible snapshots are common; ignore known stale signatures but allow new ones.
    if prompt_visible and not is_new_tool_signature:
        tool_action = None
    else:
        tool_action = raw_tool_action

    # Track tool lane transitions while prompt is not visible.
    if tool_action:
        if is_new_tool_signature:
            state.last_tool_signature = raw_tool_signature
        state.turn_active = True
        if not state.in_tool:
            await _emit_synthetic_codex_event(
                session_id,
                AgentHookEvents.TOOL_USE,
                emit_agent_event,
                tool_name=tool_action,
                tool_preview=raw_tool_preview,
            )
            state.in_tool = True
    elif state.in_tool:
        await _emit_synthetic_codex_event(
            session_id,
            AgentHookEvents.TOOL_DONE,
            emit_agent_event,
        )
        state.in_tool = False

    # Any live spinner/status marker means turn is still active.
    if responding:
        state.turn_active = True
        state.prompt_visible_last = False
        return

    # Prompt visible + not responding => authoritative tool-lane end.
    # Do NOT emit synthetic agent_stop; Codex stop is hook-authoritative.
    if prompt_visible:
        should_finalize_tool_lane = (
            state.turn_active or state.in_tool or ((not state.prompt_visible_last) and raw_tool_action is not None)
        )
        if should_finalize_tool_lane:
            if state.in_tool:
                await _emit_synthetic_codex_event(
                    session_id,
                    AgentHookEvents.TOOL_DONE,
                    emit_agent_event,
                )
        state.turn_active = False
        state.in_tool = False
        state.prompt_visible_last = True
        return

    state.prompt_visible_last = False
    if tool_action:
        state.turn_active = True
        return


async def _maybe_emit_codex_input(
    session_id: str,
    active_agent: str | None,
    current_output: str,
    output_changed: bool,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
) -> None:
    """Thin integration wrapper around the Codex synthetic-submit module."""
    await codex_prompt_submit.maybe_emit_codex_input(
        session_id=session_id,
        active_agent=active_agent,
        current_output=current_output,
        output_changed=output_changed,
        emit_agent_event=emit_agent_event,
        on_submit_emitted=_mark_codex_turn_started,
    )


_codex_session_start_emitted: set[str] = set()
_codex_transcript_bind_attempted: set[str] = set()


def _cleanup_codex_input_state(session_id: str) -> None:
    """Clean up Codex input tracking state when session ends."""
    codex_prompt_submit.cleanup_codex_prompt_state(session_id)
    _codex_turn_state.pop(session_id, None)
    _codex_session_start_emitted.discard(session_id)
    _codex_transcript_bind_attempted.discard(session_id)


async def _emit_codex_session_start(
    session: "Session",
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
) -> None:
    """Emit synthetic session_start for Codex, enriched with transcript if available."""
    if not session.active_agent or session.active_agent.lower() != AgentName.CODEX.value:
        return
    if session.session_id in _codex_session_start_emitted:
        return

    native_session_id = (session.native_session_id or "").strip() or None
    transcript_path = (session.native_log_file or "").strip() or None

    if native_session_id and not transcript_path:
        transcript_path = discover_codex_transcript_path(native_session_id)

    raw = {
        "synthetic": True,
        "source": "codex_native_discovery",
        "session_id": native_session_id or "",
        "transcript_path": transcript_path or "",
    }

    await emit_agent_event(
        AgentEventContext(
            session_id=session.session_id,
            event_type=AgentHookEvents.AGENT_SESSION_START,
            data=AgentSessionStartPayload(
                session_id=native_session_id or "",
                transcript_path=transcript_path,
                raw=raw,
            ),
        )
    )
    _codex_session_start_emitted.add(session.session_id)
    logger.debug(
        "Emitted synthetic Codex session_start",
        session_id=session.session_id,
        native_session_id=native_session_id,
        transcript_path=transcript_path,
    )


async def _try_bind_codex_transcript(session: "Session") -> bool:
    """One-shot opportunistic transcript binding for Codex sessions.

    Returns True when the DB was updated with a discovered transcript path.
    """
    if not session.active_agent or session.active_agent.lower() != AgentName.CODEX.value:
        return False
    if session.session_id in _codex_transcript_bind_attempted:
        return False
    native_session_id = (session.native_session_id or "").strip()
    if not native_session_id:
        return False
    if (session.native_log_file or "").strip():
        return False

    transcript_path = discover_codex_transcript_path(native_session_id)
    if not transcript_path:
        # Not found — mark attempted so we don't rescan the filesystem every tick.
        _codex_transcript_bind_attempted.add(session.session_id)
        return False
    await db.update_session(session.session_id, native_log_file=transcript_path)
    _codex_transcript_bind_attempted.add(session.session_id)
    return True


_active_pollers: set[str] = set()
_poller_lock = asyncio.Lock()
_active_headless_projections: set[str] = set()
_headless_projection_lock = asyncio.Lock()


def _handle_background_poller_result(task: asyncio.Task[None], session_id: str) -> None:
    """Consume background poller task exceptions to avoid unretrieved-task noise."""
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:  # pylint: disable=broad-exception-caught
        logger.error("Background poller task crashed for session %s", session_id, exc_info=True)


async def is_polling(session_id: str) -> bool:
    """Check if a poller task is active for the session (in-memory only)."""
    async with _poller_lock:
        return session_id in _active_pollers


async def _register_polling(session_id: str) -> bool:
    """Register a poller task if one isn't active. Returns True if registered."""
    async with _poller_lock:
        if session_id in _active_pollers:
            return False
        _active_pollers.add(session_id)
        return True


async def _unregister_polling(session_id: str) -> None:
    """Unregister a poller task."""
    async with _poller_lock:
        _active_pollers.discard(session_id)


async def _register_headless_projection(session_id: str) -> bool:
    """Register a headless projection task if one isn't active."""
    async with _headless_projection_lock:
        if session_id in _active_headless_projections:
            return False
        _active_headless_projections.add(session_id)
        return True


async def _unregister_headless_projection(session_id: str) -> None:
    """Unregister a headless projection task."""
    async with _headless_projection_lock:
        _active_headless_projections.discard(session_id)


async def _project_user_reflection(
    session: "Session",
    adapter_client: "AdapterClient",
) -> "Session":
    """Project the latest authoritative user message from transcript into canonical state."""
    # pylint: disable=too-many-locals
    transcript_path = session.native_log_file
    active_agent = session.active_agent
    if not transcript_path or not active_agent:
        return session

    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        return session

    extracted = await asyncio.to_thread(extract_last_user_message_with_timestamp, transcript_path, agent_name)
    if not extracted:
        return session

    user_text, transcript_ts = extracted
    if not user_text.strip():
        return session

    transcript_iso = transcript_ts.astimezone(UTC).isoformat() if isinstance(transcript_ts, datetime) else None
    current_iso = (
        session.last_message_sent_at.astimezone(UTC).isoformat()
        if isinstance(session.last_message_sent_at, datetime)
        else None
    )
    changed = transcript_iso != current_iso
    if not changed:
        return session

    source = (session.last_input_origin or "").strip() or InputOrigin.TERMINAL.value
    # Transcript projection is canonical for prompt persistence, but Discord
    # reflection is only valid for human-origin sessions. System-role sessions
    # (for example integrator/finalizer) can legitimately have no human identity.
    if source != InputOrigin.DISCORD.value and not session.system_role:
        await adapter_client.broadcast_user_input(session, user_text, source)

    if transcript_iso:
        await db.update_session(
            session.session_id,
            last_message_sent=user_text[:200],
            last_message_sent_at=transcript_iso,
        )
    else:
        await db.update_session(
            session.session_id,
            last_message_sent=user_text[:200],
        )
    refreshed = await db.get_session(session.session_id)
    return refreshed or session


async def refresh_session_title_from_transcript(session: "Session") -> "Session":
    """Recompute semantic title from transcript truth when the recent turn set changes."""
    # pylint: disable=too-many-return-statements
    current_title = (session.title or "").strip()
    if current_title.startswith("/"):
        return session

    transcript_path = session.native_log_file
    active_agent = session.active_agent
    if not transcript_path or not active_agent:
        return session

    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        return session

    recent_turns = await asyncio.to_thread(
        extract_recent_transcript_turns, transcript_path, agent_name, max_turns_per_role=3
    )
    if not recent_turns:
        return session
    turn_signature = tuple((role, text) for role, text in recent_turns)
    if _title_projection_signatures.get(session.session_id) == turn_signature:
        return session

    try:
        new_title = await generate_session_title(recent_turns)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Title summarization failed: %s", exc)
        return session

    _title_projection_signatures[session.session_id] = turn_signature
    if not new_title or new_title == current_title:
        return session

    await db.update_session(session.session_id, title=new_title)
    logger.info("Updated session title from transcript: %s", new_title)
    refreshed = await db.get_session(session.session_id)
    return refreshed or session


async def project_session_from_transcript(
    session: "Session",
    adapter_client: "AdapterClient",
    *,
    started_at: float = 0.0,
    last_changed_at: float | None = None,
) -> "Session":
    """Project transcript truth into canonical session state and outbound delivery."""
    session = await _project_user_reflection(session, adapter_client)

    transcript_update = await asyncio.to_thread(_build_transcript_output_update, session)
    if transcript_update is not None:
        message, last_ts, is_multi = transcript_update
        changed_at = last_changed_at if last_changed_at is not None else last_ts.timestamp()
        await adapter_client.send_output_update(
            session,
            message,
            started_at,
            changed_at,
            multi_message=is_multi,
            delivery_ts=last_ts,
        )
        _record_output_tick(session.session_id, len(message))
    return session


async def schedule_headless_projection(session_id: str, adapter_client: "AdapterClient") -> bool:
    """Schedule one transcript projection pass for a headless session."""
    if not await _register_headless_projection(session_id):
        return False

    async def _run() -> None:
        try:
            session = await db.get_session(session_id)
            if not session or session.lifecycle_status != "headless":
                return
            await project_session_from_transcript(session, adapter_client)
        finally:
            await _unregister_headless_projection(session_id)

    task = asyncio.create_task(_run(), name=f"project-headless-{session_id}")
    task.add_done_callback(lambda t, sid=session_id: _handle_background_poller_result(t, sid))  # type: ignore[misc]
    return True


async def schedule_polling(
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
) -> bool:
    """Schedule polling in the background with an in-memory guard.

    Returns True if scheduled, False if a poller is already active.
    """
    if not await _register_polling(session_id):
        logger.warning(
            "Polling already active for session %s, ignoring duplicate request",
            session_id,
        )
        return False

    task = asyncio.create_task(
        poll_and_send_output(
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            output_poller=output_poller,
            adapter_client=adapter_client,
            _skip_register=True,
        ),
        name=f"poll-output-{session_id}",
    )
    task.add_done_callback(lambda t, sid=session_id: _handle_background_poller_result(t, sid))  # type: ignore[misc]
    return True


async def poll_and_send_output(  # pylint: disable=too-many-arguments,too-many-branches,too-many-locals,too-many-positional-arguments,too-many-statements
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    _skip_register: bool = False,
) -> None:
    """Poll tmux activity and push transcript-derived output for a session.

    Tmux is a liveness and visible-activity signal only. Durable payloads come
    from the native transcript, except for Codex synthetic events derived from
    terminal effects.

    Args:
        session_id: Session ID
        tmux_session_name: tmux session name
        output_poller: Output poller instance
        adapter_client: AdapterClient instance
    """
    if not _skip_register:
        if not await _register_polling(session_id):
            logger.warning(
                "Polling already active for session %s, ignoring duplicate request",
                session_id,
            )
            return

    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name):
            if isinstance(event, OutputChanged):
                logger.debug(
                    "[COORDINATOR %s] Received OutputChanged event from poller",
                    session_id,
                )
                # Output is a rendered TUI snapshot (poller reads from raw stream)
                clean_output = event.output

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)
                if not session:
                    logger.debug(
                        "Session %s missing during polling output; stopping poller",
                        event.session_id,
                    )
                    return

                logger.trace(
                    "[COORDINATOR %s] Fetched session for output: digest=%s",
                    event.session_id,
                    session.last_output_digest,
                )

                # Detect user input for Codex sessions (no hook support).
                # Keep this inline to avoid spawning unbounded background tasks
                # on high-frequency output updates.
                emit_handler = adapter_client.agent_event_handler
                if emit_handler:
                    try:
                        # Codex synthetic tool events come from visible terminal effects
                        # regardless of native session bindings.
                        synth_turn_events_enabled = (session.active_agent or "").lower() == "codex"
                        await _maybe_emit_codex_turn_events(
                            session_id=event.session_id,
                            active_agent=session.active_agent,
                            current_output=clean_output,
                            emit_agent_event=emit_handler,
                            enable_synthetic_turn_events=synth_turn_events_enabled,
                        )
                        await _maybe_emit_codex_input(
                            session_id=event.session_id,
                            active_agent=session.active_agent,
                            current_output=clean_output,
                            output_changed=True,  # OutputChanged event means output changed
                            emit_agent_event=emit_handler,
                        )
                        await _emit_codex_session_start(session, emit_handler)
                        if await _try_bind_codex_transcript(session):
                            refreshed = await db.get_session(event.session_id)
                            if refreshed is not None:
                                session = refreshed
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error("[CODEX] Error in Codex event processing: %s", e, exc_info=True)

                await db.update_last_activity(event.session_id)
                await project_session_from_transcript(
                    session,
                    adapter_client,
                    started_at=event.started_at,
                    last_changed_at=event.last_changed_at,
                )

            elif isinstance(event, ProcessExited):
                # Fetch session once for all operations
                session = await db.get_session(event.session_id)
                if not session:
                    logger.debug(
                        "Session %s missing during process exit; stopping poller",
                        event.session_id,
                    )
                    return

                if event.exit_code is not None:
                    await db.update_last_activity(event.session_id)
                    tmux_alive = True
                    if session.tmux_session_name:
                        tmux_alive = await tmux_bridge.session_exists(
                            session.tmux_session_name,
                            log_missing=False,
                        )
                    if not tmux_alive:
                        await session_cleanup.terminate_session(
                            event.session_id,
                            adapter_client,
                            reason="tmux_exited",
                            session=session,
                            kill_tmux=False,
                        )
                        logger.info(
                            "Terminated session %s after tmux exit (exit code: %d)",
                            event.session_id,
                            event.exit_code,
                        )
                    else:
                        logger.info(
                            "Polling stopped for %s (exit code: %d), output file kept for downloads",
                            event.session_id,
                            event.exit_code,
                        )
                else:
                    # Tmux session disappeared without a clean process exit.
                    # Recovery is demand-driven; do not attempt background healing here.
                    logger.warning(
                        "Tmux session missing for %s; polling stopped without recovery",
                        event.session_id,
                    )
    except Exception as exc:
        logger.error("Polling failed for session %s: %s", session_id, exc)
        try:
            await adapter_client.send_error_feedback(
                session_id,
                f"Polling error: {exc}",
            )
        except Exception as feedback_exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed to send error feedback for session %s: %s",
                session_id,
                feedback_exc,
            )
        raise

    finally:
        # Cleanup state
        await _unregister_polling(session_id)
        _cleanup_codex_input_state(session_id)
        _clear_output_metrics(session_id)
        # NOTE: Don't clear pending_deletions here - let _pre_handle_user_input handle deletion on next input

        logger.debug("Polling ended for session %s", session_id)
