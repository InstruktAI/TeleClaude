"""Agent Coordinator - orchestrates agent events and cross-computer communication.

Handles agent lifecycle events (start, stop, notification) and routes them to:
1. Local listeners (via tmux injection)
2. Remote initiators (via Redis transport)
3. Human UI (via AdapterClient feedback)
"""

import asyncio
import base64
import random
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING, Coroutine, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import (
    CHECKPOINT_MESSAGE,
    CHECKPOINT_PREFIX,
    LOCAL_COMPUTER,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.checkpoint_dispatch import inject_checkpoint_if_needed
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentEventContext,
    AgentHookEvents,
    AgentNotificationPayload,
    AgentOutputPayload,
    AgentSessionEndPayload,
    AgentSessionStartPayload,
    AgentStopPayload,
    TeleClaudeEvents,
    UserPromptSubmitPayload,
)
from teleclaude.core.feature_flags import is_threaded_output_enabled, is_threaded_output_include_tools_enabled
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import notify_input_request, notify_stop
from teleclaude.core.summarizer import summarize_agent_output, summarize_user_input_title
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService
from teleclaude.tts.manager import TTSManager
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.utils import strip_ansi_codes
from teleclaude.utils.markdown import telegramify_markdown
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    extract_last_agent_message,
    extract_last_user_message_with_timestamp,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_PASTED_CONTENT_PLACEHOLDER_RE = re.compile(r"^\[Pasted Content \d+ chars\]$")

SESSION_START_MESSAGES = [
    "Standing by with grep patterns locked and loaded. What can I find?",
    "Warmed up and ready to hunt down that bug!",
    "Cache cleared, mind fresh. What's the task?",
    "All systems nominal, ready to ship some code!",
    "Initialized and ready to make those tests pass. What needs fixing?",
    "Compiled with optimism and ready to refactor!",
    "Ready to turn coffee into code. Where do we start?",
    "Standing by like a well-indexed database!",
    "Alert and ready to parse whatever you need. What's up?",
    "Primed to help you ship that feature!",
    "Spun up and ready to debug. What's broken?",
    "Loaded and eager to make things work!",
    "Ready to dig into the details. What should I investigate?",
    "All systems go for some serious coding!",
    "Prepared to tackle whatever you throw at me. What's the challenge?",
    "Standing by to help ship something awesome!",
    "Ready to make the build green. What needs attention?",
    "Warmed up and waiting to assist!",
    "Initialized and ready to solve problems. What's the issue?",
    "All set to help you build something great!",
]


def _is_checkpoint_prompt(
    prompt: str,
    *,
    raw_payload: object = None,
) -> bool:
    """Return True when prompt text is our system checkpoint message.

    Matches both the generic Phase 1 message and context-aware Phase 2
    messages by checking known prefixes.  Codex synthetic input detection
    truncates captured prompt text, so we also accept 40-char prefixes of
    the generic constant for synthetic events.
    """
    prompt_clean = (prompt or "").strip()
    if not prompt_clean:
        return False

    # Canonical prefix match covers all checkpoint variants.
    if prompt_clean.startswith(CHECKPOINT_PREFIX):
        return True

    # Exact match for the generic constant (backward compat).
    checkpoint_clean = CHECKPOINT_MESSAGE.strip()
    if prompt_clean == checkpoint_clean:
        return True

    # Truncated Codex synthetic prompt (from output polling / fast-poll)
    is_codex_synthetic = False
    if isinstance(raw_payload, dict):
        source = raw_payload.get("source")
        is_codex_synthetic = (
            bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")
        )

    if is_codex_synthetic and len(prompt_clean) >= 40 and checkpoint_clean.startswith(prompt_clean):
        return True

    return False


def _is_codex_synthetic_prompt_event(raw_payload: object) -> bool:
    """Return True for Codex synthetic prompt events derived from output polling."""
    if not isinstance(raw_payload, Mapping):
        return False
    source = raw_payload.get("source")
    return bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")


def _is_pasted_content_placeholder(prompt: str) -> bool:
    """Return True when prompt is a synthetic pasted-content placeholder."""
    return bool(_PASTED_CONTENT_PLACEHOLDER_RE.fullmatch((prompt or "").strip()))


def _to_utc(ts: datetime) -> datetime:
    """Normalize naive datetimes to UTC for stable comparisons."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _is_codex_input_already_recorded(
    session: "Session | None",
    prompt_text: str,
) -> bool:
    """Return True when session state already reflects this Codex prompt turn."""
    if not session:
        return False

    existing_prompt = (session.last_message_sent or "").strip()
    candidate_prompt = (prompt_text or "").strip()
    if not existing_prompt or not candidate_prompt:
        return False
    prompts_match = (
        existing_prompt == candidate_prompt
        or existing_prompt.startswith(candidate_prompt)
        or candidate_prompt.startswith(existing_prompt)
    )
    if not prompts_match:
        return False
    if not isinstance(session.last_message_sent_at, datetime):
        return False

    message_at = _to_utc(session.last_message_sent_at)
    if not isinstance(session.last_feedback_received_at, datetime):
        return True
    feedback_at = _to_utc(session.last_feedback_received_at)
    return message_at > feedback_at


class AgentCoordinator:
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
            except Exception as exc:  # noqa: BLE001 - background task errors are logged and dropped
                logger.error("Background task '%s' failed: %s", label, exc, exc_info=True)

                # Emit error event for user-visible failures (title updates, TTS)
                # Other background failures are logged but don't require user notification
                if "title" in label.lower():
                    try:
                        event_bus.emit(
                            TeleClaudeEvents.ERROR,
                            {"message": f"Failed to update session title: {exc}", "severity": "warning"},
                        )
                    except Exception:  # noqa: BLE001 - don't cascade error event failures
                        pass

        task.add_done_callback(_on_done)

    def _emit_activity_event(
        self,
        session_id: str,
        event_type: str,
        tool_name: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Emit agent activity event with error handling.

        Args:
            session_id: Session identifier
            event_type: AgentHookEventType value
            tool_name: Optional tool name for tool_use events
            summary: Optional output summary (agent_stop only)
        """
        try:
            event_bus.emit(
                TeleClaudeEvents.AGENT_ACTIVITY,
                AgentActivityEvent(
                    session_id=session_id,
                    event_type=event_type,
                    tool_name=tool_name,
                    summary=summary,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
            )
        except Exception as exc:
            logger.error(
                "Failed to emit activity event: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id[:8], "event_type": event_type},
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
        elif context.event_type == AgentHookEvents.AGENT_NOTIFICATION:
            await self.handle_notification(context)
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

        if isinstance(raw_cwd, str) and raw_cwd:
            session = await db.get_session(context.session_id)
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
                context.session_id[:8],
            )

        logger.info(
            "Stored Agent session data: teleclaude=%s, native=%s",
            context.session_id[:8],
            str(native_session_id)[:8],
        )

        await self._maybe_send_headless_snapshot(context.session_id)
        await self._speak_session_start()

    async def handle_user_prompt_submit(self, context: AgentEventContext) -> None:
        """Handle user prompt submission.

        For ALL sessions: write last_message_sent to DB (captures direct terminal input).
        If title is "Untitled", summarize user input and update title.
        For headless sessions: also route through process_message for tmux adoption.
        """
        session_id = context.session_id
        payload = cast(UserPromptSubmitPayload, context.data)

        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for user_prompt_submit", session_id[:8])
            return

        prompt_text = payload.prompt or ""
        if not prompt_text.strip():
            logger.debug("Empty prompt detected, skipping user input persistence for session %s", session_id[:8])
            return

        is_codex_synthetic = _is_codex_synthetic_prompt_event(payload.raw)
        # Guard against occasional single-character Codex polling artifacts (e.g. "r")
        # that would overwrite the real last input and cause misleading TUI state.
        if is_codex_synthetic and len(prompt_text.strip()) <= 1:
            logger.debug(
                "Ignoring tiny synthetic Codex prompt for session %s: %r",
                session_id[:8],
                prompt_text,
            )
            return

        # System-injected checkpoint — not real user input, skip entirely
        if _is_checkpoint_prompt(prompt_text, raw_payload=payload.raw):
            logger.debug("Checkpoint prompt detected, skipping user input persistence for session %s", session_id[:8])
            return

        # Clear notification flag when new prompt starts (all sessions)
        await db.set_notification_flag(session_id, False)

        # Clear checkpoint state on real user input
        await db.update_session(session_id, last_checkpoint_at=None, last_tool_use_at=None)

        # Prepare batched update
        now = datetime.now(timezone.utc)
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
                    session_id[:8],
                    existing_input[:50],
                    incoming_input[:50],
                )

        update_kwargs: dict[str, object] = {  # guard: loose-dict - Dynamic session updates
            "last_input_origin": InputOrigin.HOOK.value,
        }
        if should_update_last_message:
            update_kwargs.update(
                {
                    "last_message_sent": prompt_text[:200],
                    "last_message_sent_at": now.isoformat(),
                }
            )

        # Title update is non-critical and must not block hook ordering.
        if session.title == "Untitled" and not (is_codex_synthetic and _is_pasted_content_placeholder(prompt_text)):
            self._queue_background_task(
                self._update_session_title_async(session_id, prompt_text),
                f"title-summary:{session_id[:8]}",
            )

        # Single DB update for all fields
        await db.update_session(session_id, **update_kwargs)
        logger.debug(
            "Recorded user input via hook for session %s: %s...",
            session_id[:8],
            prompt_text[:50],
        )

        # Emit activity event for UI updates.
        # Synthetic Codex prompts are still real input events.
        self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)

        # Non-headless: DB write done above, no further routing needed
        # (the agent already received the input directly)
        if session.lifecycle_status != "headless":
            return

        # Headless: route through unified process_message path
        # This handles tmux adoption and polling start
        from teleclaude.core.command_registry import get_command_service

        cmd = ProcessMessageCommand(
            session_id=session_id,
            text=prompt_text,
            origin=InputOrigin.HOOK.value,
        )

        logger.debug(
            "Routing headless session %s through process_message for tmux adoption",
            session_id[:8],
        )

        await get_command_service().process_message(cmd)

    async def _update_session_title_async(self, session_id: str, prompt: str) -> None:
        """Best-effort asynchronous title update for untitled sessions."""
        if not prompt:
            return

        current = await db.get_session(session_id)
        if not current or current.title != "Untitled":
            return

        try:
            new_title = await summarize_user_input_title(prompt)
        except Exception as exc:  # noqa: BLE001 - title update should not break flow
            logger.warning("Title summarization failed: %s", exc)
            return

        if not new_title:
            return

        latest = await db.get_session(session_id)
        if not latest or latest.title != "Untitled":
            return

        await db.update_session(session_id, title=new_title)
        logger.info("Updated session title from user input: %s", new_title)

    async def handle_agent_stop(self, context: AgentEventContext) -> None:
        """Handle stop event - Agent session stopped."""
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        source_computer = payload.source_computer

        # Fetch session early for logic checks
        session = await db.get_session(session_id)

        logger.debug(
            "Agent stop event for session %s (title: %s)",
            session_id[:8],
            "db",
        )

        # 1. Extract turn artifacts and persist with a single ordered activity update.
        active_agent = (session.active_agent if session else None) or (
            payload.raw.get("agent_name") if payload.raw else None
        )
        input_update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        feedback_update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        emit_codex_submit_backfill = False

        # For Codex: recover last user input from transcript (no native prompt hook).
        codex_input = await self._extract_user_input_for_codex(session_id, payload)
        if isinstance(codex_input, tuple) and len(codex_input) == 2:
            input_text, input_timestamp = codex_input
            input_update_kwargs.update(
                {
                    "last_message_sent": input_text[:200],
                    "last_input_origin": InputOrigin.HOOK.value,
                }
            )
            if input_timestamp:
                input_update_kwargs["last_message_sent_at"] = input_timestamp.isoformat()
            if input_text.strip() and not _is_codex_input_already_recorded(session, input_text):
                emit_codex_submit_backfill = True
        elif codex_input:
            logger.debug(
                "Ignoring malformed codex input tuple for session %s",
                session_id[:8],
            )

        if input_update_kwargs:
            await db.update_session(session_id, **input_update_kwargs)
        if emit_codex_submit_backfill:
            logger.info(
                "Backfilling missing user_prompt_submit from codex agent_stop for session %s",
                session_id[:8],
            )
            self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)

        raw_output = await self._extract_agent_output(session_id, payload)
        if raw_output:
            if config.terminal.strip_ansi:
                raw_output = strip_ansi_codes(raw_output)
            if not raw_output.strip():
                logger.debug("Skip stop summary/TTS (agent output empty after normalization)", session=session_id[:8])
                raw_output = None

        summary: str | None = None
        if raw_output:
            summary = await self._summarize_output(session_id, raw_output)
            feedback_update_kwargs.update(
                {
                    "last_feedback_received": raw_output,
                    "last_feedback_summary": summary,
                    "last_feedback_received_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.debug(
                "Stored agent output: session=%s raw_len=%d summary_len=%d",
                session_id[:8],
                len(raw_output),
                len(summary) if summary else 0,
            )
            if summary:
                try:
                    await self.tts_manager.speak(summary)
                except Exception as exc:  # noqa: BLE001 - TTS should never crash event handling
                    logger.warning("TTS agent_stop failed: %s", exc, extra={"session_id": session_id[:8]})

        # Persist feedback and status to DB (activity events are emitted separately).
        if feedback_update_kwargs:
            await db.update_session(session_id, **feedback_update_kwargs)

        # Emit activity event for UI updates (summary flows to TUI via event, not DB)
        self._emit_activity_event(session_id, AgentHookEvents.AGENT_STOP, summary=summary)

        # 2. Incremental threaded output (final turn portion)
        await self._maybe_send_incremental_output(session_id, payload)

        # Clear threaded output state for this turn (only for threaded sessions).
        # Non-threaded sessions rely on the poller's output_message_id for in-place edits.
        session = await db.get_session(session_id)  # Refresh to get latest metadata
        if session and active_agent and is_threaded_output_enabled(str(active_agent)):
            # Clear output_message_id via dedicated column (not adapter_metadata blob)
            # to prevent concurrent adapter_metadata writes from clobbering it.
            await db.set_output_message_id(session_id, None)
            telegram_meta = session.get_metadata().get_ui().get_telegram()
            telegram_meta.char_offset = 0
            await db.update_session(session_id, adapter_metadata=session.adapter_metadata)

        # Clear turn-specific cursor at turn completion
        await db.update_session(session_id, last_tool_done_at=None)

        # 3. Notify local listeners (AI-to-AI on same computer)
        await self._notify_session_listener(session_id, source_computer=source_computer)

        # 4. Forward to remote initiator (AI-to-AI across computers)
        if not (source_computer and source_computer != config.computer.name):
            await self._forward_stop_to_initiator(session_id)

        # 5. Inject checkpoint into the stopped agent's tmux pane
        await self._maybe_inject_checkpoint(session_id, session)

    async def handle_tool_use(self, context: AgentEventContext) -> None:
        """Handle tool_use event — agent started a tool call.

        Only records the FIRST tool_use per turn (when last_tool_use_at is NULL).
        This gives _maybe_inject_checkpoint the true turn start time, not the last tool call.
        Cleared by handle_user_prompt_submit when a new turn begins.
        """
        session_id = context.session_id
        payload = cast(AgentOutputPayload, context.data)

        # Extract tool name from raw payload if available
        tool_name = None
        if payload.raw:
            raw_tool = payload.raw.get("tool_name") or payload.raw.get("toolName")
            tool_name = str(raw_tool) if raw_tool else None

        # Always emit activity event for UI updates (every tool call)
        self._emit_activity_event(session_id, AgentHookEvents.TOOL_USE, tool_name)

        # DB write is deduped: only record the FIRST tool_use per turn for checkpoint timing
        session = await db.get_session(session_id)
        if session and session.last_tool_use_at:
            logger.debug("tool_use DB write skipped (already set) for session %s", session_id[:8])
            return
        now = datetime.now(timezone.utc)
        await db.update_session(session_id, last_tool_use_at=now.isoformat())
        logger.debug("tool_use recorded for session %s", session_id[:8])

    async def handle_tool_done(self, context: AgentEventContext) -> None:
        """Handle tool_done event — tool execution completed, output available."""
        session_id = context.session_id
        payload = cast(AgentOutputPayload, context.data)
        await self._maybe_send_incremental_output(session_id, payload)

        # Emit activity event for UI updates
        self._emit_activity_event(session_id, AgentHookEvents.TOOL_DONE)

    async def _maybe_send_incremental_output(
        self, session_id: str, payload: AgentStopPayload | AgentOutputPayload
    ) -> bool:
        """Evaluate and potentially send incremental threaded output summary.

        Returns:
            True if threaded message was sent, False otherwise.
        """
        session = await db.get_session(session_id)
        if not session:
            return False

        agent_key = session.active_agent
        if not agent_key:
            return False

        # Check if experiment is enabled for this agent (Gemini only).
        is_enabled = is_threaded_output_enabled(agent_key)
        logger.debug("Evaluating incremental output", session=session_id[:8], agent=agent_key, is_enabled=is_enabled)

        if not is_enabled:
            return False

        transcript_path = payload.transcript_path or session.native_log_file
        if not transcript_path:
            logger.debug("Incremental output skipped (missing transcript path)", session=session_id[:8])
            return False

        try:
            agent_name = AgentName.from_str(agent_key)
        except ValueError:
            return False

        # Check if tools should be included
        include_tools = is_threaded_output_include_tools_enabled(agent_key)

        # 1. Retrieve all assistant messages since the last cursor
        assistant_messages = get_assistant_messages_since(
            transcript_path, agent_name, since_timestamp=session.last_tool_done_at
        )

        # Decide between clean (single-block) and standard (multi-block) rendering
        # using the number of renderable blocks, not message objects. Gemini often
        # emits multiple events (thinking/tool/text) inside a single assistant message.
        renderable_block_count = count_renderable_assistant_blocks(
            transcript_path,
            agent_name,
            since_timestamp=session.last_tool_done_at,
            include_tools=include_tools,
            include_tool_results=False,
        )

        logger.debug(
            "Incremental output analysis: session=%s msg_count=%d block_count=%d",
            session_id[:8],
            len(assistant_messages),
            renderable_block_count,
        )

        if not assistant_messages:
            return False

        # 2. Decide which renderer to use based on renderable block count
        is_multi = renderable_block_count > 1

        if is_multi:
            # Multi-message: use standard renderer (with headers) for bulk update.
            # Suppression of tool results is handled inside the renderer for UI.
            # No truncation; adapter handles pagination/splitting.
            message, last_ts = render_agent_output(
                transcript_path,
                agent_name,
                include_tools=include_tools,
                include_tool_results=False,
                since_timestamp=session.last_tool_done_at,
                include_timestamps=False,
            )
        else:
            # Single message: use clean, metadata-free renderer (italics/bold-monospace).
            message, last_ts = render_clean_agent_output(
                transcript_path, agent_name, since_timestamp=session.last_tool_done_at
            )

        if not message:
            # Activity detected but no renderable text (e.g. empty thinking blocks or hidden tool output).
            # Use a placeholder to ensure the UI shows liveness (and the footer updates).
            message = "_..._"

        if message:
            logger.info(
                "Sending incremental output: tc_session=%s len=%d multi_message=%s",
                session_id[:8],
                len(message),
                is_multi,
            )
            try:
                # Keep Telegram MarkdownV2 formatting for both renderers.
                formatted_message = telegramify_markdown(message)

                # Skip if content unchanged since last send.
                display_digest = sha256(formatted_message.encode("utf-8")).hexdigest()

                # Only update main message if content actually changed
                if session.last_output_digest != display_digest:
                    await self.client.send_threaded_output(session, formatted_message, multi_message=is_multi)

                # CRITICAL: Update cursor ONLY if we are NOT tracking this message for future updates.
                # If we are tracking (is_threaded_active), we want to re-render from the start of the turn
                # each time (accumulating content), so we do NOT update the cursor.
                # NOTE: We fetch fresh session/metadata to check the ID set by send_threaded_output
                fresh_session = await db.get_session(session_id)
                is_threaded_active = fresh_session and fresh_session.output_message_id is not None
                should_update_cursor = not is_threaded_active

                # Always update session to refresh last_activity (heartbeat),
                # but conditionally update the cursor.
                update_kwargs = {}
                if should_update_cursor and last_ts:
                    from teleclaude.core.models import SessionField

                    update_kwargs[SessionField.LAST_TOOL_DONE_AT.value] = last_ts.isoformat()
                    logger.debug("Updating cursor for session %s to %s", session_id[:8], last_ts.isoformat())

                # Persist cursor timestamp (activity events are emitted separately).
                if update_kwargs:
                    await db.update_session(session_id, **update_kwargs)

                return True
            except Exception as exc:  # noqa: BLE001 - Message send should never crash event handling
                logger.warning("Failed to send incremental output: %s", exc, extra={"session_id": session_id[:8]})

        return False

    async def handle_notification(self, context: AgentEventContext) -> None:
        """Handle notification event - input request."""
        session_id = context.session_id
        payload = cast(AgentNotificationPayload, context.data)
        message = payload.message
        source_computer = payload.source_computer

        # 1. Notify local listeners
        computer = source_computer or LOCAL_COMPUTER
        await notify_input_request(session_id, computer, str(message))

        # 2. Forward to remote initiator (skip if already forwarded from remote)
        if not source_computer:
            await self._forward_notification_to_initiator(session_id, str(message))

        # Update notification flag
        await db.set_notification_flag(session_id, True)

    async def handle_session_end(self, context: AgentEventContext) -> None:
        """Handle session_end event - agent session ended."""
        _payload = cast(AgentSessionEndPayload, context.data)
        logger.info("Agent %s for session %s", AgentHookEvents.AGENT_SESSION_END, context.session_id[:8])

    async def _maybe_send_headless_snapshot(self, session_id: str) -> None:
        session = await db.get_session(session_id)
        if not session or session.lifecycle_status != "headless":
            return
        if not session.active_agent or not session.native_log_file:
            logger.debug("Headless snapshot skipped (missing agent or transcript)", session=session_id[:8])
            return
        await self.headless_snapshot_service.send_snapshot(session, reason="agent_session_start", client=self.client)

    async def _speak_session_start(self) -> None:
        if not SESSION_START_MESSAGES:
            return
        message = random.choice(SESSION_START_MESSAGES)
        try:
            await self.tts_manager.speak(message)
        except Exception as exc:  # noqa: BLE001 - TTS should never crash event handling
            logger.warning("TTS session_start failed: %s", exc)

    async def _extract_agent_output(self, session_id: str, payload: AgentStopPayload) -> str | None:
        """Extract last agent output from transcript.

        Returns:
            Raw output text, or None if extraction fails or no output found.
        """
        session = await db.get_session(session_id)
        transcript_path = payload.transcript_path or (session.native_log_file if session else None)
        if not transcript_path:
            logger.debug("Extract skipped (missing transcript path)", session=session_id[:8])
            return None

        raw_agent_name = payload.raw.get("agent_name")
        agent_name_value = raw_agent_name if isinstance(raw_agent_name, str) and raw_agent_name else None
        if not agent_name_value and session and session.active_agent:
            agent_name_value = session.active_agent
        if not agent_name_value:
            logger.debug("Extract skipped (missing agent name)", session=session_id[:8])
            return None

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            logger.warning("Extract skipped (unknown agent '%s')", agent_name_value)
            return None

        last_message = extract_last_agent_message(transcript_path, agent_name, 1)
        if not last_message or not last_message.strip():
            logger.debug("Extract skipped (no agent output)", session=session_id[:8])
            return None

        return last_message

    async def _summarize_output(self, session_id: str, raw_output: str) -> str | None:
        """Summarize raw agent output via LLM.

        Returns:
            Summary text, or None if summarization fails.
        """
        if not raw_output.strip():
            logger.debug("Summarization skipped (empty normalized output)", session=session_id[:8])
            return None
        try:
            _title, summary = await summarize_agent_output(raw_output)
            return summary
        except Exception as exc:  # noqa: BLE001 - summarizer failures should not break stop handling
            logger.warning("Summarization failed: %s", exc, extra={"session_id": session_id[:8]})
            return None

    async def _extract_user_input_for_codex(
        self, session_id: str, payload: AgentStopPayload
    ) -> tuple[str, datetime | None] | None:
        """Extract last user input from transcript for Codex sessions.

        Codex doesn't have user_prompt_submit hook, so we extract user input
        from the transcript on agent stop as a fallback.
        """
        session = await db.get_session(session_id)
        if not session:
            return None

        # Only for Codex sessions
        agent_name_value = session.active_agent
        if agent_name_value != AgentName.CODEX.value:
            return None

        transcript_path = payload.transcript_path or session.native_log_file
        if not transcript_path:
            logger.debug("Codex user input extraction skipped (no transcript)", session=session_id[:8])
            return None

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            return None

        extracted = extract_last_user_message_with_timestamp(transcript_path, agent_name)
        if not extracted:
            logger.debug("Codex user input extraction skipped (no user message)", session=session_id[:8])
            return None
        last_user_input, input_timestamp = extracted

        # Don't persist our own checkpoint message as user input
        if _is_checkpoint_prompt(last_user_input):
            logger.debug("Codex user input skipped (checkpoint message) for session %s", session_id[:8])
            return None

        logger.debug(
            "Extracted Codex user input: session=%s input=%s...",
            session_id[:8],
            last_user_input[:50],
        )
        return last_user_input, input_timestamp

    async def _notify_session_listener(
        self,
        target_session_id: str,
        *,
        source_computer: str | None = None,
    ) -> None:
        """Notify local listeners via tmux injection."""
        target_session = await db.get_session(target_session_id)
        display_title = target_session.title if target_session else "Unknown"
        computer = source_computer or LOCAL_COMPUTER
        await notify_stop(target_session_id, computer, title=display_title)

    async def _forward_stop_to_initiator(self, session_id: str) -> None:
        """Forward stop event to remote initiator via Redis.

        Uses session.title from DB (stable, canonical) rather than
        freshly generated title from summarizer.
        """
        session = await db.get_session(session_id)
        if not session:
            return

        redis_meta = session.get_metadata().get_transport().get_redis()
        if not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
        if initiator_computer == config.computer.name:
            return

        # Use stable title from session record
        title_arg = ""
        if session.title:
            title_b64 = base64.b64encode(session.title.encode()).decode()
            title_arg = f" {title_b64}"

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/stop_notification {session_id} {config.computer.name}{title_arg}",
                metadata=MessageMetadata(),
            )
            logger.info("Forwarded stop to %s", initiator_computer)
        except Exception as e:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, e)

    async def _forward_notification_to_initiator(self, session_id: str, message: str) -> None:
        """Forward notification to remote initiator."""
        session = await db.get_session(session_id)
        if not session:
            return

        redis_meta = session.get_metadata().get_transport().get_redis()
        if not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
        if initiator_computer == config.computer.name:
            return

        message_b64 = base64.b64encode(message.encode()).decode()
        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/input_notification {session_id} {config.computer.name} {message_b64}",
                metadata=MessageMetadata(),
            )
        except Exception as e:
            logger.warning("Failed to forward notification to %s: %s", initiator_computer, e)

    async def _maybe_inject_checkpoint(self, session_id: str, session: "Session | None") -> None:
        """Conditionally inject a checkpoint message into the agent's tmux pane.

        Claude/Gemini: handled by hook output in receiver.py (invisible checkpoint).
        Codex: falls through to tmux injection below.
        """
        if not session:
            return

        try:
            await inject_checkpoint_if_needed(
                session_id,
                route="codex_tmux",
                include_elapsed_since_turn_start=True,
                default_agent=AgentName.CLAUDE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Checkpoint injection failed for session %s: %s", session_id[:8], exc)
