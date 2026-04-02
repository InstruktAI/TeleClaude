"""Adapter-owned output cadence loop.

Each UI adapter runs its own cadence timer. On each tick, the adapter
checks active sessions, pulls transcripts, renders output, and sends
if content has changed. Core only signals activity via last_activity_at;
no output data flows from core to adapters.

The cadence is the single authority over rendering decisions. It reads
the transcript file, derives what to render, detects turn boundaries
from user messages, and manages its own delivery bookkeeping.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import JsonDict
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)
from teleclaude.utils.transcript._extraction import _extract_text_from_content
from teleclaude.utils.transcript._iterators import _get_entries_for_agent
from teleclaude.utils.transcript._parsers import normalize_transcript_entry_message
from teleclaude.utils.transcript._tool_calls import _is_user_tool_result_only_message
from teleclaude.utils.transcript._utils import _parse_timestamp

if TYPE_CHECKING:
    from teleclaude.adapters.ui_adapter import UiAdapter
    from teleclaude.core.models import Session

logger = get_logger(__name__)

# Sessions with activity within this window are candidates for output pull.
_ACTIVITY_WINDOW = timedelta(seconds=120)

# Sentinel stored in _last_seen_user_ts when a genuine user message exists but its
# timestamp is absent or unparseable. Prevents re-firing on repeated ticks while
# still triggering a boundary on first encounter.
_UNPARSEABLE_TS_SENTINEL: datetime = datetime.min.replace(tzinfo=UTC)


def _find_last_genuine_user_boundary(entries: list[JsonDict]) -> int:
    """Return the index of the last genuine user message in a transcript entry list.

    Returns 0 if no genuine user message is found.
    """
    for i in range(len(entries) - 1, -1, -1):
        message = normalize_transcript_entry_message(entries[i])
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        if _is_user_tool_result_only_message(message):
            continue
        return i
    return 0


class OutputCadenceLoop:
    """Per-adapter cadence loop that pulls and renders session output."""

    def __init__(self, adapter: UiAdapter, interval_seconds: float) -> None:
        self._adapter = adapter
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        # Per-session output lock to prevent concurrent renders.
        self._locks: dict[str, asyncio.Lock] = {}
        # Per-session turn tracking: timestamp of last genuine user message seen.
        self._last_seen_user_ts: dict[str, datetime | None] = {}

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
        active_ids = {s.session_id for s in active_sessions}
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
        # Clean up turn tracking for sessions no longer in the active window.
        stale = set(self._last_seen_user_ts) - active_ids
        for sid in stale:
            del self._last_seen_user_ts[sid]

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

    def _detect_turn_boundary(self, session: Session, transcript_path: str, agent_name: AgentName) -> bool:
        """Detect if a new turn has started by scanning for the last genuine user message.

        Returns True if a new turn was detected (and updates tracked timestamp).
        """
        entries = _get_entries_for_agent(transcript_path, agent_name)
        if not entries:
            return False

        # Scan backwards for last genuine user message.
        found_genuine_user = False
        last_user_ts: datetime | None = None
        for i in range(len(entries) - 1, -1, -1):
            entry = entries[i]
            message = normalize_transcript_entry_message(entry)
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            if _is_user_tool_result_only_message(message):
                continue
            # Found a genuine user message — extract its timestamp.
            found_genuine_user = True
            raw_ts = entry.get("timestamp")
            if isinstance(raw_ts, str):
                last_user_ts = _parse_timestamp(raw_ts)
            break

        session_id = session.session_id
        prev_ts = self._last_seen_user_ts.get(session_id)

        if not found_genuine_user:
            # No genuine user message in transcript — no turn boundary.
            if session_id not in self._last_seen_user_ts:
                self._last_seen_user_ts[session_id] = None
            return False

        if last_user_ts is None:
            # Genuine user message found but timestamp is absent or unparseable.
            # Use a sentinel so repeated ticks do not re-fire the boundary.
            if prev_ts != _UNPARSEABLE_TS_SENTINEL:
                self._last_seen_user_ts[session_id] = _UNPARSEABLE_TS_SENTINEL
                return True
            return False

        if prev_ts is None or last_user_ts > prev_ts:
            self._last_seen_user_ts[session_id] = last_user_ts
            return True

        return False

    async def _pull_unlocked(self, session: Session) -> None:
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

        # Detect turn boundaries from the transcript file.
        if self._detect_turn_boundary(session, transcript_path, agent_name):
            await self._adapter._clear_output_message_id(session)  # pylint: disable=protected-access
            await self._adapter._set_char_offset(session, 0)  # pylint: disable=protected-access

        # Determine rendering mode from session metadata at render time.
        is_origin_mode = session.last_input_origin == self._adapter.ADAPTER_KEY or not session.last_input_origin

        if is_origin_mode:
            await self._render_origin_mode(session, transcript_path, agent_name)
        else:
            await self._render_reflection_mode(session, transcript_path, agent_name)

    async def _render_origin_mode(self, session: Session, transcript_path: str, agent_name: AgentName) -> None:
        """Origin mode: render agent output only from the transcript file."""
        # File-derived rendering: no external cursor, the function finds the
        # last user boundary and returns assistant messages after it.
        assistant_messages = get_assistant_messages_since(transcript_path, agent_name)
        if not assistant_messages:
            return

        include_tools = True
        renderable_block_count = count_renderable_assistant_blocks(
            transcript_path,
            agent_name,
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
                include_timestamps=False,
            )
        else:
            message, last_ts = render_clean_agent_output(transcript_path, agent_name)

        if not message or not last_ts:
            return

        logger.debug(
            "Cadence output: session=%s adapter=%s len=%d multi=%s",
            session.session_id,
            self._adapter.ADAPTER_KEY,
            len(message),
            is_multi,
        )
        await self._adapter.send_threaded_output(session, message, multi_message=is_multi)

    async def _render_reflection_mode(self, session: Session, transcript_path: str, agent_name: AgentName) -> None:
        """Reflection mode: render both user and agent messages as a unified belt."""
        belt_text, _ = self._build_reflection_belt(session, transcript_path, agent_name)
        if not belt_text:
            return

        logger.debug(
            "Cadence reflection output: session=%s adapter=%s len=%d",
            session.session_id,
            self._adapter.ADAPTER_KEY,
            len(belt_text),
        )
        await self._adapter.send_threaded_output(session, belt_text, multi_message=False)

    def _build_reflection_belt(  # pylint: disable=too-many-locals
        self, session: Session, transcript_path: str, agent_name: AgentName
    ) -> tuple[str | None, datetime | None]:
        """Build the unified content belt for reflection mode rendering."""
        entries = _get_entries_for_agent(transcript_path, agent_name)
        if not entries:
            return None, None

        start_idx = _find_last_genuine_user_boundary(entries)
        belt_parts: list[str] = []
        last_ts: datetime | None = None

        # Resolve display name once for user messages.
        input_origin = session.last_input_origin or ""
        resolver = get_identity_resolver()
        identity = resolver.resolve(input_origin, session.get_origin_section(input_origin))
        try:
            display_name = identity.display_name
        except ValueError:
            display_name = input_origin or "User"

        for entry in entries[start_idx:]:
            message = normalize_transcript_entry_message(entry)
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            content = message.get("content")
            raw_ts = entry.get("timestamp")
            if isinstance(raw_ts, str):
                parsed = _parse_timestamp(raw_ts)
                if parsed:
                    last_ts = parsed

            if role == "user" and not _is_user_tool_result_only_message(message):
                text = _extract_text_from_content(content, "user")
                if text:
                    belt_parts.append(f"> **{display_name}:** {text}\n\n")
            elif role == "assistant":
                text = _extract_text_from_content(content, "assistant")
                if text:
                    belt_parts.append(text)

        if not belt_parts:
            return None, None
        return "".join(belt_parts), last_ts
