"""SSE streaming endpoint for the web interface.

POST /api/chat/stream — returns AI SDK v5 UIMessage Stream.
Two modes: history replay then live tail of the JSONL transcript.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict

from teleclaude.api.transcript_converter import (
    convert_entry,
    convert_session_status,
    message_finish,
    message_start,
    stream_done,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.utils.transcript import _iter_claude_entries, _iter_codex_entries, _parse_timestamp

logger = get_logger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

LIVE_POLL_INTERVAL_S = 1.0
LIVE_IDLE_TIMEOUT_S = 300.0


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ChatStreamMessage(BaseModel):
    """A single message in the chat stream request."""

    model_config = ConfigDict(frozen=True)

    role: str
    content: str


class ChatStreamRequest(BaseModel):
    """Request body for POST /api/chat/stream."""

    model_config = ConfigDict(frozen=True)

    sessionId: str
    since_timestamp: str | None = None
    messages: list[ChatStreamMessage] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_transcript_chain(session: object) -> list[str]:
    """Build ordered list of transcript file paths from a session record."""
    chain: list[str] = []
    transcript_files = getattr(session, "transcript_files", None)
    if transcript_files:
        try:
            stored = json.loads(transcript_files)
            if isinstance(stored, list):
                chain = [str(p) for p in stored if p]
        except (json.JSONDecodeError, TypeError):
            pass
    native_log = getattr(session, "native_log_file", None)
    if native_log and native_log not in chain:
        chain.append(native_log)
    return chain


def _get_agent_name(session: object) -> AgentName:
    """Resolve agent name from session, defaulting to Claude."""
    active_agent = getattr(session, "active_agent", None) or "claude"
    try:
        return AgentName.from_str(active_agent)
    except ValueError:
        return AgentName.CLAUDE


def _iter_entries_for_file(
    path: str,
    agent_name: AgentName,
) -> list[dict[str, object]]:  # guard: loose-dict - External transcript entries
    """Load transcript entries from a single file."""
    p = Path(path).expanduser()
    if not p.exists():
        return []
    if agent_name == AgentName.CLAUDE:
        return list(_iter_claude_entries(p))
    if agent_name == AgentName.CODEX:
        return list(_iter_codex_entries(p))
    # Gemini uses JSON, not JSONL — skip for live tailing
    return list(_iter_claude_entries(p))


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------


async def _stream_sse(
    session_id: str,
    since_timestamp: str | None,
    user_message: str | None,
) -> AsyncIterator[str]:
    """Generate SSE events: history replay then live tail.

    Yields SSE-formatted strings conforming to AI SDK v5 UIMessage Stream.
    """
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    agent_name = _get_agent_name(session)
    chain = _get_transcript_chain(session)

    message_id = f"msg-{session_id[:8]}"
    yield message_start(message_id)
    yield convert_session_status("streaming", session_id)

    # --- Task 5: Message ingestion ---
    if user_message:
        tmux_session_name = getattr(session, "tmux_session_name", None)
        if tmux_session_name:
            from teleclaude.core import tmux_bridge

            await tmux_bridge.send_keys_existing_tmux(
                tmux_session_name,
                user_message,
                send_enter=True,
                active_agent=getattr(session, "active_agent", None),
            )

    # --- History replay ---
    since_dt = _parse_timestamp(since_timestamp) if since_timestamp else None
    for file_path in chain:
        entries = _iter_entries_for_file(file_path, agent_name)
        for entry in entries:
            if since_dt:
                entry_ts = entry.get("timestamp")
                if isinstance(entry_ts, str):
                    entry_dt = _parse_timestamp(entry_ts)
                    if entry_dt and entry_dt <= since_dt:
                        continue
            for sse_event in convert_entry(entry):
                yield sse_event

    # --- Live tail ---
    if not chain:
        yield message_finish(message_id)
        yield stream_done()
        return

    live_file = chain[-1]
    if not Path(live_file).exists():
        yield message_finish(message_id)
        yield stream_done()
        return

    # Track file position for incremental reads
    file_size = os.path.getsize(live_file)
    idle_elapsed = 0.0

    while idle_elapsed < LIVE_IDLE_TIMEOUT_S:
        await asyncio.sleep(LIVE_POLL_INTERVAL_S)

        # Check if session is still active
        refreshed = await db.get_session(session_id)
        if not refreshed or getattr(refreshed, "closed_at", None):
            yield convert_session_status("closed", session_id)
            break

        # Check for new transcript data
        if not Path(live_file).exists():
            break

        current_size = os.path.getsize(live_file)
        if current_size <= file_size:
            idle_elapsed += LIVE_POLL_INTERVAL_S
            continue

        # Read new content
        idle_elapsed = 0.0
        try:
            with open(live_file, "rb") as f:
                f.seek(file_size)
                new_bytes = f.read(current_size - file_size)
            file_size = current_size

            new_text = new_bytes.decode("utf-8", errors="ignore")
            for line in new_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry_value: object = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry_value, dict):
                    entry: dict[str, object] = entry_value  # guard: loose-dict - JSONL parse
                    for sse_event in convert_entry(entry):
                        yield sse_event
        except OSError as exc:
            logger.warning("Error reading live transcript %s: %s", live_file, exc)
            break

        # Check if transcript file rotated (new native_log_file)
        refreshed = await db.get_session(session_id)
        if refreshed:
            new_log = getattr(refreshed, "native_log_file", None)
            if new_log and new_log != live_file and Path(new_log).exists():
                live_file = new_log
                file_size = 0

    yield message_finish(message_id)
    yield stream_done()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/stream")
async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:
    """SSE streaming endpoint for the web interface."""
    # Extract user message if present
    user_message: str | None = None
    if request.messages:
        for msg in reversed(request.messages):
            if msg.role == "user" and msg.content.strip():
                user_message = msg.content
                break

    generator = _stream_sse(
        session_id=request.sessionId,
        since_timestamp=request.since_timestamp,
        user_message=user_message,
    )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
