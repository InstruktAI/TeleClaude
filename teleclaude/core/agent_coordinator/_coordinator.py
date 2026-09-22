"""Core AgentCoordinator class composing incremental-output and fanout mixins."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import polling_coordinator
from teleclaude.core.activity_contract import serialize_activity_event
from teleclaude.core.agents import AgentName
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_delivery import schedule_debounced_delivery
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentDistressPayload,
    AgentEventContext,
    AgentHookEvents,
    AgentHookEventType,
    AgentIdlePayload,
    AgentOutputPayload,
    AgentSessionStartPayload,
    AgentStopActivityEvent,
    AgentStopCompletionSource,
    AgentStopPayload,
    ErrorEventContext,
    SessionLifecycleContext,
    SessionStatusContext,
    TeleClaudeEvents,
    ToolUseActivityEvent,
    UserPromptSubmitActivityEvent,
    UserPromptSubmitPayload,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.reminders.models import ReminderEvent, ReminderEventAnchor
from teleclaude.core.session_lifecycle import (
    LifecycleTransition,
    LifecycleTransitionReason,
    decide_codex_stop_recovery,
    transition_session,
)
from teleclaude.core.session_listeners import NotificationKind
from teleclaude.core.session_output import StopOutputKind, StopOutputResult, classify_stop_output
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_title import generate_session_title_from_transcript
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.core.tool_activity import build_tool_preview, extract_tool_name
from teleclaude.events.envelope import EventVisibility
from teleclaude.session_scoping._git import read_head_sha
from teleclaude.tts.manager import TTSManager
from teleclaude.utils import strip_ansi_codes
from teleclaude.utils.transcript import extract_last_user_message_with_timestamp, transcript_has_stop_response

from ._fanout import _FanoutMixin
from ._helpers import _is_checkpoint_prompt, wait_for_transcript_ready
from ._slow_work import schedule as schedule_slow_work

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.reminders import ReminderService

logger = get_logger(__name__)

_AGENT_STOP_OUTPUT_SUPPRESSED_EVENT = "agent_stop_output_suppressed"
_SESSION_OBSERVED_STOP_SENT_EVENT = "session_observed_stop_sent"
_AGENT_STOP_OUTPUT_SUPPRESSED_OUTCOME = "suppressed"
_AGENT_STOP_OUTPUT_BARE_NOOP_REASON = "bare_noop"
_HOOK_MESSAGE_KEY = "message"
_AGENT_SESSION_START_OBSERVED_EVENT = "agent_session_start_observed"
_AGENT_SESSION_START_OBSERVED_OUTCOME = "accepted"
_AGENT_SESSION_START_NORMALIZED_HOOK_REASON = "normalized_hook"
_AGENT_SESSION_LIFECYCLE_TRANSITION_EVENT = "agent_session_lifecycle_transition"
_AGENT_SESSION_LIFECYCLE_TRANSITION_OUTCOME = "active"
_AGENT_SESSION_LIFECYCLE_TRANSITION_REASON = "agent_session_started"
_AGENT_SESSION_LIFECYCLE_STATUS = "active"
_AGENT_IDLE_OBSERVED_EVENT = "agent_idle_observed"
_AGENT_IDLE_OBSERVED_OUTCOME = "recorded"
_AGENT_IDLE_MANUAL_NATIVE_COMMAND_REASON = "manual_native_command"
_AGENT_STOP_RECOVERY_DECIDED_EVENT = "agent_stop_recovery_decided"
_AGENT_TURN_FAILED_OBSERVED_EVENT = "agent_turn_failed_observed"
_AGENT_TURN_FAILED_OBSERVED_OUTCOME = "recorded"
_AGENT_TURN_FAILED_BOUNDARY_REASON = "agent_turn_failed"


class AgentCoordinator(
    _FanoutMixin,
):
    """Coordinator for agent events and inter-agent communication."""

    def __init__(
        self,
        client: AdapterClient,
        tts_manager: TTSManager,
        reminder_service: ReminderService | None = None,
    ) -> None:
        self.client = client
        self.tts_manager = tts_manager
        self.reminder_service = reminder_service
        self._background_tasks: set[asyncio.Task[object]] = set()
        # Track last emitted lifecycle status per session for guard checks.
        self._last_emitted_status: dict[str, str] = {}

    def _queue_background_task(
        self,
        coro: Coroutine[object, object, object],
        label: str,
    ) -> None:
        """Run non-critical work without blocking hook event handling."""
        task = asyncio.create_task(coro, name=label)
        self._background_tasks.add(task)

        def _on_done(done: asyncio.Task[object]) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Background task '%s' failed: %s", label, exc, exc_info=True)

                # Emit error event for user-visible failures (title updates, TTS)
                # Other background failures are logged but don't require user notification
                if "title" in label.lower():
                    try:
                        event_bus.emit(
                            TeleClaudeEvents.ERROR,
                            ErrorEventContext(
                                session_id=None,
                                message=f"Failed to update session title: {exc}",
                                source="agent_coordinator",
                                severity="warning",
                            ),
                            visibility=EventVisibility.CLUSTER,
                        )
                    except Exception:
                        pass

        task.add_done_callback(_on_done)

    async def _signal_projection_activity(self, session_id: str, final_version: datetime | None = None) -> None:
        """Drive one transcript projection pass from agent activity.

        ``final_version`` marks the pass as delivering a staged stop, so its
        receipt is written under the same version the lanes were enrolled with.
        """
        session = await db.get_session(session_id)
        if not session:
            return
        await db.update_last_activity(session_id)
        if session.lifecycle_status == "headless":
            await polling_coordinator.schedule_session_projection(
                session_id, self.client, headless_only=True, final_version=final_version
            )
        else:
            await polling_coordinator.schedule_session_projection(session_id, self.client, final_version=final_version)

    def _emit_activity_event(
        self,
        session_id: str,
        event_type: AgentHookEventType,
        tool_name: str | None = None,
        tool_preview: str | None = None,
        summary: str | None = None,
        message: str | None = None,
    ) -> None:
        """Emit agent activity event with error handling.

        Routes through the canonical contract (activity_contract.py) to produce
        canonical_type and routing metadata alongside the hook-level event_type.
        The hook event_type is always preserved for consumer compatibility.

        Args:
            session_id: Session identifier
            event_type: AgentHookEventType value
            tool_name: Optional tool name for pre_tool_use events
            tool_preview: Optional UI preview text for pre_tool_use events
            summary: Optional output summary (agent_stop only)
            message: Optional notification message (notification only)
        """
        try:
            timestamp = datetime.now(UTC).isoformat()
            canonical = serialize_activity_event(
                session_id=session_id,
                hook_event_type=event_type,
                timestamp=timestamp,
                tool_name=tool_name,
                tool_preview=tool_preview,
                summary=summary,
                message=message,
            )
            event_bus.emit(
                TeleClaudeEvents.AGENT_ACTIVITY,
                self._build_activity_event(
                    session_id=session_id,
                    event_type=event_type,
                    timestamp=timestamp,
                    tool_name=tool_name,
                    tool_preview=tool_preview,
                    summary=summary,
                    message=message,
                    canonical_type=canonical.canonical_type if canonical else None,
                    message_intent=canonical.message_intent if canonical else None,
                    delivery_scope=canonical.delivery_scope if canonical else None,
                ),
                visibility=EventVisibility.CLUSTER,
            )
        except Exception as exc:
            logger.error(
                "Failed to emit activity event: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id, "event_type": event_type},
            )

    @staticmethod
    def _build_activity_event(
        *,
        session_id: str,
        event_type: AgentHookEventType,
        timestamp: str,
        tool_name: str | None,
        tool_preview: str | None,
        summary: str | None,
        message: str | None,
        canonical_type: str | None,
        message_intent: str | None,
        delivery_scope: str | None,
    ) -> AgentActivityEvent:
        if event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
            return UserPromptSubmitActivityEvent(
                session_id=session_id,
                event_type=event_type,
                timestamp=timestamp,
                canonical_type=canonical_type,
                message_intent=message_intent,
                delivery_scope=delivery_scope,
            )
        if event_type == AgentHookEvents.PRE_TOOL_USE:
            return ToolUseActivityEvent(
                session_id=session_id,
                event_type=event_type,
                tool_name=tool_name,
                tool_preview=tool_preview,
                timestamp=timestamp,
                canonical_type=canonical_type,
                message_intent=message_intent,
                delivery_scope=delivery_scope,
            )
        if event_type == AgentHookEvents.AGENT_STOP:
            return AgentStopActivityEvent(
                session_id=session_id,
                event_type=event_type,
                summary=summary,
                message=message,
                timestamp=timestamp,
                canonical_type=canonical_type,
                message_intent=message_intent,
                delivery_scope=delivery_scope,
            )
        raise ValueError(f"Unsupported activity event_type: {event_type}")

    def _emit_status_event(
        self,
        session_id: str,
        status: str,
        reason: str,
        *,
        last_activity_at: str | None = None,
    ) -> bool:
        """Emit a canonical lifecycle status transition event.

        Routes through status_contract.serialize_status_event() for validation.
        Failures are logged but never crash the event flow (parallel to _emit_activity_event).

        Args:
            session_id: Session identifier.
            status: Target lifecycle status (must be a valid LifecycleStatus value).
            reason: Reason code for this transition.
            last_activity_at: ISO 8601 UTC timestamp of last known activity (optional).
        """
        # Idempotency suppresses redundant status emissions and their cache and
        # WebSocket broadcasts.
        if self._last_emitted_status.get(session_id) == status:
            return False
        try:
            timestamp = datetime.now(UTC).isoformat()
            canonical = serialize_status_event(
                session_id=session_id,
                status=status,
                reason=reason,
                timestamp=timestamp,
                last_activity_at=last_activity_at,
            )
            if canonical is None:
                return False
            self._last_emitted_status[session_id] = status
            event_bus.emit(
                TeleClaudeEvents.SESSION_STATUS,
                SessionStatusContext(
                    session_id=session_id,
                    status=status,
                    reason=reason,
                    timestamp=timestamp,
                    last_activity_at=last_activity_at,
                    message_intent=canonical.message_intent,
                    delivery_scope=canonical.delivery_scope,
                ),
                visibility=EventVisibility.CLUSTER,
            )
            logger.debug(
                "status transition: session=%s %s (reason=%s)",
                session_id,
                status,
                reason,
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to emit status event: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id, "status": status},
            )
            return False

    async def handle_event(self, context: AgentEventContext) -> None:
        """Handle any agent lifecycle event."""
        if context.event_type == AgentHookEvents.AGENT_SESSION_START:
            logger.info(
                _AGENT_SESSION_START_OBSERVED_EVENT,
                session_id=context.session_id,
                outcome=_AGENT_SESSION_START_OBSERVED_OUTCOME,
                reason=_AGENT_SESSION_START_NORMALIZED_HOOK_REASON,
            )
        if context.event_type == AgentHookEvents.AGENT_IDLE:
            await self.handle_agent_idle(context)
            return
        if context.event_type == AgentHookEvents.AGENT_SESSION_START:
            await self.handle_session_start(context)
        elif context.event_type == AgentHookEvents.AGENT_STOP:
            await self.handle_agent_stop(context)
        elif context.event_type == AgentHookEvents.AGENT_BLOCKED:
            await self.handle_agent_distress(context, NotificationKind.BLOCKED)
        elif context.event_type == AgentHookEvents.AGENT_NOTIFICATION:
            await self.handle_agent_distress(context, NotificationKind.NATIVE_NOTIFICATION)
        elif context.event_type == AgentHookEvents.AGENT_TURN_FAILED:
            await self.handle_agent_distress(context, NotificationKind.TURN_FAILED)
        elif context.event_type == AgentHookEvents.PRE_TOOL_USE:
            await self.handle_tool_use(context)
        elif context.event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
            await self.handle_user_prompt_submit(context)

    async def handle_agent_idle(self, context: AgentEventContext) -> None:
        """Record a provider-confirmed native command completion without finalizing output."""
        payload = cast(AgentIdlePayload, context.data)
        idle_at = datetime.now(UTC)
        await db.update_session(
            context.session_id,
            last_agent_idle_at=idle_at.isoformat(),
            last_activity=idle_at.isoformat(),
        )
        logger.info(
            _AGENT_IDLE_OBSERVED_EVENT,
            session_id=context.session_id,
            outcome=_AGENT_IDLE_OBSERVED_OUTCOME,
            reason=_AGENT_IDLE_MANUAL_NATIVE_COMMAND_REASON,
            native_session_id=payload.session_id,
        )

    async def handle_agent_distress(self, context: AgentEventContext, notification_kind: NotificationKind) -> None:
        """Notify watchers when a provider reports a blocked or failed turn.

        A failed turn also ends the turn: unlike a block (still running),
        it records an idle boundary before fan-out, mirroring
        ``handle_agent_idle``, so the session reads idle for the next
        control payload once no later input has arrived.
        """
        payload = cast(AgentDistressPayload, context.data)
        if notification_kind is NotificationKind.TURN_FAILED:
            idle_at = datetime.now(UTC)
            await db.update_session(
                context.session_id,
                last_agent_idle_at=idle_at.isoformat(),
                last_activity=idle_at.isoformat(),
            )
            logger.info(
                _AGENT_TURN_FAILED_OBSERVED_EVENT,
                session_id=context.session_id,
                outcome=_AGENT_TURN_FAILED_OBSERVED_OUTCOME,
                reason=_AGENT_TURN_FAILED_BOUNDARY_REASON,
            )
        await self._notify_session_distress(
            context.session_id,
            notification_kind,
            source_computer=payload.source_computer,
            observation=payload.observation,
        )

    async def handle_session_start(self, context: AgentEventContext) -> None:
        """Handle session_start event - store native session details and update title if needed."""
        payload = cast(AgentSessionStartPayload, context.data)
        native_session_id = payload.session_id
        native_log_file = payload.transcript_path
        raw_cwd = payload.raw.get("cwd")

        update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        if native_session_id:
            update_kwargs["native_session_id"] = str(native_session_id)
        if native_log_file:
            update_kwargs["native_log_file"] = str(native_log_file)

        session = await db.get_session(context.session_id)

        if isinstance(raw_cwd, str) and raw_cwd:
            if session and not session.project_path:
                update_kwargs["project_path"] = raw_cwd
                update_kwargs["subdir"] = None
        if update_kwargs:
            await db.update_session(context.session_id, **update_kwargs)

        # A headless session has no adoption boundary to cross into ACTIVE;
        # runtime start stays observable through session data, not status.
        if not session or session.lifecycle_status != SessionLifecycleStatus.HEADLESS:
            await transition_session(
                db,
                context.session_id,
                LifecycleTransition(
                    SessionLifecycleStatus.ACTIVE,
                    LifecycleTransitionReason.RUNTIME_SESSION_START,
                    runtime_start_observed=True,
                    runtime_activity_at=datetime.now(UTC),
                ),
            )

        voice = await db.get_voice(context.session_id)
        if voice:
            await db.assign_voice(context.session_id, voice)
            logger.debug(
                "Reaffirmed voice from service '%s' for teleclaude_session_id %s",
                voice.service_name,
                context.session_id,
            )

        logger.info(
            "Stored Agent session data: teleclaude=%s, native=%s",
            context.session_id,
            str(native_session_id),
        )

        # Normalized runtime start is an observed lifecycle fact. Consumers with
        # native startup authority subscribe to AGENT_READY here.
        event_bus.emit(
            TeleClaudeEvents.AGENT_READY,
            SessionLifecycleContext(session_id=context.session_id),
            visibility=EventVisibility.LOCAL,
        )

        # Headless state flows through session data, not status events.
        if not session or session.lifecycle_status != "headless":
            transition_emitted = self._emit_status_event(
                context.session_id,
                _AGENT_SESSION_LIFECYCLE_STATUS,
                _AGENT_SESSION_LIFECYCLE_TRANSITION_REASON,
            )
            if transition_emitted:
                logger.info(
                    _AGENT_SESSION_LIFECYCLE_TRANSITION_EVENT,
                    session_id=context.session_id,
                    outcome=_AGENT_SESSION_LIFECYCLE_TRANSITION_OUTCOME,
                    reason=_AGENT_SESSION_LIFECYCLE_TRANSITION_REASON,
                )

        # Speak only on the first normalized session_start for this session.
        # TTS is scheduled (debounced, cancelable) so it never blocks the
        # AGENT_READY emit above or any subsequent event on this session.
        already_started_before = bool(session and session.native_session_id)
        if not already_started_before:
            schedule_slow_work(
                session_id=context.session_id,
                event_type=AgentHookEvents.AGENT_SESSION_START,
                runner=lambda: self._speak_session_start(context.session_id),
            )

    async def _backfill_prompt_from_transcript(self, session: object) -> str | None:
        """Recover the last user message from the transcript.

        Agent-agnostic: used when a CLI's hook payload omits the prompt body
        (the field name and transcript schema are resolved at the bottom of the
        stack by the per-agent extractor). Returns None when no transcript is
        bound yet or no user text is present.
        """
        transcript_path = getattr(session, "native_log_file", None)
        active_agent = getattr(session, "active_agent", None)
        if not transcript_path or not active_agent:
            return None
        try:
            agent_name = AgentName.from_str(active_agent)
        except ValueError:
            return None
        extracted = await asyncio.to_thread(extract_last_user_message_with_timestamp, transcript_path, agent_name)
        if not extracted:
            return None
        text = extracted[0]
        return text or None

    async def handle_user_prompt_submit(self, context: AgentEventContext) -> None:
        """Handle user prompt submission.

        Hook payloads are a signal only. Canonical prompt content, ordering,
        and title derivation come from transcript projection.
        """
        session_id = context.session_id
        payload = cast(UserPromptSubmitPayload, context.data)

        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for user_prompt_submit", session_id)
            return

        prompt_text = payload.prompt or ""
        if not prompt_text.strip():
            # Some CLIs (e.g. agy) carry no prompt in the hook payload — the
            # canonical text lives in the transcript. Backfill agent-agnostically.
            prompt_text = await self._backfill_prompt_from_transcript(session) or ""
        if not prompt_text.strip():
            # Transcript not flushed yet; let the projection cadence reflect it.
            logger.debug("No prompt text available yet for session %s; deferring to projection", session_id)
            if session.lifecycle_status == "headless":
                await polling_coordinator.schedule_session_projection(session_id, self.client, headless_only=True)
            else:
                await polling_coordinator.schedule_session_projection(session_id, self.client)
            return

        # System-injected checkpoint — not real user input, skip entirely
        if _is_checkpoint_prompt(prompt_text, raw_payload=payload.raw):
            logger.debug("Checkpoint prompt detected, skipping user input persistence for session %s", session_id)
            return

        # A real prompt starts a new turn and re-opens all notification outcomes.
        await db.clear_turn_notifications(session_id)
        logger.info("turn_notification_gate_cleared", session_id=session_id)

        # Snapshot HEAD as the turn-start anchor for scoped path resolution.
        # Captured here because user_prompt_submit is the canonical turn boundary:
        # any commit after this point belongs to the new turn.
        anchor_sha: str | None = None
        if session.project_path:
            anchor_sha = await asyncio.to_thread(read_head_sha, session.project_path)

        # Clear checkpoint state on real user input; record the new turn anchor.
        await db.update_session(
            session_id,
            last_checkpoint_at=None,
            last_tool_use_at=None,
            turn_anchor_sha=anchor_sha,
        )

        update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates

        # Terminal input bypasses command acceptance handlers, so the prompt
        # hook is the turn-origin signal. If a UI adapter already recorded a
        # fresh matching acceptance for this prompt, preserve it.
        fresh_origin = await db.get_session(session_id)
        current_origin = (fresh_origin.last_input_origin if fresh_origin else session.last_input_origin) or ""
        has_fresh_ui_origin = (
            bool(fresh_origin)
            and current_origin != InputOrigin.TERMINAL.value
            and polling_coordinator.has_fresh_origin_for_user(fresh_origin, prompt_text)
        )
        terminal_origin_recorded = not has_fresh_ui_origin
        if terminal_origin_recorded:
            update_kwargs["last_input_origin"] = InputOrigin.TERMINAL.value
            update_kwargs["last_message_sent"] = prompt_text[:200]
            update_kwargs["last_message_sent_at"] = datetime.now(UTC).isoformat()

        if update_kwargs:
            await db.update_session(session_id, **update_kwargs)
        current = await db.get_session(session_id)
        if current and current.runtime_start_observed:
            await db.update_session(session_id, runtime_activity_at=datetime.now(UTC))
        await db.update_last_activity(session_id)
        if session.lifecycle_status == "headless":
            await polling_coordinator.schedule_session_projection(session_id, self.client, headless_only=True)
        else:
            await polling_coordinator.schedule_session_projection(session_id, self.client)
        logger.debug(
            "Recorded user input via hook for session %s: %s...",
            session_id,
            prompt_text[:50],
        )

        # Emit activity event for all sessions
        self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)

        if session.lifecycle_status != "headless" and terminal_origin_recorded:
            now_ts = datetime.now(UTC).isoformat()
            self._emit_status_event(session_id, "accepted", "user_prompt_accepted", last_activity_at=now_ts)

    async def handle_agent_stop(self, context: AgentEventContext) -> None:
        """Handle stop event - Agent session stopped.

        Fast path only: row mutations, status/activity emit (without summary),
        projection signal, and stop finalize. The slow summary/title/TTS chain
        is scheduled via ``_slow_work`` so it never blocks the per-session
        FIFO drain and gets superseded on the next agent_stop for this
        session.
        """
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        source_computer = payload.source_computer

        if payload.completion_source is AgentStopCompletionSource.CODEX_TASK_RECOVERY:
            decision = decide_codex_stop_recovery(await db.get_session(session_id), payload)
            if not decision.accepted:
                logger.info(
                    _AGENT_STOP_RECOVERY_DECIDED_EVENT,
                    session_id=session_id,
                    native_session_id=payload.session_id,
                    native_turn_id=payload.native_turn_id,
                    outcome="rejected",
                    reason=decision.reason.value,
                    native_completed_at=(
                        payload.native_completed_at.isoformat() if payload.native_completed_at else None
                    ),
                    accepted_input_at=(payload.accepted_input_at.isoformat() if payload.accepted_input_at else None),
                )
                return

        logger.debug(
            "Agent stop event for session %s (title: %s)",
            session_id,
            "db",
        )

        stop_at = datetime.now(UTC)
        stop_timestamp = stop_at.isoformat()
        output_result = await self._prepare_agent_stop_output(session_id, payload)

        # One durable transition: the stop version, the payload belonging to it,
        # the cleared summary, and every lane enrolled to recover that payload.
        # A payload with no enrolled lane is unrecoverable; an enrolment with no
        # payload replays the prior turn. Extraction reads the transcript and
        # writes nothing, so it is safe to run before this write.
        routing_session = await db.get_session(session_id)
        owed_lanes = (
            self.client.resolve_final_output_lanes(routing_session)
            if routing_session is not None and output_result.has_substantive_output
            else []
        )
        await db.stage_agent_stop(
            session_id,
            stop_at=stop_at,
            raw_output=output_result.raw_output,
            output_disposition=output_result.disposition,
            owed_lanes=owed_lanes,
            known_ui_lanes=self.client.canonical_ui_lanes(),
        )
        if self.reminder_service is not None:
            await self.reminder_service.handle_agent_event(
                ReminderEvent(
                    session_id=context.session_id,
                    event_id=f"{context.event_type}:{stop_timestamp}",
                    anchor=ReminderEventAnchor.AGENT_STOP,
                )
            )

        # Activity event without summary; the slow runner re-emits with the
        # computed summary once it lands.
        self._emit_activity_event(session_id, AgentHookEvents.AGENT_STOP, summary=None)

        # Emit canonical lifecycle status: completed (R2)
        self._emit_status_event(session_id, "completed", "agent_turn_complete", last_activity_at=stop_timestamp)

        # Immediate projection pull on stop — final output must be captured.
        await self._signal_projection_activity(
            session_id,
            final_version=stop_at if output_result.has_substantive_output else None,
        )

        await self._finalize_agent_stop(
            session_id,
            payload,
            source_computer,
            suppress_notifications=output_result.is_suppressed,
            output_version=(stop_timestamp if output_result.has_substantive_output else None),
        )

        if not output_result.is_suppressed:
            schedule_slow_work(
                session_id=session_id,
                event_type=AgentHookEvents.AGENT_STOP,
                runner=lambda: self._run_agent_stop_slow_work(session_id, payload, stop_at, output_result),
            )

    async def _prepare_agent_stop_output(self, session_id: str, payload: AgentStopPayload) -> StopOutputResult:
        """Fast extraction step shared by handler and slow runner.

        Reads the transcript, applies ANSI stripping, and returns the typed
        output result. No LLM, no TTS, no DB writes.
        """
        payload_output_raw = payload.raw.get(_HOOK_MESSAGE_KEY)
        if isinstance(payload_output_raw, str):
            payload_output = strip_ansi_codes(payload_output_raw) if config.terminal.strip_ansi else payload_output_raw
            result = classify_stop_output(payload_output)
            if result.is_suppressed:
                self._log_bare_noop_suppression(session_id)
                return result

        result = await self._extract_agent_output(session_id, payload)
        if result.raw_output is not None and config.terminal.strip_ansi:
            result = classify_stop_output(strip_ansi_codes(result.raw_output))
        if result.is_suppressed:
            self._log_bare_noop_suppression(session_id)
        return result

    def _log_bare_noop_suppression(self, session_id: str) -> None:
        """Record one body-free structural suppression decision."""
        logger.info(
            _AGENT_STOP_OUTPUT_SUPPRESSED_EVENT,
            session_id=session_id,
            outcome=_AGENT_STOP_OUTPUT_SUPPRESSED_OUTCOME,
            reason=_AGENT_STOP_OUTPUT_BARE_NOOP_REASON,
        )

    async def _run_agent_stop_slow_work(
        self,
        session_id: str,
        payload: AgentStopPayload,
        stop_at: datetime,
        output_result_initial: StopOutputResult,
    ) -> None:
        """Composite slow runner scheduled by ``handle_agent_stop``.

        Summarizes the raw output, persists feedback fields, re-emits the
        activity event carrying the summary, speaks the summary via TTS,
        and generates a session title. Cancelled when a new ``agent_stop``
        arrives for the same session; ``CancelledError`` propagates
        through the LLM/TTS awaits.

        If the synchronous extract in the fast path missed (transcript not
        flushed yet — codex's typical pattern), waits up to 10 s for the
        assistant message to appear before re-extracting, then proceeds
        through the rest of the chain. Title generation runs against the
        now-ready file too, so it benefits from the same wait.
        """
        output_result = output_result_initial
        if output_result.kind is StopOutputKind.UNAVAILABLE:
            session = await db.get_session(session_id)
            if session is not None:
                try:
                    active_agent = AgentName.from_str(session.active_agent) if session.active_agent else None
                except ValueError:
                    active_agent = None
                native_entry_id = payload.native_turn_id
                ready = await wait_for_transcript_ready(
                    session,
                    content_predicate=(
                        lambda entries: (
                            transcript_has_stop_response(
                                entries,
                                active_agent,
                                native_entry_id=native_entry_id,
                            )
                            if active_agent is not None
                            else False
                        )
                    ),
                )
                if ready:
                    output_result = await self._prepare_agent_stop_output(session_id, payload)
                    if output_result.kind is not StopOutputKind.UNAVAILABLE:
                        # Stage the recovered payload against the stop version
                        # already persisted, then re-signal projection. The fast
                        # path signalled while the transcript was still empty, so
                        # without this the turn is never delivered live and
                        # recovery has nothing to replay until summarization ends
                        # — which is the slowest step in the chain. The output is
                        # stamped with that persisted stop version rather than the
                        # wall time this late extraction happened to land, so both
                        # writes describe the same turn.
                        # Same staging operation as the fast path, against the
                        # stop version already persisted. The fast path could not
                        # enrol: it had no payload to be owed yet.
                        accepted = await db.stage_agent_stop(
                            session_id,
                            stop_at=stop_at,
                            raw_output=output_result.raw_output,
                            output_disposition=output_result.disposition,
                            owed_lanes=(
                                self.client.resolve_final_output_lanes(session)
                                if output_result.has_substantive_output
                                else []
                            ),
                            known_ui_lanes=self.client.canonical_ui_lanes(),
                            expected_stop_at=stop_at,
                        )
                        if not accepted:
                            return
                        if output_result.has_substantive_output:
                            await self._signal_projection_activity(session_id, final_version=stop_at)

        if output_result.has_substantive_output and output_result.raw_output is not None:
            summary = await self._summarize_output(session_id, output_result.raw_output)
            # Persist raw output regardless of summary success — the fallback
            # display path uses raw_output when summary is absent, so dropping
            # it on summarizer failure regresses output visibility. Write
            # last_output_summary unconditionally (None when summarize
            # failed) so a stale summary from a prior turn cannot bleed
            # into this turn's display.
            accepted = await db.persist_agent_stop_summary(
                session_id,
                stop_at=stop_at,
                raw_output=output_result.raw_output,
                summary=summary,
                summary_at=datetime.now(UTC),
            )
            if not accepted:
                return
            logger.debug(
                "Stored agent output: session=%s raw_len=%d summary_len=%d",
                session_id,
                len(output_result.raw_output),
                len(summary) if summary else 0,
            )
            # TUI summary emit + TTS gate on summary content only — empty
            # summary surfaces should not paint stale or blank state on the
            # downstream UI lanes.
            if summary:
                self._emit_activity_event(session_id, AgentHookEvents.AGENT_STOP, summary=summary)
                await self._speak_agent_stop_summary(session_id, summary)

        session = await db.get_session(session_id)
        if session:
            await generate_session_title_from_transcript(session, self.client)

    async def _speak_agent_stop_summary(self, session_id: str, summary: str | None) -> None:
        """Emit stop-summary TTS when a non-empty summary exists."""
        if not summary:
            return
        try:
            await self.tts_manager.speak(summary, session_id=session_id)
        except Exception as exc:
            logger.warning("TTS agent_stop failed: %s", exc, extra={"session_id": session_id})

    async def _finalize_agent_stop(
        self,
        session_id: str,
        payload: AgentStopPayload,
        source_computer: str | None,
        *,
        suppress_notifications: bool,
        output_version: str | None,
    ) -> None:
        """Complete stop fan-out, listener notification, and forwarding."""
        schedule_debounced_delivery(
            session_id,
            client=self.client,
            command_service=get_command_service(),
            source_computer=source_computer,
        )

        if suppress_notifications:
            return

        title_raw = payload.raw.get("title")
        title = title_raw if isinstance(title_raw, str) and title_raw else None
        await self._notify_session_listener(session_id, source_computer=source_computer, title_override=title)

        if output_version is not None:
            publication = await self.client.notify_session_observed_stop(session_id, output_version)
            if publication.published:
                logger.info(_SESSION_OBSERVED_STOP_SENT_EVENT, session_id=session_id, observer=publication.observer)

        if not (source_computer and source_computer != config.computer.name):
            await self._forward_stop_to_initiator(session_id)

    async def handle_tool_use(self, context: AgentEventContext) -> None:
        """Handle pre_tool_use event — agent started a tool call.

        Only records the FIRST pre_tool_use per turn (when last_tool_use_at is NULL).
        Cleared by handle_user_prompt_submit when a new turn begins.
        """
        session_id = context.session_id
        payload = cast(AgentOutputPayload, context.data)

        tool_name = extract_tool_name(payload.raw)
        tool_preview = build_tool_preview(tool_name=tool_name, raw_payload=payload.raw)

        # Always emit activity event for UI updates (every tool call)
        self._emit_activity_event(
            session_id,
            AgentHookEvents.PRE_TOOL_USE,
            tool_name,
            tool_preview=tool_preview,
        )

        # Output evidence observed → active_output
        now_ts = datetime.now(UTC).isoformat()
        self._emit_status_event(session_id, "active_output", "output_observed", last_activity_at=now_ts)

        # DB write is deduped: only record the FIRST pre_tool_use per turn for checkpoint timing
        session = await db.get_session(session_id)
        if session and not session.last_tool_use_at:
            now = datetime.now(UTC)
            await db.update_session(session_id, last_tool_use_at=now.isoformat())
            logger.debug("pre_tool_use recorded for session %s", session_id)

        # Tool hooks are liveness signals; projection remains transcript-driven.
        await self._signal_projection_activity(session_id)
