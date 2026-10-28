"""Polling lifecycle orchestration and transcript-driven fanout."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core import session_cleanup, tmux_bridge
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.db import db
from teleclaude.core.identity import resolve_discord_author_alias, session_person_role
from teleclaude.core.injected_text import (
    TranscriptEntryKind,
    caller_occurrence_key,
    classify_transcript_text,
    recognize_delivered_text,
    scan_injected_envelopes,
    visible_input_preview,
    visible_input_update,
)
from teleclaude.core.models import MessageAuthor, MessageMetadata
from teleclaude.core.models._adapter import session_is_unattended
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputChanged, OutputPoller, ProcessExited
from teleclaude.core.session_compaction import active_compaction_attempt
from teleclaude.core.session_output import assistant_messages_are_bare_noop
from teleclaude.core.session_title import clear_title_projection_state
from teleclaude.core.session_transcript import session_transcript
from teleclaude.core.turn_binding import bind_pending_native_turns, binding_id_for_native_entry
from teleclaude.core.user_reflection_observation import (
    UserReflectionProjectionOutcome,
    UserReflectionProjectionReason,
    observe_user_reflection_projection,
)
from teleclaude.core.user_turn_reflection import SKIPPED_TURN_REFLECTION, reflect_user_turn_segments
from teleclaude.output_projection.models import ProjectionSurface, visibility_policy_for_person
from teleclaude.utils.transcript import (
    ClaudeTurnCommitment,
    ClaudeTurnCommitmentOutcome,
    ClaudeTurnCommitmentResolver,
    _get_entries_for_agent,
    count_renderable_assistant_blocks,
    extract_last_turn_boundary_timestamp,
    find_last_turn_start,
    get_assistant_messages_since,
    native_entry_id,
    render_agent_output,
    render_clean_agent_output,
)
from teleclaude.utils.transcript.source_views import transcript_read_scope
from teleclaude.utils.transcript_discovery import TranscriptCandidate, discover_transcripts, extract_session_id

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)
OUTPUT_METRICS_SUMMARY_INTERVAL_S = 30.0
_OUTPUT_CADENCE_SUMMARY_EVENT = "polling_output_cadence_summary"
_BACKGROUND_POLLER_CRASHED_EVENT = "polling_background_poller_crashed"
_TRANSCRIPT_BIND_ERROR_EVENT = "polling_transcript_bind_error"
_PROJECTION_SESSION_READ_FAILED_EVENT = "polling_projection_session_read_failed"
_PROJECTION_PASS_FAILED_EVENT = "polling_projection_pass_failed"
_POLLING_LOOP_FAILED_EVENT = "polling_loop_failed"
_POLLING_ENDED_EVENT = "polling_ended"
_PROJECTION_DEFERRED_STALE_ORIGIN_EVENT = "polling_projection_deferred_stale_origin"
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
_GENERATION_ID_PREFIX = "gen:"
_CONVERSATION_INPUT_ORIGINS = frozenset(
    {InputOrigin.TELEGRAM.value, InputOrigin.DISCORD.value, InputOrigin.WHATSAPP.value}
)


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
    """Render the full cumulative transcript-backed output for one session turn."""
    transcript = session_transcript(session)
    if transcript is None:
        return None
    transcript_path, agent_name = transcript.path, transcript.agent

    turn_cursor = extract_last_turn_boundary_timestamp(transcript_path, agent_name)
    assistant_messages = get_assistant_messages_since(transcript_path, agent_name, since_timestamp=turn_cursor)
    if not assistant_messages:
        return None
    if assistant_messages_are_bare_noop(assistant_messages):
        return None

    policy = visibility_policy_for_person(
        human_role=session_person_role(session),
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
    """Bind a discovered native transcript path, returning whether the DB changed."""
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


def _fresh_visible_input_matches(session: "Session", text: str) -> bool:
    """Return whether this turn matches a visible input accepted after the watermark."""
    visible = visible_input_preview(text)
    if visible is None or visible != session.last_input:
        return False
    accepted_at = _as_utc(session.last_input_written_at)
    projected_at = _as_utc(session.last_projected_at)
    return accepted_at is not None and (projected_at is None or accepted_at > projected_at)


def _accepted_conversation_view(session: "Session", text: str) -> str:
    """Return native text without a verified delivery mark for its fresh acceptance."""
    origin = (session.last_input_origin or "").strip()
    if origin not in _CONVERSATION_INPUT_ORIGINS or not session.active_agent:
        return text
    accepted_view = recognize_delivered_text(text, AgentName.from_str(session.active_agent))
    if accepted_view != text and _stored_preview_matches(session, accepted_view, require_stored=True):
        return accepted_view
    return text


def _preserved_visible_input(session: "Session", user_text: str) -> str | None:
    """Return the stored visible span when an acceptance writer owns this turn.

    A delivered turn can carry a source text that never reaches the transcript
    — a command shorthand expands into its loader before injection — and the
    writer that accepted it stored the human's own words. Deriving the span
    from the transcript would replace those words with the expansion, so the
    stored span stands.

    A turn typed into the pane has no acceptance writer. Reusing what is stored
    there pins the row to an earlier turn for the life of the session, because
    this projection is the only thing that would ever move it.
    """
    origin = (session.last_input_origin or "").strip()
    if not origin or origin == InputOrigin.TERMINAL.value:
        return None
    if not has_fresh_origin_for_user(session, user_text):
        return None
    return session.last_input


def has_fresh_origin_for_user(
    session: "Session",
    user_text: str,
    *,
    transcript_at: datetime | None = None,
) -> bool:
    """Return whether last_input_origin belongs to this unprojected user turn."""

    origin = (session.last_input_origin or "").strip()
    if not origin:
        return False
    projected_at = _as_utc(session.last_projected_at)
    if origin in _CONVERSATION_INPUT_ORIGINS and _fresh_visible_input_matches(session, user_text):
        # A control delivery can replace the operational fingerprint between
        # UI acceptance and this hook. The clean span and its own acceptance
        # time preserve the adapter origin until projection advances the
        # watermark, so the origin adapter will not receive a duplicate.
        return True
    if origin == InputOrigin.TERMINAL.value and transcript_at is not None:
        # A later control wake can replace the terminal input fingerprint while
        # leaving the user's transcript turn unprojected. The transcript's own
        # timestamp is authoritative for pane-authored turns; the watermark
        # still prevents replaying an older user entry.
        transcript_time = _as_utc(transcript_at)
        return transcript_time is not None and (projected_at is None or transcript_time > projected_at)

    user_text = _accepted_conversation_view(session, user_text)
    if not _stored_preview_matches(session, user_text, require_stored=origin != InputOrigin.TERMINAL.value):
        return False

    accepted_at = _as_utc(session.last_message_sent_at)
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
    """Claim the projection slot or queue a follow-up, retaining the newest stop."""
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
    """Drop the delivered final version unless a newer stop superseded it."""
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
    """Project the latest authoritative user message into canonical state."""
    transcript = session_transcript(session)
    if transcript is None:
        return session, True, False
    agent_name = transcript.agent

    entries = await asyncio.to_thread(_get_entries_for_agent, transcript.path, agent_name)
    if not entries:
        return session, True, False
    turn = find_last_turn_start(entries, agent_name)
    if turn is None:
        return session, True, False

    entry_id = native_entry_id(entries[turn.entry_index], agent_name) if session.native_session_id else None
    if entry_id is not None:
        await db.create_output_generation(
            generation_id=f"{_GENERATION_ID_PREFIX}{agent_name.value}:{session.native_session_id}:{entry_id}",
            session_id=session.session_id,
            native_runtime=agent_name.value,
            native_session_id=session.native_session_id,
            native_entry_id=entry_id,
        )
    await bind_pending_native_turns(session, entries, agent_name)
    # A turn opened by platform text, such as the dispatch loader, owns its
    # output generation but carries nothing an author sent to reflect.
    user_text = turn.authored_text
    if user_text is None or not user_text.strip():
        return session, True, False
    user_text = _accepted_conversation_view(session, user_text)
    transcript_dt = _as_utc(turn.timestamp) if isinstance(turn.timestamp, datetime) else None
    requires_binding = any(
        segment.kind is TranscriptEntryKind.IDENTITY_CONTENT and caller_occurrence_key(segment.opening) is not None
        for segment in scan_injected_envelopes(user_text)
    )
    binding_id = (
        binding_id_for_native_entry(session.session_id, entry_id) if requires_binding and entry_id is not None else None
    )
    watermark_dt = _as_utc(session.last_projected_at)
    if watermark_dt is not None and transcript_dt is not None and transcript_dt <= watermark_dt:
        observe_user_reflection_projection(
            session,
            native_entry_id=entry_id,
            commitment=None,
            binding_id=binding_id,
            outcome=UserReflectionProjectionOutcome.SUPPRESSED,
            reason=UserReflectionProjectionReason.PROJECTION_WATERMARK,
        )
        return session, True, False

    commitment: ClaudeTurnCommitment | None = None
    if entry_id is not None:
        if agent_name is AgentName.CLAUDE:
            commitment = ClaudeTurnCommitmentResolver(entries).resolve(entry_id)

    def observe(
        outcome: UserReflectionProjectionOutcome,
        reason: StrEnum,
        platform_message_ids: tuple[str, ...] = (),
    ) -> None:
        observe_user_reflection_projection(
            session,
            native_entry_id=entry_id,
            commitment=commitment,
            binding_id=binding_id,
            outcome=outcome,
            reason=reason,
            platform_message_ids=platform_message_ids,
        )

    if not has_fresh_origin_for_user(session, user_text, transcript_at=transcript_dt):
        logger.debug(
            _PROJECTION_DEFERRED_STALE_ORIGIN_EVENT,
            session_id=session.session_id,
            origin=(session.last_input_origin or "").strip() or None,
            projected_at=watermark_dt.isoformat() if watermark_dt else None,
        )
        observe(UserReflectionProjectionOutcome.DEFERRED, UserReflectionProjectionReason.STALE_ORIGIN)
        return session, False, False
    source = (session.last_input_origin or "").strip() or InputOrigin.TERMINAL.value
    if commitment is not None and commitment.outcome is not ClaudeTurnCommitmentOutcome.COMMITTED:
        observe(UserReflectionProjectionOutcome.DEFERRED, commitment.reason)
        return session, False, False
    if classify_transcript_text(user_text).kind is TranscriptEntryKind.PLATFORM_CONTROL:
        logger.info(
            _NOTICE_VISIBILITY_DECISION_EVENT,
            outcome=_NOTICE_SUPPRESSED_OUTCOME,
            reason=_NOTICE_DAEMON_CONTROL_REASON,
            session_id=session.session_id,
            watermark_advanced=False,
        )
        observe(UserReflectionProjectionOutcome.SUPPRESSED, UserReflectionProjectionReason.DAEMON_CONTROL)
    elif session_is_unattended(session):
        observe(UserReflectionProjectionOutcome.SUPPRESSED, UserReflectionProjectionReason.UNATTENDED)
    else:
        result = SKIPPED_TURN_REFLECTION
        if InputOrigin.DISCORD.value in adapter_client.adapters:
            result = await reflect_user_turn_segments(
                session,
                adapter_client,
                user_text=user_text,
                source=source,
            )
        outcome, reason = _user_reflection_delivery_disposition(
            adapter_client,
            source=source,
            platform_message_ids=result.platform_message_ids,
            reflectable=result.reflectable,
        )
        if result.failed:
            outcome, reason = UserReflectionProjectionOutcome.FAILED, UserReflectionProjectionReason.TRANSPORT_FAILURE
        observe(outcome, reason, result.platform_message_ids)

    if transcript_dt is not None:
        await db.update_session(
            session.session_id,
            last_message_sent=user_text[:200],
            last_message_sent_at=transcript_dt,
            last_projected_at=transcript_dt,
            **visible_input_update(
                user_text,
                accepted_at=transcript_dt,
                visible_source_text=_preserved_visible_input(session, user_text),
            ),
        )
    else:
        await db.update_session(
            session.session_id,
            last_message_sent=user_text[:200],
            **visible_input_update(user_text, visible_source_text=_preserved_visible_input(session, user_text)),
        )
    refreshed = await db.get_session(session.session_id)
    return refreshed or session, True, False


def _user_reflection_delivery_disposition(
    adapter_client: "AdapterClient",
    *,
    source: str,
    platform_message_ids: tuple[str, ...],
    reflectable: bool,
) -> tuple[UserReflectionProjectionOutcome, UserReflectionProjectionReason]:
    if platform_message_ids:
        return UserReflectionProjectionOutcome.SENT, UserReflectionProjectionReason.PLATFORM_RECEIPT
    if source.strip().lower() == InputOrigin.DISCORD.value:
        return UserReflectionProjectionOutcome.SUPPRESSED, UserReflectionProjectionReason.ORIGIN_ALREADY_VISIBLE
    if not reflectable:
        return UserReflectionProjectionOutcome.SUPPRESSED, UserReflectionProjectionReason.NO_REFLECTABLE_PART
    if InputOrigin.DISCORD.value not in adapter_client.adapters:
        return UserReflectionProjectionOutcome.SUPPRESSED, UserReflectionProjectionReason.TARGET_UNAVAILABLE
    return UserReflectionProjectionOutcome.FAILED, UserReflectionProjectionReason.TRANSPORT_FAILURE


async def _project_session_from_transcript_locked(
    session: "Session",
    adapter_client: "AdapterClient",
    *,
    started_at: float = 0.0,
    last_changed_at: float | None = None,
    final_version: datetime | None = None,
) -> "Session":
    """Project transcript truth into canonical session state and outbound delivery."""
    session, can_project_live_output, can_project_final_output = await _project_user_reflection(session, adapter_client)
    can_project_native = can_project_live_output or (can_project_final_output and final_version is not None)
    transcript_update = (
        await asyncio.to_thread(_build_transcript_output_update, session) if can_project_native else None
    )
    if transcript_update is not None:
        message, last_ts, is_multi = transcript_update
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
                job_role=session.role,
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

        await _deliver_native()
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
        if active_compaction_attempt(refreshed) is not None:
            return refreshed
        with transcript_read_scope():
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
    """Schedule one coalesced transcript projection, optionally carrying a stop version."""
    if not await _register_session_projection(session_id, final_version):
        return False

    async def _run() -> None:
        try:
            while True:
                try:
                    session = await db.get_session(session_id)
                except Exception:
                    logger.exception(_PROJECTION_SESSION_READ_FAILED_EVENT, session_id=session_id)
                    await _wait_for_session_projection_cadence(session_id)
                    continue
                if not session or (headless_only and session.lifecycle_status != "headless"):
                    return
                if active_compaction_attempt(session) is not None:
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
                try:
                    await project_session_from_transcript(session, adapter_client, final_version=pass_version)
                except Exception:
                    logger.exception(_PROJECTION_PASS_FAILED_EVENT, session_id=session_id)
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
    """Schedule polling with an in-memory duplicate guard."""
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
    """Poll tmux activity and push transcript-derived output for a session."""
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
                if active_compaction_attempt(session) is not None:
                    continue

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
                if active_compaction_attempt(session) is not None:
                    continue

                if event.exit_code is not None:
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
        await _unregister_polling(session_id)
        _cleanup_codex_input_state(session_id)
        _clear_output_metrics(session_id)
        logger.debug(_POLLING_ENDED_EVENT, session_id=session_id)
