"""Incremental threaded output and suppression-state mixin for AgentCoordinator."""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.events import AgentOutputPayload, AgentStopPayload
from teleclaude.core.feature_flags import is_threaded_output_enabled
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    extract_last_user_message_with_timestamp,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)

from ._helpers import (
    _NOOP_LOG_INTERVAL_SECONDS,
    _has_active_output_message,
    _SuppressionState,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


class _IncrementalOutputMixin:
    """Suppression tracking and incremental threaded output rendering."""

    if TYPE_CHECKING:
        client: "AdapterClient"
        _incremental_noop_state: dict[str, _SuppressionState]
        _tool_use_skip_state: dict[str, _SuppressionState]
        _incremental_eval_state: dict[str, tuple[str, bool]]
        _incremental_render_digests: dict[str, str]
        _incremental_output_locks: dict[str, asyncio.Lock]
        _last_emitted_status: dict[str, str]

    def _suppression_signature(self, *parts: object) -> str:
        """Build a stable signature for no-op suppression contexts."""
        raw = "|".join("" if part is None else str(part) for part in parts)
        return sha256(raw.encode("utf-8")).hexdigest()

    def _mark_incremental_noop(self, session_id: str, *, reason: str, signature: str) -> None:
        """Record repeated incremental no-op events with sampled debug logging."""
        now = datetime.now(UTC)
        state = self._incremental_noop_state.get(session_id)

        if state and state.signature == signature:
            state.suppressed += 1
            elapsed_s = int((now - state.started_at).total_seconds())
            if (now - state.last_log_at).total_seconds() >= _NOOP_LOG_INTERVAL_SECONDS:
                logger.debug(
                    "Incremental no-op persists for session %s (reason=%s, suppressed=%d, elapsed_s=%d)",
                    session_id,
                    reason,
                    state.suppressed,
                    elapsed_s,
                )
                state.last_log_at = now
                state.suppressed = 0
            return

        self._incremental_noop_state[session_id] = _SuppressionState(
            signature=signature,
            started_at=now,
            last_log_at=now,
        )
        logger.debug("Incremental no-op entered for session %s (reason=%s)", session_id, reason)

    def _clear_incremental_noop(self, session_id: str, *, outcome: str) -> None:
        """Emit a one-time resume log when exiting a no-op suppression window."""
        now = datetime.now(UTC)
        state = self._incremental_noop_state.pop(session_id, None)
        if not state:
            return
        elapsed_s = int((now - state.started_at).total_seconds())
        logger.debug(
            "Incremental no-op cleared for session %s (outcome=%s, suppressed=%d, elapsed_s=%d)",
            session_id,
            outcome,
            state.suppressed,
            elapsed_s,
        )

    def _mark_tool_use_skip(self, session_id: str) -> None:
        """Collapse repeated tool_use skip logs for the same session."""
        now = datetime.now(UTC)
        state = self._tool_use_skip_state.get(session_id)
        signature = "tool_use_already_set"

        if state and state.signature == signature:
            state.suppressed += 1
            elapsed_s = int((now - state.started_at).total_seconds())
            if (now - state.last_log_at).total_seconds() >= _NOOP_LOG_INTERVAL_SECONDS:
                logger.debug(
                    "tool_use DB write still skipped for session %s (suppressed=%d, elapsed_s=%d)",
                    session_id,
                    state.suppressed,
                    elapsed_s,
                )
                state.last_log_at = now
                state.suppressed = 0
            return

        self._tool_use_skip_state[session_id] = _SuppressionState(
            signature=signature,
            started_at=now,
            last_log_at=now,
        )
        logger.debug("tool_use DB write skipped (already set) for session %s", session_id)

    def _clear_tool_use_skip(self, session_id: str) -> None:
        """Clear tool_use skip suppression when a new turn starts recording again."""
        now = datetime.now(UTC)
        state = self._tool_use_skip_state.pop(session_id, None)
        if not state or state.suppressed <= 0:
            return
        elapsed_s = int((now - state.started_at).total_seconds())
        logger.debug(
            "tool_use skip suppression cleared for session %s (suppressed=%d, elapsed_s=%d)",
            session_id,
            state.suppressed,
            elapsed_s,
        )

    async def _maybe_send_incremental_output(
        self, session_id: str, payload: AgentStopPayload | AgentOutputPayload
    ) -> bool:
        """Evaluate and potentially send incremental threaded output summary.

        Returns:
            True if threaded message was sent, False otherwise.
        """
        lock = self._incremental_output_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._incremental_output_locks[session_id] = lock

        async with lock:
            return await self._maybe_send_incremental_output_unlocked(session_id, payload)

    async def _maybe_send_incremental_output_unlocked(
        self, session_id: str, payload: AgentStopPayload | AgentOutputPayload
    ) -> bool:
        """Core incremental output path. Caller must hold session incremental lock."""
        session = await db.get_session(session_id)
        if not session:
            return False

        raw_agent_name = payload.raw.get("agent_name")
        payload_agent = raw_agent_name.strip().lower() if isinstance(raw_agent_name, str) else ""
        agent_key = payload_agent or session.active_agent
        if not agent_key:
            return False

        # Check if threaded output is enabled for this agent (any adapter).
        is_enabled = is_threaded_output_enabled(agent_key)
        eval_state = (agent_key, is_enabled)
        if self._incremental_eval_state.get(session_id) != eval_state:
            logger.debug(
                "Evaluating incremental output",
                session=session_id,
                agent=agent_key,
                is_enabled=is_enabled,
            )
            self._incremental_eval_state[session_id] = eval_state

        if not is_enabled:
            self._mark_incremental_noop(
                session_id,
                reason="threaded_output_disabled",
                signature=self._suppression_signature("disabled", agent_key),
            )
            return False

        transcript_path = payload.transcript_path or session.native_log_file
        if not transcript_path:
            self._mark_incremental_noop(
                session_id,
                reason="missing_transcript_path",
                signature=self._suppression_signature("missing_transcript", agent_key, session.native_log_file),
            )
            return False

        try:
            agent_name = AgentName.from_str(agent_key)
        except ValueError:
            return False

        # Tools are always included in threaded mode
        include_tools = is_threaded_output_enabled(agent_key)

        turn_cursor = session.last_tool_done_at

        # Force a turn break if a new user message is detected in the transcript.
        # This handles races where the agent starts outputting before the
        # user_prompt_submit hook has been processed.
        if _has_active_output_message(session):
            user_msg = extract_last_user_message_with_timestamp(transcript_path, agent_name)
            if user_msg:
                _, user_ts = user_msg
                # If user message is newer than our last rendered assistant block, break the block.
                if user_ts and (turn_cursor is None or user_ts > turn_cursor):
                    logger.info("New turn detected in transcript; forcing fresh message block for %s", session_id)
                    await self.client.break_threaded_turn(session)
                    # NOTE: Do NOT clear _incremental_render_digests here. The
                    # same content can be re-rendered on this tick; keeping the
                    # digest lets the dedup check prevent a duplicate send.
                    # The digest is cleared in the user-input handler
                    # where a genuinely new turn begins.
                    # Anchor this turn to the user message timestamp so repeated
                    # poll ticks don't keep re-breaking and replaying chunks.
                    await db.update_session(session_id, last_tool_done_at=user_ts.isoformat())
                    turn_cursor = user_ts
                    # Refresh session to reflect cleared state
                    session = await db.get_session(session_id)
                    if not session:
                        return False

        # 1. Retrieve all assistant messages since the current turn cursor
        assistant_messages = get_assistant_messages_since(transcript_path, agent_name, since_timestamp=turn_cursor)

        # Decide between clean (single-block) and standard (multi-block) rendering
        # using the number of renderable blocks, not message objects. Gemini often
        # emits multiple events (thinking/tool/text) inside a single assistant message.
        renderable_block_count = count_renderable_assistant_blocks(
            transcript_path,
            agent_name,
            since_timestamp=turn_cursor,
            include_tools=include_tools,
            include_tool_results=False,
        )

        analysis_signature = self._suppression_signature(
            "analysis",
            agent_key,
            transcript_path,
            len(assistant_messages),
            renderable_block_count,
            turn_cursor.isoformat() if turn_cursor else None,
        )

        if not assistant_messages:
            self._mark_incremental_noop(
                session_id,
                reason="no_assistant_messages",
                signature=analysis_signature,
            )
            return False

        self._clear_incremental_noop(session_id, outcome="assistant_messages_detected")
        logger.debug(
            "Incremental output analysis: session=%s msg_count=%d block_count=%d",
            session_id,
            len(assistant_messages),
            renderable_block_count,
        )

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
                since_timestamp=turn_cursor,
                include_timestamps=False,
            )
        else:
            # Single message: use clean, metadata-free renderer (italics/bold-monospace).
            message, last_ts = render_clean_agent_output(transcript_path, agent_name, since_timestamp=turn_cursor)

        if not message:
            # Activity detected but no renderable text (e.g. empty thinking blocks or hidden tool output).
            self._mark_incremental_noop(
                session_id,
                reason="no_renderable_message",
                signature=self._suppression_signature("no_render", analysis_signature),
            )
            return False

        try:
            # Pass raw Markdown to adapter. The adapter handles platform-specific
            # conversion (e.g. Telegram MarkdownV2 escaping) internally.
            formatted_message = message

            # Skip if content unchanged since last send.
            display_digest = sha256(formatted_message.encode("utf-8")).hexdigest()
            if self._incremental_render_digests.get(session_id) == display_digest:
                self._mark_incremental_noop(
                    session_id,
                    reason="unchanged_render_digest",
                    signature=self._suppression_signature("digest", display_digest, is_multi),
                )
                return False

            self._clear_incremental_noop(session_id, outcome="output_changed")
            logger.info(
                "Sending incremental output: tc_session=%s len=%d multi_message=%s",
                session_id,
                len(message),
                is_multi,
            )
            await self.client.send_threaded_output(session, formatted_message, multi_message=is_multi)
            self._incremental_render_digests[session_id] = display_digest

            # CRITICAL: Update cursor ONLY if we are NOT tracking this message for future updates.
            # If we are tracking (is_threaded_active), we want to re-render from the start of the turn
            # each time (accumulating content), so we do NOT update the cursor.
            # NOTE: We fetch fresh session/metadata to check adapter output_message_id
            fresh_session = await db.get_session(session_id)
            is_threaded_active = fresh_session is not None and _has_active_output_message(fresh_session)
            should_update_cursor = not is_threaded_active

            # Always update session to refresh last_activity (heartbeat),
            # but conditionally update the cursor.
            update_kwargs = {}
            if should_update_cursor and last_ts:
                from teleclaude.core.models import SessionField

                update_kwargs[SessionField.LAST_TOOL_DONE_AT.value] = last_ts.isoformat()
                logger.debug("Updating cursor for session %s to %s", session_id, last_ts.isoformat())

            # Persist cursor timestamp (activity events are emitted separately).
            if update_kwargs:
                await db.update_session(session_id, **update_kwargs)

            return True
        except Exception as exc:
            logger.warning("Failed to send incremental output: %s", exc, extra={"session_id": session_id})

        return False

    async def trigger_incremental_output(self, session_id: str) -> bool:
        """Trigger incremental threaded output refresh for a session.

        Called by the polling coordinator on each OutputChanged tick.
        Skipped when the turn is already complete (handle_agent_stop delivered
        the final render and called break_threaded_turn).
        """
        session = await db.get_session(session_id)
        if not session:
            return False

        if not is_threaded_output_enabled(session.active_agent):
            return False

        # After handle_agent_stop, status transitions to "completed" and
        # break_threaded_turn resets adapter state.  A subsequent poller tick
        # would re-render with different parameters (block_count, multi_message)
        # producing a different digest and bypassing dedup — causing a duplicate
        # message.  Guard: skip if the turn is already done.
        status = self._last_emitted_status.get(session_id)
        if status in ("completed", "closed", "error"):
            return False

        payload = AgentOutputPayload(session_id=session_id, transcript_path=session.native_log_file)
        return await self._maybe_send_incremental_output(session_id, payload)
