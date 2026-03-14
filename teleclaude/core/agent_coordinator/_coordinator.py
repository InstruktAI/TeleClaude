"""Core AgentCoordinator class composing incremental-output and fanout mixins."""

import asyncio
import inspect
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core.activity_contract import serialize_activity_event
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentEventContext,
    AgentHookEvents,
    AgentOutputPayload,
    AgentSessionEndPayload,
    AgentSessionStartPayload,
    AgentStopPayload,
    SessionStatusContext,
    TeleClaudeEvents,
    UserPromptSubmitPayload,
)
from teleclaude.core.feature_flags import is_threaded_output_enabled
from teleclaude.core.origins import InputOrigin
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.core.tool_activity import build_tool_preview, extract_tool_name
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService
from teleclaude.tts.manager import TTSManager
from teleclaude.utils import strip_ansi_codes

from ._fanout import _FanoutMixin
from ._helpers import (
    _is_checkpoint_prompt,
    _is_codex_input_already_recorded,
    _is_codex_synthetic_prompt_event,
    _resolve_hook_actor_name,
    _SuppressionState,
)
from ._incremental import _IncrementalOutputMixin

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class AgentCoordinator(_IncrementalOutputMixin, _FanoutMixin):
    """Coordinator for agent events and inter-agent communication."""

    def __init__(
        self,
        client: "AdapterClient",
        tts_manager: TTSManager,
        headless_snapshot_service: HeadlessSnapshotService,
    ) -> None:
        self.client = client
        self.tts_manager = tts_manager
        self.headless_snapshot_service = headless_snapshot_service
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._incremental_noop_state: dict[str, _SuppressionState] = {}
        self._tool_use_skip_state: dict[str, _SuppressionState] = {}
        self._incremental_eval_state: dict[str, tuple[str, bool]] = {}
        # Upstream render bookkeeping for incremental threaded output.
        # Stores digest of the full rendered message (not adapter chunk digests).
        self._incremental_render_digests: dict[str, str] = {}
        # Serialize incremental rendering/sending per session to avoid
        # concurrent poll/hook races emitting the same payload twice.
        self._incremental_output_locks: dict[str, asyncio.Lock] = {}
        # Track last emitted lifecycle status per session for guard checks.
        self._last_emitted_status: dict[str, str] = {}

    def _queue_background_task(
        self,
        coro: Coroutine[object, object, object],
        label: str,
    ) -> None:
        """Run non-critical work without blocking hook event handling."""
        task = asyncio.create_task(coro)
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
                            {"message": f"Failed to update session title: {exc}", "severity": "warning"},  # type: ignore[arg-type]
                        )
                    except Exception:
                        pass

        task.add_done_callback(_on_done)

    def _emit_activity_event(
        self,
        session_id: str,
        event_type: str,
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
            tool_name: Optional tool name for tool_use events
            tool_preview: Optional UI preview text for tool_use events
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
                AgentActivityEvent(
                    session_id=session_id,
                    event_type=event_type,  # type: ignore[arg-type]
                    tool_name=tool_name,
                    tool_preview=tool_preview,
                    summary=summary,
                    message=message,
                    timestamp=timestamp,
                    canonical_type=canonical.canonical_type if canonical else None,
                    message_intent=canonical.message_intent if canonical else None,
                    delivery_scope=canonical.delivery_scope if canonical else None,
                ),
            )
        except Exception as exc:
            logger.error(
                "Failed to emit activity event: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id, "event_type": event_type},
            )

    def _emit_status_event(
        self,
        session_id: str,
        status: str,
        reason: str,
        *,
        last_activity_at: str | None = None,
    ) -> None:
        """Emit a canonical lifecycle status transition event.

        Routes through status_contract.serialize_status_event() for validation.
        Failures are logged but never crash the event flow (parallel to _emit_activity_event).

        Args:
            session_id: Session identifier.
            status: Target lifecycle status (must be a valid LifecycleStatus value).
            reason: Reason code for this transition.
            last_activity_at: ISO 8601 UTC timestamp of last known activity (optional).
        """
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
                return
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
            )
            logger.debug(
                "status transition: session=%s %s (reason=%s)",
                session_id,
                status,
                reason,
            )
        except Exception as exc:
            logger.error(
                "Failed to emit status event: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id, "status": status},
            )

    async def handle_event(self, context: AgentEventContext) -> None:
        """Handle any agent lifecycle event."""
        if context.event_type == AgentHookEvents.AGENT_SESSION_START:
            await self.handle_session_start(context)
        elif context.event_type == AgentHookEvents.AGENT_STOP:
            await self.handle_agent_stop(context)
        elif context.event_type == AgentHookEvents.TOOL_DONE:
            await self.handle_tool_done(context)
        elif context.event_type == AgentHookEvents.TOOL_USE:
            await self.handle_tool_use(context)
        elif context.event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
            await self.handle_user_prompt_submit(context)
        elif context.event_type == AgentHookEvents.AGENT_SESSION_END:
            await self.handle_session_end(context)

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

        # Headless state flows through session data, not status events.
        if not session or session.lifecycle_status != "headless":
            self._emit_status_event(context.session_id, "active", "agent_session_started")

        await self._maybe_send_headless_snapshot(context.session_id)
        await self._speak_session_start(context.session_id)

    async def handle_user_prompt_submit(self, context: AgentEventContext) -> None:
        """Handle user prompt submission.

        For ALL sessions: write last_message_sent to DB (captures direct terminal input).
        Refresh title from the latest accepted real user input.
        For headless sessions: broadcast to adapters for display without tmux adoption.
        """
        session_id = context.session_id
        payload = cast(UserPromptSubmitPayload, context.data)

        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for user_prompt_submit", session_id)
            return

        prompt_text = payload.prompt or ""
        if not prompt_text.strip():
            logger.debug("Empty prompt detected, skipping user input persistence for session %s", session_id)
            return

        is_codex_synthetic = _is_codex_synthetic_prompt_event(payload.raw)
        # System-injected checkpoint — not real user input, skip entirely
        if _is_checkpoint_prompt(prompt_text, raw_payload=payload.raw):
            logger.debug("Checkpoint prompt detected, skipping user input persistence for session %s", session_id)
            return

        # Clear notification flag when new prompt starts (all sessions)
        await db.set_notification_flag(session_id, False)

        # Clear checkpoint state on real user input
        await db.update_session(session_id, last_checkpoint_at=None, last_tool_use_at=None)
        # NOTE: Do NOT clear _incremental_render_digests here. The poller may
        # fire between this point and the first new assistant content. Clearing
        # the digest opens a window where stale content from the previous turn
        # is re-rendered and sent as a duplicate (no digest to compare against).
        # The digest is naturally replaced when new assistant content arrives
        # and produces a different hash.

        # Prepare batched update
        now = datetime.now(UTC)
        should_update_last_message = True
        if is_codex_synthetic:
            existing_input = (session.last_message_sent or "").strip()
            incoming_input = prompt_text.strip()
            existing_at = session.last_message_sent_at
            recent_existing = isinstance(existing_at, datetime) and (now - existing_at).total_seconds() <= 300
            if (
                recent_existing
                and existing_input
                and incoming_input
                and len(existing_input) > len(incoming_input)
                and existing_input.startswith(incoming_input)
            ):
                should_update_last_message = False
                logger.debug(
                    "Skipping synthetic Codex prompt overwrite for session %s (existing=%r incoming=%r)",
                    session_id,
                    existing_input[:50],
                    incoming_input[:50],
                )

        incoming_input = prompt_text.strip()
        existing_input = (session.last_message_sent or "").strip()
        existing_origin = (session.last_input_origin or "").strip().lower()
        existing_at = session.last_message_sent_at
        # deliver_inbound truncates last_message_sent to 200 chars; compare at that
        # boundary so the echo guard still fires for long messages.
        _CMP_LEN = 200
        is_recent_routed_echo = (
            session.lifecycle_status != "headless"
            and not is_codex_synthetic
            and existing_origin
            and existing_origin != InputOrigin.TERMINAL.value
            and isinstance(existing_at, datetime)
            and (now - existing_at).total_seconds() <= 20
            and existing_input
            and incoming_input
            and existing_input[:_CMP_LEN] == incoming_input[:_CMP_LEN]
        )
        if not is_recent_routed_echo and existing_origin and existing_origin != InputOrigin.TERMINAL.value:
            logger.debug(
                "Echo guard miss for session %s: origin=%s age=%.1fs text_match=%s existing=%r incoming=%r",
                session_id,
                existing_origin,
                (now - existing_at).total_seconds() if isinstance(existing_at, datetime) else -1,
                existing_input[:50] == incoming_input[:50] if existing_input and incoming_input else "N/A",
                existing_input[:50] if existing_input else None,
                incoming_input[:50],
            )
        if is_recent_routed_echo:
            should_update_last_message = False
            logger.debug(
                "Skipping duplicate hook prompt persistence for session %s (origin=%s)",
                session_id,
                existing_origin,
            )

        update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        if should_update_last_message:
            update_kwargs.update(
                {
                    "last_message_sent": prompt_text[:200],
                    "last_message_sent_at": now.isoformat(),
                    "last_input_origin": InputOrigin.TERMINAL.value,
                }
            )

        # Track what triggered this turn for echo suppression in handle_agent_stop.
        # Set unconditionally — deliver_inbound's eager writes must not control this.
        _linked_prefix_check = f"{TELECLAUDE_SYSTEM_PREFIX} Linked output from "
        update_kwargs["turn_triggered_by_linked_output"] = prompt_text.strip().startswith(_linked_prefix_check)

        # Single DB update for all fields
        await db.update_session(session_id, **update_kwargs)
        logger.debug(
            "Recorded user input via hook for session %s: %s...",
            session_id,
            prompt_text[:50],
        )

        # Title update is non-critical and must not block hook ordering.
        # Only schedule when this submit became the canonical persisted input.
        if should_update_last_message:
            self._queue_background_task(
                self._update_session_title_async(session_id, now, prompt_text),
                f"title-summary:{session_id}",
            )

        # Reset threaded output state on user input.
        # This seals the previous agent output block, ensuring the next response
        # starts a fresh message (append-only flow).
        if is_threaded_output_enabled(session.active_agent):
            await self.client.break_threaded_turn(session)

        # Emit activity event for all sessions
        self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)

        hook_actor_name = _resolve_hook_actor_name(session)

        if session.lifecycle_status != "headless":
            # Emit canonical lifecycle status: accepted (R2)
            now_ts = datetime.now(UTC).isoformat()
            self._emit_status_event(session_id, "accepted", "user_prompt_accepted", last_activity_at=now_ts)

            if is_recent_routed_echo:
                logger.debug(
                    "Skipping duplicate non-headless hook reflection for session %s",
                    session_id,
                )
                return
            broadcast_result = self.client.broadcast_user_input(
                session,
                prompt_text,
                InputOrigin.TERMINAL.value,
                actor_id=f"terminal:{config.computer.name}:{session_id}",
                actor_name=hook_actor_name,
            )
            if inspect.isawaitable(broadcast_result):
                await broadcast_result
            return

        # Headless: broadcast to adapters for display, no tmux adoption.
        broadcast_result = self.client.broadcast_user_input(
            session,
            prompt_text,
            InputOrigin.TERMINAL.value,
            actor_id=f"terminal:{config.computer.name}:{session_id}",
            actor_name=hook_actor_name,
        )
        if inspect.isawaitable(broadcast_result):
            await broadcast_result

    async def handle_agent_stop(self, context: AgentEventContext) -> None:
        """Handle stop event - Agent session stopped."""
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        source_computer = payload.source_computer

        # Fetch session early for logic checks
        session = await db.get_session(session_id)

        logger.debug(
            "Agent stop event for session %s (title: %s)",
            session_id,
            "db",
        )

        await self._record_agent_stop_input(session_id, payload, session)
        link_output, summary = await self._record_agent_stop_output(session_id, payload)

        # Emit activity event for UI updates (summary flows to TUI via event, not DB)
        self._emit_activity_event(session_id, AgentHookEvents.AGENT_STOP, summary=summary)

        # Emit canonical lifecycle status: completed (R2)
        now_ts = datetime.now(UTC).isoformat()
        self._emit_status_event(session_id, "completed", "agent_turn_complete", last_activity_at=now_ts)

        # 2. Incremental threaded output (final turn portion)
        await self._maybe_send_incremental_output(session_id, payload)

        # Clear threaded output state for this turn (only for threaded sessions).
        # Non-threaded sessions rely on the poller's output_message_id for in-place edits.
        # NOTE: Do NOT clear _incremental_render_digests here. The poller may
        # fire one more OutputChanged tick after this point; keeping the digest
        # lets the deduplication check prevent a duplicate message send.
        # The digest is naturally invalidated on the next user turn when new
        # assistant content changes the hash.
        session = await db.get_session(session_id)  # Refresh to get latest metadata
        if session and is_threaded_output_enabled(session.active_agent):
            await self.client.break_threaded_turn(session)

        # Clear turn-specific cursor at turn completion
        await db.update_session(session_id, last_tool_done_at=None)
        await self._finalize_agent_stop(session_id, session, payload, link_output, source_computer)

    async def _record_agent_stop_input(
        self,
        session_id: str,
        payload: AgentStopPayload,
        session: "Session | None",
    ) -> None:
        """Backfill missing Codex input metadata and user prompt events."""
        input_update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        recovered_input_text: str | None = None

        codex_input = await self._extract_user_input_for_codex(session_id, payload)
        if isinstance(codex_input, tuple) and len(codex_input) == 2:
            input_text, input_timestamp = codex_input
            input_update_kwargs["last_message_sent"] = input_text[:200]
            if input_timestamp:
                input_update_kwargs["last_message_sent_at"] = input_timestamp.isoformat()
            if input_text.strip() and not _is_codex_input_already_recorded(session, input_text):
                recovered_input_text = input_text
        elif codex_input:
            logger.debug("Ignoring malformed codex input tuple for session %s", session_id)

        if input_update_kwargs:
            await db.update_session(session_id, **input_update_kwargs)
        if recovered_input_text is None:
            return

        logger.info("Backfilling missing user_prompt_submit from codex agent_stop for session %s", session_id)
        self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)
        if session and session.lifecycle_status != "headless":
            hook_actor_name = _resolve_hook_actor_name(session)
            await self.client.broadcast_user_input(
                session,
                recovered_input_text,
                InputOrigin.TERMINAL.value,
                actor_id=f"terminal:{config.computer.name}:{session_id}",
                actor_name=hook_actor_name,
            )

    async def _record_agent_stop_output(
        self, session_id: str, payload: AgentStopPayload
    ) -> tuple[str | None, str | None]:
        """Persist stop output, summary, and optional TTS feedback."""
        feedback_update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        raw_output = await self._extract_agent_output(session_id, payload)
        forwarded_output_raw = payload.raw.get("linked_output")
        forwarded_output = forwarded_output_raw if isinstance(forwarded_output_raw, str) else None
        link_output = raw_output or forwarded_output

        if raw_output:
            if config.terminal.strip_ansi:
                raw_output = strip_ansi_codes(raw_output)
            if not raw_output.strip():
                logger.debug("Skip stop summary/TTS (agent output empty after normalization)", session=session_id)
                raw_output = None
                link_output = None
            else:
                link_output = raw_output
        if payload.prompt and _is_checkpoint_prompt(payload.prompt, raw_payload=payload.raw):
            link_output = None

        summary: str | None = None
        if raw_output:
            summary = await self._summarize_output(session_id, raw_output)
            feedback_update_kwargs.update(
                {
                    "last_output_raw": raw_output,
                    "last_output_summary": summary,
                    "last_output_at": datetime.now(UTC).isoformat(),
                }
            )
            logger.debug(
                "Stored agent output: session=%s raw_len=%d summary_len=%d",
                session_id,
                len(raw_output),
                len(summary) if summary else 0,
            )
            await self._speak_agent_stop_summary(session_id, summary)

        if feedback_update_kwargs:
            await db.update_session(session_id, **feedback_update_kwargs)
        return link_output, summary

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
        session: "Session | None",
        payload: AgentStopPayload,
        link_output: str | None,
        source_computer: str | None,
    ) -> None:
        """Complete stop fan-out, listener notification, forwarding, and checkpoint injection."""
        is_linked_echo = session is not None and session.turn_triggered_by_linked_output
        if is_linked_echo:
            logger.debug("Suppressing linked fan-out for session %s (turn triggered by linked output)", session_id)
        if link_output and link_output.strip() and not is_linked_echo:
            await self._fanout_linked_stop_output(session_id, link_output, source_computer=source_computer)

        if session is not None and session.turn_triggered_by_linked_output:
            await db.update_session(session_id, turn_triggered_by_linked_output=False)

        title_raw = payload.raw.get("title")
        title = title_raw if isinstance(title_raw, str) and title_raw else None
        await self._notify_session_listener(session_id, source_computer=source_computer, title_override=title)

        if not (source_computer and source_computer != config.computer.name):
            await self._forward_stop_to_initiator(session_id, link_output)

        await self._maybe_inject_checkpoint(session_id, session)

    async def handle_tool_use(self, context: AgentEventContext) -> None:
        """Handle tool_use event — agent started a tool call.

        Only records the FIRST tool_use per turn (when last_tool_use_at is NULL).
        This gives _maybe_inject_checkpoint the true turn start time, not the last tool call.
        Cleared by handle_user_prompt_submit when a new turn begins.
        """
        session_id = context.session_id
        payload = cast(AgentOutputPayload, context.data)

        tool_name = extract_tool_name(payload.raw)
        tool_preview = build_tool_preview(tool_name=tool_name, raw_payload=payload.raw)

        # Always emit activity event for UI updates (every tool call)
        self._emit_activity_event(
            session_id,
            AgentHookEvents.TOOL_USE,
            tool_name,
            tool_preview=tool_preview,
        )

        # Output evidence observed → active_output
        now_ts = datetime.now(UTC).isoformat()
        self._emit_status_event(session_id, "active_output", "output_observed", last_activity_at=now_ts)

        # DB write is deduped: only record the FIRST tool_use per turn for checkpoint timing
        session = await db.get_session(session_id)
        if session and session.last_tool_use_at:
            self._mark_tool_use_skip(session_id)
        elif session:
            self._clear_tool_use_skip(session_id)
            now = datetime.now(UTC)
            await db.update_session(session_id, last_tool_use_at=now.isoformat())
            logger.debug("tool_use recorded for session %s", session_id)

        # Output fanout is transcript-driven from polling; hooks stay control-plane only.
        # tool_use still emits activity + checkpoint timing metadata.

    async def handle_tool_done(self, context: AgentEventContext) -> None:
        """Handle tool_done event — tool execution completed, output available."""
        session_id = context.session_id

        # Emit activity event for UI updates
        self._emit_activity_event(session_id, AgentHookEvents.TOOL_DONE)

    async def handle_session_end(self, context: AgentEventContext) -> None:
        """Handle session_end event - agent session ended."""
        _payload = cast(AgentSessionEndPayload, context.data)
        logger.info("Agent %s for session %s", AgentHookEvents.AGENT_SESSION_END, context.session_id)
