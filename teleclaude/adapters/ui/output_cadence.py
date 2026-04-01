"""Adapter-owned output cadence loop.

Each UI adapter runs its own cadence timer. On each tick, the adapter
checks active sessions, pulls transcripts, renders output, and sends
if content has changed. Core only signals activity via last_activity_at;
no output data flows from core to adapters.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.models import SessionField
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)

if TYPE_CHECKING:
    from teleclaude.adapters.ui_adapter import UiAdapter
    from teleclaude.core.models import Session

logger = get_logger(__name__)

# Sessions with activity within this window are candidates for output pull.
_ACTIVITY_WINDOW = timedelta(seconds=120)


class OutputCadenceLoop:
    """Per-adapter cadence loop that pulls and renders session output."""

    def __init__(self, adapter: UiAdapter, interval_seconds: float) -> None:
        self._adapter = adapter
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        # Per-session output lock to prevent concurrent renders.
        self._locks: dict[str, asyncio.Lock] = {}

    def start(self) -> None:
        """Start the cadence loop background task."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=f"output-cadence-{self._adapter.ADAPTER_KEY}")

    async def stop(self) -> None:
        """Stop the cadence loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def pull_session(self, session: Session) -> None:
        """Force an immediate output pull for one session outside the cadence schedule."""
        await self._pull_session_output(session)

    async def _reflect_user_input(self, session: Session, user_text: str) -> None:
        """Reflect user input to this adapter's channel.

        Each adapter independently reflects user input it detects in the
        transcript. The originating adapter suppresses its own echo via
        reflection_origin matching.
        """
        from teleclaude.core.identity import get_identity_resolver  # pylint: disable=import-outside-toplevel
        from teleclaude.core.models import MessageMetadata  # pylint: disable=import-outside-toplevel

        try:
            input_origin = session.last_input_origin or ""
            resolver = get_identity_resolver()
            identity = resolver.resolve(input_origin, session.get_origin_section(input_origin))
            if not identity.person_name and session.human_email:
                identity = resolver.resolve_by_email(session.human_email)

            metadata = MessageMetadata(
                parse_mode=None,
                reflection_origin=input_origin,
                reflection_actor_name=identity.display_name,
            )
            await self._adapter.send_message(session, user_text, metadata=metadata)
        except Exception:  # pylint: disable=broad-exception-caught  # Reflection is non-critical.
            logger.debug(
                "User input reflection failed: session=%s adapter=%s",
                session.session_id,
                self._adapter.ADAPTER_KEY,
                exc_info=True,
            )

    async def _run(self) -> None:
        """Main cadence loop — runs until cancelled."""
        adapter_key = self._adapter.ADAPTER_KEY
        logger.info("Output cadence loop started: adapter=%s interval=%.1fs", adapter_key, self._interval)
        try:
            while True:
                await asyncio.sleep(self._interval)
                try:
                    await self._tick()
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.warning("Output cadence tick failed for %s", adapter_key, exc_info=True)
        except asyncio.CancelledError:
            logger.info("Output cadence loop stopped: adapter=%s", adapter_key)

    async def _tick(self) -> None:
        """Single cadence tick: find active sessions, pull and render output."""
        cutoff = datetime.now(UTC) - _ACTIVITY_WINDOW
        active_sessions = await db.get_sessions_active_since(cutoff)
        for session in active_sessions:
            if not session.native_log_file or not session.active_agent:
                continue
            try:
                session = await self._adapter.ensure_channel(session)
                await self._pull_session_output(session)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Output pull failed for session %s on %s",
                    session.session_id,
                    self._adapter.ADAPTER_KEY,
                    exc_info=True,
                )

    async def _pull_session_output(self, session: Session) -> None:
        """Pull transcript for one session, render, and send if changed."""
        session_id = session.session_id
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock

        if lock.locked():
            return  # Previous tick still rendering; skip.

        async with lock:
            await self._pull_unlocked(session)

    async def _pull_unlocked(self, session: Session) -> None:  # pylint: disable=too-many-locals,too-many-branches
        """Core pull logic. Caller must hold session lock."""
        session_id = session.session_id
        transcript_path = session.native_log_file
        if not transcript_path:
            return

        try:
            agent_name = AgentName.from_str(session.active_agent)
        except ValueError:
            logger.warning(
                "Invalid active_agent %r for session %s, skipping output pull", session.active_agent, session_id
            )
            return

        turn_cursor = session.last_tool_done_at

        # Turn-break detection is NOT done here — core owns that responsibility
        # via break_threaded_turn (coordinator + command handlers).  The cadence
        # loop only renders; it never mutates turn state.

        # Read assistant messages since cursor.
        assistant_messages = get_assistant_messages_since(transcript_path, agent_name, since_timestamp=turn_cursor)
        if not assistant_messages:
            return

        # Decide renderer based on renderable block count.
        include_tools = True
        renderable_block_count = count_renderable_assistant_blocks(
            transcript_path,
            agent_name,
            since_timestamp=turn_cursor,
            include_tools=include_tools,
            include_tool_results=False,
        )
        is_multi = renderable_block_count > 1

        if is_multi:
            message, last_ts = render_agent_output(
                transcript_path,
                agent_name,
                include_tools=include_tools,
                include_tool_results=False,
                since_timestamp=turn_cursor,
                include_timestamps=False,
            )
        else:
            message, last_ts = render_clean_agent_output(transcript_path, agent_name, since_timestamp=turn_cursor)

        if not message or not last_ts:
            return

        # Deduplicate by delivery timestamp (persisted in origin_metadata).
        last_delivered_raw = self._adapter._origin_field(session, "last_delivered_at")  # pylint: disable=protected-access
        if isinstance(last_delivered_raw, str):
            from teleclaude.utils.transcript._utils import _parse_timestamp  # pylint: disable=import-outside-toplevel

            last_delivered = _parse_timestamp(last_delivered_raw)
            if last_delivered and last_ts <= last_delivered:
                return

        # Send via adapter's threaded output method.
        logger.debug(
            "Cadence output: session=%s adapter=%s len=%d multi=%s",
            session_id,
            self._adapter.ADAPTER_KEY,
            len(message),
            is_multi,
        )
        await self._adapter.send_threaded_output(session, message, multi_message=is_multi, delivery_ts=last_ts)
        await self._adapter._set_origin_field(session, last_delivered_at=last_ts.isoformat())  # pylint: disable=protected-access

        # Update cursor if no adapter is actively tracking an output message for this session.
        if last_ts:
            from teleclaude.core.agent_coordinator._helpers import (  # pylint: disable=import-outside-toplevel
                _has_active_output_message,
            )

            fresh = await db.get_session(session_id)
            is_active = fresh is not None and await _has_active_output_message(fresh)
            if not is_active:
                await db.update_session(session_id, **{SessionField.LAST_TOOL_DONE_AT.value: last_ts.isoformat()})
