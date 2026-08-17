"""Polling lifecycle orchestration and transcript-driven fanout."""

import asyncio
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
from teleclaude.core.first_activity import record_first_activity
from teleclaude.core.identity import resolve_discord_author_alias
from teleclaude.core.inbound_types import TurnPartKind
from teleclaude.core.models import MessageAuthor, MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputChanged, OutputPoller, ProcessExited
from teleclaude.core.reminder_projection import NativeProjectionCandidate, project_session_sources
from teleclaude.core.session_title import clear_title_projection_state
from teleclaude.core.turn_binding import _native_entry_id, bind_pending_native_turns
from teleclaude.output_projection.models import ProjectionSurface, visibility_policy_for_person
from teleclaude.output_projection.visibility import is_control_header_text
from teleclaude.utils.transcript import (
    _get_entries_for_agent,
    count_renderable_assistant_blocks,
    extract_last_turn_boundary_timestamp,
    find_last_real_user_turn,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)
from teleclaude.utils.transcript import extract_recent_transcript_turns as _extract_recent_transcript_turns
from teleclaude.utils.transcript_discovery import TranscriptCandidate, discover_transcripts, extract_session_id

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.db import AcceptedTurnBindingRecord
    from teleclaude.core.models import Session

logger = get_logger(__name__)
OUTPUT_METRICS_SUMMARY_INTERVAL_S = 30.0
_PEER_REFLECTION_TRANSPORT_FAILURE_EVENT = "peer_reflection_transport_failure"
_PEER_REFLECTION_DISPATCHED_EVENT = "peer_reflection_dispatched"
_PEER_REFLECTION_SENT_OUTCOME = "sent"
_PEER_REFLECTION_FAILED_OUTCOME = "failed"
_PEER_REFLECTION_TRANSPORT_FAILURE_REASON = "transport_failure"
_PEER_REFLECTION_ALIAS_KIND = "peer"
_REFLECTION_DEFERRED_CONFLICT_EVENT = "polling_reflection_deferred_conflict"
_REFLECTION_DEFERRED_UNBOUND_EVENT = "polling_reflection_deferred_unbound"
_INVALID_ACTIVE_AGENT_EVENT = "polling_invalid_active_agent"
_OUTPUT_CADENCE_SUMMARY_EVENT = "polling_output_cadence_summary"
_BACKGROUND_POLLER_CRASHED_EVENT = "polling_background_poller_crashed"
_TURN_BINDING_PASS_FAILED_EVENT = "polling_turn_binding_pass_failed"
_TRANSCRIPT_BIND_ERROR_EVENT = "polling_transcript_bind_error"
_POLLING_LOOP_FAILED_EVENT = "polling_loop_failed"
_POLLING_ENDED_EVENT = "polling_ended"
_PROJECTION_DEFERRED_STALE_ORIGIN_EVENT = "polling_projection_deferred_stale_origin"
_USER_INPUT_REFLECTION_SKIPPED_EVENT = "polling_user_input_reflection_skipped"
_POLLING_ALREADY_ACTIVE_EVENT = "polling_already_active_duplicate_ignored"
_OUTPUT_CHANGED_RECEIVED_EVENT = "polling_output_changed_received"
_SESSION_MISSING_DURING_OUTPUT_EVENT = "polling_session_missing_during_output"
_OUTPUT_SESSION_FETCHED_EVENT = "polling_output_session_fetched"
_SESSION_MISSING_DURING_EXIT_EVENT = "polling_session_missing_during_exit"
_SESSION_TERMINATED_AFTER_EXIT_EVENT = "polling_session_terminated_after_tmux_exit"
_POLLING_STOPPED_ON_EXIT_EVENT = "polling_stopped_on_process_exit"
_TMUX_MISSING_NO_RECOVERY_EVENT = "polling_tmux_missing_no_recovery"
_ERROR_FEEDBACK_SEND_FAILED_EVENT = "polling_error_feedback_send_failed"
_NOTICE_VISIBILITY_DECISION_EVENT = "notice_visibility_decision"
_NOTICE_SUPPRESSED_OUTCOME = "suppressed"
_NOTICE_DAEMON_CONTROL_REASON = "daemon_control"

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
        logger.warning(
            _INVALID_ACTIVE_AGENT_EVENT,
            session_id=session.session_id,
            active_agent=active_agent,
        )
        return None

    turn_cursor = extract_last_turn_boundary_timestamp(transcript_path, agent_name)
    assistant_messages = get_assistant_messages_since(transcript_path, agent_name, since_timestamp=turn_cursor)
    if not assistant_messages:
        return None

    policy = visibility_policy_for_person(
        human_role=session.human_role,
        person_email=session.human_email,
        surface=ProjectionSurface.MOBILE,
        include_thinking=True,
    )
    renderable_block_count = count_renderable_assistant_blocks(
        transcript_path,
        agent_name,
        since_timestamp=turn_cursor,
        include_tools=policy.include_tools,
        include_tool_results=False,
    )
    is_multi = renderable_block_count > 1

    if is_multi:
        message, last_ts = render_agent_output(
            transcript_path,
            agent_name,
            include_tools=policy.include_tools,
            include_tool_results=False,
            since_timestamp=turn_cursor,
            include_timestamps=False,
        )
    else:
        message, last_ts = render_clean_agent_output(
            transcript_path,
            agent_name,
            since_timestamp=turn_cursor,
            include_tools=policy.include_tools,
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
        _OUTPUT_CADENCE_SUMMARY_EVENT,
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
    _pending_final_versions.pop(session_id, None)
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
# Stop versions awaiting a final projection pass, per session.
_pending_final_versions: dict[str, datetime] = {}
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


def _handle_background_poller_result(task: asyncio.Task[None], session_id: str) -> None:
    """Consume background poller task exceptions to avoid unretrieved-task noise."""
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.error(
            _BACKGROUND_POLLER_CRASHED_EVENT,
            session_id=session_id,
            error=str(exc),
            exc_info=True,
        )


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


async def _register_session_projection(session_id: str, final_version: datetime | None = None) -> bool:
    """Claim the projection slot or queue a follow-up.

    Returns True when the caller should start a new projection task. Returns
    False when one is already in flight; the slot is marked pending so the
    running task will re-run after it finishes.

    A supplied ``final_version`` is recorded before the active check, so a stop
    arriving mid-pass cannot be swallowed by coalescing: the running task picks
    it up on its next loop. The greatest version wins — a newer stop supersedes
    an older undelivered one, because the durable payload is last-turn state and
    the older turn's content is already gone.
    """
    async with _session_projection_signal_lock:
        if final_version is not None:
            known = _pending_final_versions.get(session_id)
            if known is None or final_version > known:
                _pending_final_versions[session_id] = final_version
        if session_id in _active_session_projections:
            _pending_session_projections.add(session_id)
            return False
        _active_session_projections.add(session_id)
        return True


async def _peek_final_version(session_id: str) -> datetime | None:
    """Read the pending final version without consuming it."""
    async with _session_projection_signal_lock:
        return _pending_final_versions.get(session_id)


async def _clear_final_version(session_id: str, delivered: datetime) -> None:
    """Drop a final version once its pass attempted delivery.

    Retained when a newer stop has superseded it in the meantime, so the newer
    version still gets its own pass.
    """
    async with _session_projection_signal_lock:
        known = _pending_final_versions.get(session_id)
        if known is not None and known <= delivered:
            _pending_final_versions.pop(session_id, None)


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
) -> tuple["Session", bool, bool]:
    """Project the latest authoritative user message from transcript into canonical state.

    Daemon-control shape is tested only in the receipt-less fallback, after a
    binding and an accepted-unbound receipt are both ruled out.
    """

    transcript_path = session.native_log_file
    active_agent = session.active_agent
    if not transcript_path or not active_agent:
        return session, True, False

    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        return session, True, False

    entries = await asyncio.to_thread(_get_entries_for_agent, transcript_path, agent_name)
    if not entries:
        return session, True, False
    turn = find_last_real_user_turn(entries, agent_name)
    if turn is None or turn.text is None:
        return session, True, False

    user_text = turn.text
    if not user_text.strip():
        return session, True, False

    transcript_dt = _as_utc(turn.timestamp) if isinstance(turn.timestamp, datetime) else None
    # Dedupe against the projection-owned watermark, not the mixed-purpose last_message_sent_at.
    watermark_dt = _as_utc(session.last_projected_at)
    if watermark_dt is not None and transcript_dt is not None and transcript_dt <= watermark_dt:
        return session, True, False

    if not has_fresh_origin_for_user(session, user_text):
        logger.debug(
            _PROJECTION_DEFERRED_STALE_ORIGIN_EVENT,
            session_id=session.session_id,
            origin=(session.last_input_origin or "").strip() or None,
            projected_at=watermark_dt.isoformat() if watermark_dt else None,
        )
        return session, False, False

    source = (session.last_input_origin or "").strip() or InputOrigin.TERMINAL.value

    # Attribution is read from the durable accepted-turn binding, never
    # re-derived from rendered-header text or mutable session-origin state
    # (Turn provenance invariant). The binding was just attempted by
    # `bind_pending_native_turns` immediately before this call, in the same
    # pass, so it is already durable here when one exists for this entry.
    binding: AcceptedTurnBindingRecord | None = None
    entry_id: str | None = None
    if session.native_session_id:
        entry = entries[turn.entry_index]
        entry_id = _native_entry_id(entry, agent_name, timestamp=entry.get("timestamp"), text=user_text)
        binding = await db.get_turn_binding(f"{session.session_id}:{entry_id}")

    if binding is not None:
        await _reflect_bound_turn(session, adapter_client, binding, entry_text=user_text, source=source)
    else:
        if entry_id is not None and session.native_session_id:
            conflicted_entry_ids = await db.get_conflicted_native_entry_ids(
                native_runtime=agent_name.value,
                native_session_id=session.native_session_id,
            )
            if entry_id in conflicted_entry_ids:
                logger.debug(
                    _REFLECTION_DEFERRED_CONFLICT_EVENT, session_id=session.session_id, native_entry_id=entry_id
                )
                return session, False, True
        unbound_rows = await db.get_unbound_delivered_inbound(session_id=session.session_id)
        if any(row["content"] in user_text for row in unbound_rows):
            # An accepted receipt exists for this content but has not bound
            # yet this pass (not-yet-processed, or an unresolved input
            # conflict). Never guess attribution here — defer and let the
            # next poll's binding pass settle it.
            logger.debug(_REFLECTION_DEFERRED_UNBOUND_EVENT, session_id=session.session_id)
            return session, False, False
        # No accepted receipt exists and the same-pass binding attempt did not
        # create a durable turn: the entry may predate cutover or lack a
        # resolvable local author. There is no caller attribution to recover.
        # Shape is the only signal left for a receipt-less entry.
        if is_control_header_text(user_text):
            logger.info(
                _NOTICE_VISIBILITY_DECISION_EVENT,
                outcome=_NOTICE_SUPPRESSED_OUTCOME,
                reason=_NOTICE_DAEMON_CONTROL_REASON,
                session_id=session.session_id,
                watermark_advanced=False,
            )
        else:
            try:
                await adapter_client.broadcast_user_input(session, user_text, source)
            except Exception as exc:
                logger.debug(
                    _USER_INPUT_REFLECTION_SKIPPED_EVENT,
                    session_id=session.session_id,
                    error=str(exc),
                )

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
    return refreshed or session, True, False


async def _reflect_bound_turn(
    session: "Session",
    adapter_client: "AdapterClient",
    binding: "AcceptedTurnBindingRecord",
    *,
    entry_text: str,
    source: str,
) -> None:
    """Reflect peer/local parts; typed reminder-entry projection owns reminder parts."""
    caller_origin_prefix_len = 0
    caller_origin_suffix_len = 0
    bundle_key: str | None = None
    if binding.inbound_queue_id is not None:
        inbound_row = await db.get_inbound_row(binding.inbound_queue_id)
        caller_origin_prefix_len = inbound_row.caller_origin_prefix_len if inbound_row is not None else 0
        caller_origin_suffix_len = inbound_row.caller_origin_suffix_len if inbound_row is not None else 0
        bundle_key = inbound_row.source_message_id if inbound_row is not None else None
    for sequence_index, part in enumerate(binding.parts):
        if part.part_kind is TurnPartKind.INJECTED_REMINDER:
            continue
        body_start = part.span_start
        body_end = part.span_end
        if part.part_kind is TurnPartKind.INJECTED_PEER and caller_origin_prefix_len:
            body_start += caller_origin_prefix_len
        if part.part_kind is TurnPartKind.INJECTED_PEER and caller_origin_suffix_len:
            body_end -= caller_origin_suffix_len
        part_text = entry_text[body_start:body_end]
        if not part_text:
            continue
        if part.part_kind is TurnPartKind.INJECTED_PEER:
            actor_name, actor_avatar_url = _resolve_caller_reflection_presentation(
                part.author, owning_session_id=session.session_id, job_role=part.author_job_role
            )
            try:
                platform_message_id = await adapter_client.broadcast_peer_reflection(
                    session, part_text, actor_name=actor_name, actor_avatar_url=actor_avatar_url
                )
            except Exception:
                platform_message_id = None
            delivered = platform_message_id is not None
            if not delivered:
                logger.error(
                    _PEER_REFLECTION_TRANSPORT_FAILURE_EVENT,
                    session_id=session.session_id,
                    part_id=part.part_id,
                    author_class=part.author.kind.value,
                )
            logger.info(
                _PEER_REFLECTION_DISPATCHED_EVENT,
                outcome=_PEER_REFLECTION_SENT_OUTCOME if delivered else _PEER_REFLECTION_FAILED_OUTCOME,
                reason=None if delivered else _PEER_REFLECTION_TRANSPORT_FAILURE_REASON,
                binding_id=binding.binding_id,
                part_id=part.part_id,
                bundle_key=bundle_key,
                segment_id=str(part.part_id),
                sequence_index=sequence_index,
                alias_kind=_PEER_REFLECTION_ALIAS_KIND,
                avatar_present=bool(actor_avatar_url),
                platform_message_id=platform_message_id,
                body_len=len(part_text),
                header_excluded=body_start != part.span_start,
                caller_session_id=part.original_source_session_id,
            )
        else:
            try:
                await adapter_client.broadcast_user_input(session, part_text, source)
            except Exception as exc:
                logger.debug(
                    _USER_INPUT_REFLECTION_SKIPPED_EVENT,
                    session_id=session.session_id,
                    error=str(exc),
                )


def _resolve_caller_reflection_presentation(
    author: MessageAuthor, *, owning_session_id: str, job_role: str | None
) -> tuple[str, str | None]:
    """Resolve a session-originated caller's structural author to its remote Discord identity.

    Always a remote author in practice: this path only ever resolves a
    caller from another session (O5's "any author from another session
    appends (peer)"), so ``owning_session_id`` (the target session) never
    equals the caller's own session id.
    """
    return resolve_discord_author_alias(author, owning_session_id=owning_session_id, job_role=job_role)


async def _project_session_from_transcript_locked(
    session: "Session",
    adapter_client: "AdapterClient",
    *,
    started_at: float = 0.0,
    last_changed_at: float | None = None,
    final_version: datetime | None = None,
) -> "Session":
    """Project transcript truth into canonical session state and outbound delivery.

    Invoked once per coalesced signal. Transcript files are the source of
    truth; session projection owns source-order gating and output dedupe before
    adapter delivery mechanics run.
    """
    try:
        await bind_pending_native_turns(session)
    except Exception:
        # Binding is additive discovery, not a gate: a failed pass here must
        # never block reflection or output projection. Unbound rows retry
        # every subsequent poll (Task 2a's retention keeps them available).
        logger.warning(
            _TURN_BINDING_PASS_FAILED_EVENT,
            session_id=session.session_id,
            exc_info=True,
        )

    session, can_project_live_output, can_project_final_output = await _project_user_reflection(session, adapter_client)
    can_project_native = can_project_live_output or (can_project_final_output and final_version is not None)
    transcript_update = (
        await asyncio.to_thread(_build_transcript_output_update, session) if can_project_native else None
    )
    native_candidate: NativeProjectionCandidate | None = None
    if transcript_update is not None:
        message, last_ts, is_multi = transcript_update
        # No session-wide dedupe gate here (Task 11): each UI lane owns its own
        # cursor and decides independently, inside send_output_update, whether
        # it has already delivered this exact render for the session's current
        # generation. A single shared digest let whichever lane advanced first
        # mute the others on a partial failure; per-lane cursors make every
        # call a cheap, correct no-op for a lane that's already caught up
        # without starving a lane that isn't.
        changed_at = last_changed_at if last_changed_at is not None else last_ts.timestamp()
        output_metadata: MessageMetadata | None = None
        if session.active_agent:
            output_author = MessageAuthor.for_agent(
                session_id=session.session_id,
                active_agent=session.active_agent,
                thinking_mode=session.thinking_mode,
            )
            output_alias, output_avatar_url = resolve_discord_author_alias(
                output_author,
                owning_session_id=session.session_id,
                job_role=session.job,
            )
            output_metadata = MessageMetadata(
                reflection_actor_name=output_alias,
                reflection_actor_avatar_url=output_avatar_url,
            )

        async def _deliver_native() -> None:
            await adapter_client.send_output_update(
                session,
                message,
                started_at,
                changed_at,
                is_final=final_version is not None,
                multi_message=is_multi,
                delivery_ts=final_version or last_ts,
                output_metadata=output_metadata,
            )
            if final_version is not None:
                await _clear_final_version(session.session_id, final_version)
            _record_output_tick(session.session_id, len(message))

        native_candidate = NativeProjectionCandidate(
            occurred_at=final_version or last_ts,
            stable_id=(final_version or last_ts).isoformat(),
            deliver=_deliver_native,
        )

    await project_session_sources(session, adapter_client, native_candidate=native_candidate)
    refreshed = await db.get_session(session.session_id)
    if refreshed is not None:
        session = refreshed
    return session


async def project_session_from_transcript(
    session: "Session",
    adapter_client: "AdapterClient",
    *,
    started_at: float = 0.0,
    last_changed_at: float | None = None,
    final_version: datetime | None = None,
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
            final_version=final_version,
            started_at=started_at,
            last_changed_at=last_changed_at,
        )


async def schedule_session_projection(
    session_id: str,
    adapter_client: "AdapterClient",
    *,
    headless_only: bool = False,
    final_version: datetime | None = None,
) -> bool:
    """Schedule a transcript projection pass for a session.

    Coalesces overlapping signals: while a projection is in flight, additional
    calls mark the slot pending and the running task re-runs once on completion.
    This guarantees state changes that land during a projection (e.g. a session
    title update) are reflected on the next pass without needing a fresh signal.

    ``final_version`` marks this signal as carrying a stop version. That pass
    delivers the turn's final output stamped with that version, so the receipt
    settles the obligation staged under the same version. Ordinary chunk passes
    are unaffected and keep their digest dedupe.
    """
    if not await _register_session_projection(session_id, final_version):
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
                        _TRANSCRIPT_BIND_ERROR_EVENT,
                        session_id=session_id,
                        error=str(exc),
                        exc_info=True,
                    )

                await _wait_for_session_projection_cadence(session_id)
                pass_version = await _peek_final_version(session_id)
                await project_session_from_transcript(session, adapter_client, final_version=pass_version)
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
            _POLLING_ALREADY_ACTIVE_EVENT,
            session_id=session_id,
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
    PreToolUse, agy PreToolUse, Codex PreToolUse). Transcript-path binding is
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
                record_first_activity(event.session_id)
                logger.debug(
                    _OUTPUT_CHANGED_RECEIVED_EVENT,
                    session_id=session_id,
                )

                # Fetch session once for all operations
                session = await db.get_session(event.session_id)
                if not session:
                    logger.debug(
                        _SESSION_MISSING_DURING_OUTPUT_EVENT,
                        session_id=event.session_id,
                    )
                    return

                logger.trace(
                    _OUTPUT_SESSION_FETCHED_EVENT,
                    session_id=event.session_id,
                    output_digest=session.last_output_digest,
                )

                # Opportunistic transcript-path binding. Tool activity comes from
                # the native hook, not from inferring it here.
                try:
                    if await _try_bind_transcript_path(session):
                        refreshed = await db.get_session(event.session_id)
                        if refreshed is not None:
                            session = refreshed
                except Exception as exc:
                    logger.error(
                        _TRANSCRIPT_BIND_ERROR_EVENT,
                        session_id=event.session_id,
                        error=str(exc),
                        exc_info=True,
                    )

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
                        _SESSION_MISSING_DURING_EXIT_EVENT,
                        session_id=event.session_id,
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
                            _SESSION_TERMINATED_AFTER_EXIT_EVENT,
                            session_id=event.session_id,
                            exit_code=event.exit_code,
                        )
                    else:
                        logger.info(
                            _POLLING_STOPPED_ON_EXIT_EVENT,
                            session_id=event.session_id,
                            exit_code=event.exit_code,
                        )
                else:
                    # Tmux session disappeared without a clean process exit.
                    # Recovery is demand-driven; do not attempt background healing here.
                    logger.warning(
                        _TMUX_MISSING_NO_RECOVERY_EVENT,
                        session_id=event.session_id,
                    )
    except Exception as exc:
        logger.error(
            _POLLING_LOOP_FAILED_EVENT,
            session_id=session_id,
            error=str(exc),
        )
        try:
            await adapter_client.send_error_feedback(
                session_id,
                f"Polling error: {exc}",
            )
        except Exception as feedback_exc:
            logger.error(
                _ERROR_FEEDBACK_SEND_FAILED_EVENT,
                session_id=session_id,
                error=str(feedback_exc),
            )
        raise

    finally:
        # Cleanup state
        await _unregister_polling(session_id)
        _cleanup_codex_input_state(session_id)
        _clear_output_metrics(session_id)
        # NOTE: Don't clear pending_deletions here - let _pre_handle_user_input handle deletion on next input

        logger.debug(_POLLING_ENDED_EVENT, session_id=session_id)
