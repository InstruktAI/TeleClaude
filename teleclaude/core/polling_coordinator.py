"""Polling coordinator for tmux output streaming.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and event routing to message manager.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import codex_prompt_submit, session_cleanup, tmux_bridge
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentOutputPayload,
)
from teleclaude.core.output_poller import (
    DirectoryChanged,
    OutputChanged,
    OutputPoller,
    ProcessExited,
)
from teleclaude.core.session_utils import split_project_path_and_subdir
from teleclaude.core.tool_activity import truncate_tool_preview

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

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


def _percentile(values: list[float], pct: float) -> float | None:
    """Return a percentile from sorted or unsorted numeric samples."""
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * pct)
    index = max(0, min(index, len(ordered) - 1))
    return ordered[index]


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


def _mark_codex_turn_started(session_id: str) -> None:
    """Mark a Codex turn as active when user submit is inferred."""
    state = _codex_turn_state.get(session_id)
    if state is None:
        state = CodexTurnState()
        _codex_turn_state[session_id] = state
    state.turn_active = True


seed_codex_prompt_from_message = codex_prompt_submit.seed_codex_prompt_from_message
CodexInputState = codex_prompt_submit.CodexInputState
_codex_input_state = codex_prompt_submit._codex_input_state
_find_prompt_input = codex_prompt_submit._find_prompt_input
_has_agent_marker = codex_prompt_submit._has_agent_marker
_has_live_prompt_marker = codex_prompt_submit._has_live_prompt_marker
_is_live_agent_marker_line = codex_prompt_submit._is_live_agent_marker_line
_is_suggestion_styled = codex_prompt_submit._is_suggestion_styled
_strip_suggestion_segments = codex_prompt_submit._strip_suggestion_segments


async def _emit_synthetic_codex_event(
    session_id: str,
    event_type: str,
    emit_agent_event: Callable[[AgentEventContext], Awaitable[None]],
    *,
    tool_name: str | None = None,
    tool_preview: str | None = None,
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

    if event_type == AgentHookEvents.TOOL_USE:
        payload = AgentOutputPayload(raw=raw)
    elif event_type == AgentHookEvents.TOOL_DONE:
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


async def _maybe_emit_codex_turn_events(
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

    prompt_visible = codex_prompt_submit._has_live_prompt_marker(current_output)
    responding = codex_prompt_submit._is_live_agent_responding(current_output)
    tool_match = codex_prompt_submit._find_recent_tool_action(current_output)
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


def _cleanup_codex_input_state(session_id: str) -> None:
    """Clean up Codex input tracking state when session ends."""
    codex_prompt_submit.cleanup_codex_prompt_state(session_id)
    _codex_turn_state.pop(session_id, None)


_active_pollers: set[str] = set()
_poller_lock = asyncio.Lock()


def _handle_background_poller_result(task: asyncio.Task[None], session_id: str) -> None:
    """Consume background poller task exceptions to avoid unretrieved-task noise."""
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
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


async def schedule_polling(
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
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
            get_output_file=get_output_file,
            _skip_register=True,
        )
    )
    task.add_done_callback(lambda t, sid=session_id: _handle_background_poller_result(t, sid))  # type: ignore[misc]
    return True


async def poll_and_send_output(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    get_output_file: Callable[[str], Path],
    _skip_register: bool = False,
) -> None:
    """Poll tmux output and send to all adapters for session.

    Pure orchestration - consumes events from poller, delegates to message manager.
    SINGLE RESPONSIBILITY: Owns the polling lifecycle for a session.

    Args:
        session_id: Session ID
        tmux_session_name: tmux session name
        output_poller: Output poller instance
        adapter_client: AdapterClient instance (broadcasts to all adapters)
        get_output_file: Function to get output file path for session
    """
    if not _skip_register:
        if not await _register_polling(session_id):
            logger.warning(
                "Polling already active for session %s, ignoring duplicate request",
                session_id,
            )
            return

    # Get output file
    output_file = get_output_file(session_id)
    try:
        # Consume events from pure poller
        async for event in output_poller.poll(session_id, tmux_session_name, output_file):
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
                    except Exception as e:
                        logger.error("[CODEX] Error in input detection: %s", e, exc_info=True)

                # Route through shared terminal_live projection before adapter push.
                # The projection is a thin wrapper; adapter contract is unchanged.
                from teleclaude.output_projection.terminal_live_projector import project_terminal_live

                terminal_projection = project_terminal_live(clean_output)

                # Unified output handling - ALL sessions use send_output_update
                start_time = time.time()
                logger.debug("[COORDINATOR %s] Calling send_output_update...", session_id)
                await adapter_client.send_output_update(
                    session,
                    terminal_projection.output,
                    event.started_at,
                    event.last_changed_at,
                )
                coordinator = getattr(adapter_client, "agent_coordinator", None)
                if coordinator:
                    try:
                        await coordinator.trigger_incremental_output(event.session_id)
                    except Exception:
                        logger.warning(
                            "Poller-triggered incremental output failed for %s",
                            event.session_id,
                            exc_info=True,
                        )
                _record_output_tick(event.session_id, len(clean_output))
                elapsed = time.time() - start_time
                logger.debug(
                    "[COORDINATOR %s] send_output_update completed in %.2fs",
                    session_id,
                    elapsed,
                )

            elif isinstance(event, DirectoryChanged):
                # Directory changed - update session (db dispatcher handles title update)
                trusted_dirs = [d.path for d in config.computer.get_all_trusted_dirs()]
                project_path, subdir = split_project_path_and_subdir(event.new_path, trusted_dirs)
                await db.update_session(event.session_id, project_path=project_path, subdir=subdir)

            elif isinstance(event, ProcessExited):
                # Process exited - output is already clean from file
                clean_final_output = event.final_output

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)
                if not session:
                    logger.debug(
                        "Session %s missing during process exit; stopping poller",
                        event.session_id,
                    )
                    return

                # Unified output handling - ALL sessions use send_output_update
                if event.exit_code is not None:
                    # Exit with code - send final message via AdapterClient
                    await adapter_client.send_output_update(
                        session,
                        clean_final_output,
                        event.started_at,  # Use actual start time from poller
                        time.time(),
                        is_final=True,
                        exit_code=event.exit_code,
                    )
                    _record_output_tick(event.session_id, len(clean_final_output))
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
        except Exception as feedback_exc:
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
        # NOTE: Keep output_message_id in DB - it's reused for all commands in the session
        # Only cleared when session closes (/exit command)

        logger.debug("Polling ended for session %s", session_id)
