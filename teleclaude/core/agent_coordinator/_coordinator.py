"""Core AgentCoordinator class composing incremental-output and fanout mixins."""

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core import polling_coordinator
from teleclaude.core.activity_contract import serialize_activity_event
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_delivery import schedule_debounced_delivery
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentEventContext,
    AgentHookEvents,
    AgentHookEventType,
    AgentOutputPayload,
    AgentSessionStartPayload,
    AgentStopActivityEvent,
    AgentStopPayload,
    SessionStatusContext,
    TeleClaudeEvents,
    ToolUseActivityEvent,
    UserPromptSubmitActivityEvent,
    UserPromptSubmitPayload,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_title import generate_session_title_from_transcript
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.core.tool_activity import build_tool_preview, extract_tool_name
from teleclaude.tts.manager import TTSManager
from teleclaude.utils import strip_ansi_codes

from ._fanout import _FanoutMixin
from ._helpers import _is_checkpoint_prompt

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_LINKED_OUTPUT_PREFIX = f"{TELECLAUDE_SYSTEM_PREFIX} Linked output from "


class AgentCoordinator(
    _FanoutMixin,
):
    """Coordinator for agent events and inter-agent communication."""

    def __init__(
        self,
        client: "AdapterClient",
        tts_manager: TTSManager,
    ) -> None:
        self.client = client
        self.tts_manager = tts_manager
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
                            {
                                "message": f"Failed to update session title: {exc}",
                                "severity": "warning",
                            },  # type: ignore[arg-type]
                        )
                    except Exception:
                        pass

        task.add_done_callback(_on_done)

    async def _signal_headless_activity(self, session_id: str) -> None:
        """Drive one transcript projection pass for a headless session."""
        session = await db.get_session(session_id)
        if not session or session.lifecycle_status != "headless":
            return
        await db.update_last_activity(session_id)
        await polling_coordinator.schedule_headless_projection(session_id, self.client)

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
        if event_type == AgentHookEvents.TOOL_USE:
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
        elif context.event_type == AgentHookEvents.TOOL_USE:
            await self.handle_tool_use(context)
        elif context.event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
            await self.handle_user_prompt_submit(context)

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

        await self._speak_session_start(context.session_id)

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
            logger.debug("Empty prompt detected, skipping user input persistence for session %s", session_id)
            return

        # System-injected checkpoint — not real user input, skip entirely
        if _is_checkpoint_prompt(prompt_text, raw_payload=payload.raw):
            logger.debug("Checkpoint prompt detected, skipping user input persistence for session %s", session_id)
            return

        # Clear notification flag when new prompt starts (all sessions)
        await db.set_notification_flag(session_id, False)

        # Clear checkpoint state on real user input
        await db.update_session(session_id, last_checkpoint_at=None, last_tool_use_at=None)

        update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates

        # Terminal input bypasses the command pipeline — set origin here.
        # Acceptance handlers set last_input_origin for adapter-originated
        # commands. Re-read to see the current value.
        fresh_origin = await db.get_session(session_id)
        current_origin = (fresh_origin.last_input_origin if fresh_origin else session.last_input_origin) or ""
        is_terminal_input = current_origin == InputOrigin.TERMINAL.value or not current_origin
        if is_terminal_input:
            update_kwargs["last_input_origin"] = InputOrigin.TERMINAL.value

        # Single DB update for all fields
        await db.update_session(session_id, **update_kwargs)
        await db.update_last_activity(session_id)
        logger.debug(
            "Recorded user input via hook for session %s: %s...",
            session_id,
            prompt_text[:50],
        )

        # Drop pending QoS payloads on user input.
        await self.client.break_threaded_turn(session)

        # Emit activity event for all sessions
        self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)

        if session.lifecycle_status != "headless":
            now_ts = datetime.now(UTC).isoformat()
            self._emit_status_event(session_id, "accepted", "user_prompt_accepted", last_activity_at=now_ts)

    async def handle_agent_stop(self, context: AgentEventContext) -> None:
        """Handle stop event - Agent session stopped."""
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        source_computer = payload.source_computer

        # Fetch session early for logic checks
        session = await db.get_session(session_id)
        linked_prompt_at = (
            session.last_message_sent_at
            if session is not None
            and isinstance(session.last_message_sent_at, datetime)
            and (session.last_message_sent or "").strip().startswith(_LINKED_OUTPUT_PREFIX)
            else None
        )

        logger.debug(
            "Agent stop event for session %s (title: %s)",
            session_id,
            "db",
        )

        stop_timestamp = datetime.now(UTC).isoformat()
        await db.update_session(
            session_id,
            last_activity=stop_timestamp,
            last_agent_stop_at=stop_timestamp,
        )

        link_output, summary = await self._record_agent_stop_output(session_id, payload)

        # Emit activity event for UI updates (summary flows to TUI via event, not DB)
        self._emit_activity_event(session_id, AgentHookEvents.AGENT_STOP, summary=summary)

        # Emit canonical lifecycle status: completed (R2)
        self._emit_status_event(session_id, "completed", "agent_turn_complete", last_activity_at=stop_timestamp)

        # Immediate headless pull on stop — final output must be captured.
        await self._signal_headless_activity(session_id)
        await generate_session_title_from_transcript(session)

        await self._finalize_agent_stop(
            session_id,
            session,
            payload,
            link_output,
            source_computer,
            linked_prompt_at=linked_prompt_at,
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
        *,
        linked_prompt_at: datetime | None = None,
    ) -> None:
        """Complete stop fan-out, listener notification, and forwarding."""
        fanout_output = link_output
        used_conversation_replay = False
        if session is not None and isinstance(session.last_conversation_injected_at, datetime):
            schedule_debounced_delivery(
                session_id,
                client=self.client,
                command_service=get_command_service(),
                source_computer=source_computer,
            )
            used_conversation_replay = True
        elif linked_prompt_at is not None:
            fanout_output = await self._extract_agent_output_since(
                session_id,
                payload,
                since_timestamp=linked_prompt_at,
            )
        if not used_conversation_replay and fanout_output and fanout_output.strip():
            await self._fanout_linked_stop_output(session_id, fanout_output, source_computer=source_computer)

        title_raw = payload.raw.get("title")
        title = title_raw if isinstance(title_raw, str) and title_raw else None
        await self._notify_session_listener(session_id, source_computer=source_computer, title_override=title)

        if not (source_computer and source_computer != config.computer.name):
            await self._forward_stop_to_initiator(session_id, link_output)

    async def handle_tool_use(self, context: AgentEventContext) -> None:
        """Handle tool_use event — agent started a tool call.

        Only records the FIRST tool_use per turn (when last_tool_use_at is NULL).
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
        if session and not session.last_tool_use_at:
            now = datetime.now(UTC)
            await db.update_session(session_id, last_tool_use_at=now.isoformat())
            logger.debug("tool_use recorded for session %s", session_id)

        # Output fanout is transcript-driven from polling; hooks stay control-plane only.
        # tool_use still emits activity + checkpoint timing metadata.

        # Drive headless output delivery via debounced transcript pull.
        await self._signal_headless_activity(session_id)
