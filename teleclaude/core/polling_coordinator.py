"""Polling coordinator for tmux activity detection and transcript-driven fanout.

Extracted from daemon.py to reduce file size and improve organization.
Handles polling lifecycle orchestration and central transcript-driven delivery.
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import session_cleanup, tmux_bridge
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.db import db
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputChanged, OutputPoller, ProcessExited
from teleclaude.core.session_title import clear_title_projection_state
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    extract_last_turn_boundary_timestamp,
    extract_last_user_message_with_timestamp,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)
from teleclaude.utils.transcript import extract_recent_transcript_turns as _extract_recent_transcript_turns
from teleclaude.utils.transcript_discovery import TranscriptCandidate, discover_transcripts, extract_session_id

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)
OUTPUT_METRICS_SUMMARY_INTERVAL_S = 30.0

# Retained as a module attribute for older test patch targets.
extract_recent_transcript_turns = _extract_recent_transcript_turns


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
    _last_session_projection_started_at.pop(session_id, None)
    clear_title_projection_state(session_id)


_transcript_bind_attempted: set[str] = set()


def _cleanup_codex_input_state(session_id: str) -> None:
    """Clean up transcript-bind tracking state when session ends."""
    _transcript_bind_attempted.discard(session_id)


def _discover_native_transcript_path(agent_name: AgentName, native_session_id: str) -> str | None:
    """Find a transcript path for an agent-native session id."""
    if agent_name == AgentName.CODEX:
        return discover_codex_transcript_path(native_session_id)

    candidates: list[TranscriptCandidate] = discover_transcripts([agent_name])
    for candidate in candidates:
        if extract_session_id(candidate.path, agent_name) == native_session_id:
            return str(candidate.path)
    return None


async def _try_bind_transcript_path(session: "Session") -> bool:
    """Opportunistically bind a native transcript path for any supported agent.

    Returns True when the DB was updated with a discovered transcript path.
    """
    active_agent = (session.active_agent or "").strip()
    if not active_agent:
        return False
    if session.session_id in _transcript_bind_attempted:
        return False
    native_session_id = (session.native_session_id or "").strip()
    if not native_session_id:
        return False
    if (session.native_log_file or "").strip():
        return False

    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        return False

    transcript_path = _discover_native_transcript_path(agent_name, native_session_id)
    if not transcript_path:
        return False
    await db.update_session(session.session_id, native_log_file=transcript_path)
    _transcript_bind_attempted.add(session.session_id)
    return True


_active_pollers: set[str] = set()
_poller_lock = asyncio.Lock()
_active_session_projections: set[str] = set()
_pending_session_projections: set[str] = set()
_session_projection_signal_lock = asyncio.Lock()
_last_session_projection_started_at: dict[str, float] = {}
_session_projection_locks: dict[str, asyncio.Lock] = {}
_session_projection_locks_lock = asyncio.Lock()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _message_preview(text: str) -> str:
    return text[:200]


def _stored_preview_matches(session: "Session", text: str, *, require_stored: bool = False) -> bool:
    stored = (session.last_message_sent or "").strip()
    if not stored:
        return not require_stored
    return stored == _message_preview(text).strip()


def has_fresh_origin_for_user(session: "Session", user_text: str) -> bool:
    """Return whether last_input_origin belongs to this unprojected user turn."""

    origin = (session.last_input_origin or "").strip()
    if not origin:
        return False
    if not _stored_preview_matches(session, user_text, require_stored=origin != InputOrigin.TERMINAL.value):
        return False

    accepted_at = _as_utc(session.last_message_sent_at)
    projected_at = _as_utc(session.last_projected_at)
    if projected_at is None:
        return accepted_at is not None or origin == InputOrigin.TERMINAL.value
    if accepted_at is None:
        return False
    return accepted_at > projected_at


def _output_projection_digest(message: str, delivery_ts: datetime, is_multi: bool) -> str:
    payload = "\0".join(
        (
            delivery_ts.astimezone(UTC).isoformat(),
            "multi" if is_multi else "single",
            message,
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


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


def _projection_cadence_s() -> float:
    """Return the coalesced projection cadence."""
    return max(0.0, float(config.polling.output_cadence_s))


async def _wait_for_session_projection_cadence(session_id: str) -> None:
    """Throttle scheduled projection starts to the configured session cadence."""
    cadence_s = _projection_cadence_s()
    if cadence_s <= 0:
        _last_session_projection_started_at[session_id] = time.monotonic()
        return

    now = time.monotonic()
    last_started_at = _last_session_projection_started_at.get(session_id)
    if last_started_at is not None:
        delay_s = cadence_s - (now - last_started_at)
        if delay_s > 0:
            await asyncio.sleep(delay_s)
    _last_session_projection_started_at[session_id] = time.monotonic()


async def _register_session_projection(session_id: str) -> bool:
    """Claim the projection slot or queue a follow-up.

    Returns True when the caller should start a new projection task. Returns
    False when one is already in flight; the slot is marked pending so the
    running task will re-run after it finishes.
    """
    async with _session_projection_signal_lock:
        if session_id in _active_session_projections:
            _pending_session_projections.add(session_id)
            return False
        _active_session_projections.add(session_id)
        return True


async def _consume_pending_projection(session_id: str) -> bool:
    """At end of a projection pass, decide whether to loop or release."""
    async with _session_projection_signal_lock:
        if session_id in _pending_session_projections:
            _pending_session_projections.discard(session_id)
            return True
        _active_session_projections.discard(session_id)
        return False


async def _release_session_projection(session_id: str) -> None:
    """Release the projection slot unconditionally (used in error paths)."""
    async with _session_projection_signal_lock:
        _pending_session_projections.discard(session_id)
        _active_session_projections.discard(session_id)


async def _get_session_projection_lock(session_id: str) -> asyncio.Lock:
    """Return the per-session projection lock shared by scheduled and poller paths."""
    async with _session_projection_locks_lock:
        lock = _session_projection_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _session_projection_locks[session_id] = lock
        return lock


async def _project_user_reflection(
    session: "Session",
    adapter_client: "AdapterClient",
) -> tuple["Session", bool]:
    """Project the latest authoritative user message from transcript into canonical state."""

    transcript_path = session.native_log_file
    active_agent = session.active_agent
    if not transcript_path or not active_agent:
        return session, True

    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        return session, True

    extracted = await asyncio.to_thread(extract_last_user_message_with_timestamp, transcript_path, agent_name)
    if not extracted:
        return session, True

    user_text, transcript_ts = extracted
    if not user_text.strip():
        return session, True

    transcript_dt = _as_utc(transcript_ts) if isinstance(transcript_ts, datetime) else None
    # Dedupe against the projection-owned watermark, not the mixed-purpose last_message_sent_at.
    watermark_dt = _as_utc(session.last_projected_at)
    if watermark_dt is not None and transcript_dt is not None and transcript_dt <= watermark_dt:
        return session, True

    if not has_fresh_origin_for_user(session, user_text):
        logger.debug(
            "Deferring transcript projection until user-turn origin is fresh: session=%s origin=%s projected_at=%s",
            session.session_id,
            (session.last_input_origin or "").strip() or "<none>",
            watermark_dt.isoformat() if watermark_dt else "<none>",
        )
        return session, False

    source = (session.last_input_origin or "").strip() or InputOrigin.TERMINAL.value
    # Mirror the output-lane admin copy rule: skip only when the origin itself
    # is Discord (origin delivery already hits Discord). Pipeline sessions
    # (worker/orchestrator/integrator) remain visible so the admin sees both
    # sides of the conversation in Discord.
    if source != InputOrigin.DISCORD.value:
        await adapter_client.broadcast_user_input(session, user_text, source)

    if transcript_dt is not None:
        await db.update_session(
            session.session_id,
            last_message_sent=user_text[:200],
            last_message_sent_at=transcript_dt,
            last_projected_at=transcript_dt,
        )
    else:
        await db.update_session(
            session.session_id,
            last_message_sent=user_text[:200],
        )
    refreshed = await db.get_session(session.session_id)
    return refreshed or session, True


async def _project_session_from_transcript_locked(
    session: "Session",
    adapter_client: "AdapterClient",
    *,
    started_at: float = 0.0,
    last_changed_at: float | None = None,
) -> "Session":
    """Project transcript truth into canonical session state and outbound delivery.

    Invoked once per coalesced signal. Transcript files are the source of
    truth; session projection owns source-order gating and output dedupe before
    adapter delivery mechanics run.
    """
    session, can_project_output = await _project_user_reflection(session, adapter_client)
    if not can_project_output:
        return session

    transcript_update = await asyncio.to_thread(_build_transcript_output_update, session)
    if transcript_update is not None:
        message, last_ts, is_multi = transcript_update
        projection_digest = _output_projection_digest(message, last_ts, is_multi)
        if session.last_projected_output_digest == projection_digest:
            return session
        changed_at = last_changed_at if last_changed_at is not None else last_ts.timestamp()
        await adapter_client.send_output_update(
            session,
            message,
            started_at,
            changed_at,
            multi_message=is_multi,
            delivery_ts=last_ts,
        )
        await db.update_session(session.session_id, last_projected_output_digest=projection_digest)
        refreshed = await db.get_session(session.session_id)
        if refreshed is not None:
            session = refreshed
        _record_output_tick(session.session_id, len(message))
    return session


async def project_session_from_transcript(
    session: "Session",
    adapter_client: "AdapterClient",
    *,
    started_at: float = 0.0,
    last_changed_at: float | None = None,
) -> "Session":
    """Project transcript truth through a per-session gate shared by all callers."""
    lock = await _get_session_projection_lock(session.session_id)
    async with lock:
        refreshed = await db.get_session(session.session_id)
        if refreshed is None:
            return session
        return await _project_session_from_transcript_locked(
            refreshed,
            adapter_client,
            started_at=started_at,
            last_changed_at=last_changed_at,
        )


async def schedule_session_projection(
    session_id: str,
    adapter_client: "AdapterClient",
    *,
    headless_only: bool = False,
) -> bool:
    """Schedule a transcript projection pass for a session.

    Coalesces overlapping signals: while a projection is in flight, additional
    calls mark the slot pending and the running task re-runs once on completion.
    This guarantees state changes that land during a projection (e.g. a session
    title update) are reflected on the next pass without needing a fresh signal.
    """
    if not await _register_session_projection(session_id):
        return False

    async def _run() -> None:
        try:
            while True:
                session = await db.get_session(session_id)
                if not session or (headless_only and session.lifecycle_status != "headless"):
                    return

                try:
                    if await _try_bind_transcript_path(session):
                        refreshed = await db.get_session(session_id)
                        if refreshed is not None:
                            session = refreshed
                except Exception as exc:
                    logger.error(
                        "Transcript bind failed during scheduled projection for session %s: %s",
                        session_id,
                        exc,
                        exc_info=True,
                    )

                await _wait_for_session_projection_cadence(session_id)
                await project_session_from_transcript(session, adapter_client)
                if not await _consume_pending_projection(session_id):
                    return
        finally:
            await _release_session_projection(session_id)

    task_name = f"project-headless-{session_id}" if headless_only else f"project-session-{session_id}"
    task = asyncio.create_task(_run(), name=task_name)
    task.add_done_callback(lambda t, sid=session_id: _handle_background_poller_result(t, sid))  # type: ignore[misc]
    return True


async def schedule_headless_projection(session_id: str, adapter_client: "AdapterClient") -> bool:
    """Schedule a transcript projection pass for a headless session."""
    return await schedule_session_projection(session_id, adapter_client, headless_only=True)


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


async def poll_and_send_output(
    session_id: str,
    tmux_session_name: str,
    output_poller: OutputPoller,
    adapter_client: "AdapterClient",
    _skip_register: bool = False,
) -> None:
    """Poll tmux activity and push transcript-derived output for a session.

    Tmux is a liveness and visible-activity signal only. Durable payloads —
    including tool activity — come from the agent's native hooks (Claude
    PreToolUse, Gemini BeforeTool, Codex PreToolUse). Transcript-path binding is
    opportunistic from polling and scheduled projection because some agent
    versions omit transcript_path on early lifecycle events.

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

                # Opportunistic transcript-path binding. Tool activity comes from
                # the native hook, not from inferring it here.
                try:
                    if await _try_bind_transcript_path(session):
                        refreshed = await db.get_session(event.session_id)
                        if refreshed is not None:
                            session = refreshed
                except Exception as e:
                    logger.error("Error in transcript bind: %s", e, exc_info=True)

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

        logger.debug("Polling ended for session %s", session_id)
