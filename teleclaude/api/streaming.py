"""SSE streaming endpoint for the web interface.

POST /api/chat/stream — returns AI SDK v5 UIMessage Stream.
Two modes: history replay then live tail of the JSONL transcript.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict, Field

from teleclaude.api.session_access import check_session_access
from teleclaude.api.transcript_converter import (
    convert_projected_block,
    convert_session_status,
    message_finish,
    message_start,
    stream_done,
)
from teleclaude.core.agents import AgentName, resolve_parser_agent
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.db_models import Session
from teleclaude.core.models import JsonDict
from teleclaude.output_projection.conversation_projector import project_entries
from teleclaude.output_projection.models import ProjectionSurface, VisibilityPolicy, visibility_policy_for_person
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.utils.transcript import (
    TranscriptTailCursor,
    TranscriptTailReadError,
    _iter_claude_entries,
    _iter_codex_entries,
    _iter_gemini_entries,
    read_appended_jsonl_entries,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Canonical lifecycle status mapping
# ---------------------------------------------------------------------------

_CLOSED_STATUSES = frozenset({"closed"})
_ERROR_STATUSES = frozenset({"error"})
_COMPLETED_STATUSES = frozenset({"completed"})


def _map_lifecycle_to_sse_status(lifecycle_status: str | None) -> str:
    """Map canonical session lifecycle_status to Web SSE status value.

    Derives SSE status from the canonical lifecycle_status field established
    by ucap-truthful-session-status. Prevents hardcoded bypass strings.

    Args:
        lifecycle_status: Canonical lifecycle status from session DB field.

    Returns:
        SSE status string for ``data-session-status`` event.
    """
    if lifecycle_status in _CLOSED_STATUSES:
        return "closed"
    if lifecycle_status in _ERROR_STATUSES:
        return "error"
    if lifecycle_status in _COMPLETED_STATUSES:
        return "completed"
    return "streaming"


router = APIRouter(prefix="/api/chat", tags=["chat"])

LIVE_POLL_INTERVAL_S = 1.0
LIVE_IDLE_TIMEOUT_S = 300.0


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ChatStreamMessage(BaseModel):
    """A single message in the chat stream request."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant", "system"]
    content: str


class ChatStreamRequest(BaseModel):
    """Request body for POST /api/chat/stream."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., min_length=1, alias="sessionId")
    since_timestamp: str | None = None
    messages: list[ChatStreamMessage] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_transcript_chain(session: Session) -> list[str]:
    """Build ordered list of transcript file paths from a session record."""
    chain: list[str] = []
    if session.transcript_files:
        try:
            stored = json.loads(session.transcript_files)
            if isinstance(stored, list):
                chain = [str(p) for p in stored if p]
        except (json.JSONDecodeError, TypeError):
            pass
    if session.native_log_file and session.native_log_file not in chain:
        chain.append(session.native_log_file)
    return chain


def _get_agent_name(session: Session) -> AgentName:
    """Resolve agent name from session, defaulting to Claude."""
    return resolve_parser_agent(session.active_agent)


def _iter_entries_for_file(
    path: str,
    agent_name: AgentName,
) -> list[JsonDict]:
    """Load transcript entries from a single file."""
    p = Path(path).expanduser()
    if not p.exists():
        return []
    if agent_name == AgentName.CLAUDE:
        return list(_iter_claude_entries(p))
    if agent_name == AgentName.CODEX:
        return list(_iter_codex_entries(p))
    if agent_name == AgentName.GEMINI:
        return list(_iter_gemini_entries(p))
    return list(_iter_claude_entries(p))


async def _emit_initial_stream_events(
    session: Session,
    session_id: str,
    message_id: str,
) -> AsyncIterator[str]:
    """Emit the initial stream start and status events."""
    yield message_start(message_id)

    initial_status = _map_lifecycle_to_sse_status(session.lifecycle_status)
    logger.info(
        "Web lane stream start",
        lane="web",
        session_id=session_id,
        event_type="data-session-status",
        status=initial_status,
        lifecycle_status=session.lifecycle_status,
    )
    yield convert_session_status(initial_status, session_id)


async def _deliver_user_message(
    session_id: str,
    user_message: str | None,
) -> AsyncIterator[str]:
    """Send the incoming user message through the canonical command path."""
    if not user_message:
        return

    cmd = ProcessMessageCommand(
        session_id=session_id,
        text=user_message,
        origin="web",
    )
    try:
        await get_command_service().process_message(cmd)
    except RuntimeError:
        logger.warning(
            "Web lane message delivery failed",
            lane="web",
            session_id=session_id,
            event_type="data-session-status",
            exc_info=True,
        )
        yield convert_session_status("error", session_id)


async def _replay_history(
    chain: list[str],
    agent_name: AgentName,
    since_timestamp: str | None,
    policy: VisibilityPolicy,
) -> AsyncIterator[str]:
    """Replay existing transcript history with the web visibility policy."""
    for file_path in chain:
        entries = _iter_entries_for_file(file_path, agent_name)
        for projected in project_entries(entries, policy, since=since_timestamp):
            for sse_event in convert_projected_block(projected):
                yield sse_event


def _stream_is_live(chain: list[str]) -> bool:
    """Check whether live tailing can start for the current transcript chain."""
    return bool(chain) and Path(chain[-1]).exists()


async def _emit_stream_finish(message_id: str) -> AsyncIterator[str]:
    """Emit the terminal stream events."""
    yield message_finish(message_id)
    yield stream_done()


async def _load_live_transcript_events(
    live_file: str,
    *,
    cursor: TranscriptTailCursor,
    session_id: str,
    policy: VisibilityPolicy,
) -> tuple[TranscriptTailCursor, list[str]]:
    """Read newly appended transcript data and convert it into SSE events."""
    events: list[str] = []
    batch = read_appended_jsonl_entries(live_file, cursor)
    for entry in batch.entries:
        for projected in project_entries([entry], policy):
            events.extend(convert_projected_block(projected))

    return batch.cursor, events


async def _resolve_stream_closure(session_id: str) -> tuple[bool, str | None]:
    """Check whether the stream should close based on canonical lifecycle status."""
    refreshed = await db.get_session(session_id)
    if refreshed and refreshed.lifecycle_status not in _CLOSED_STATUSES:
        return False, refreshed.native_log_file

    close_reason = "not_found" if not refreshed else refreshed.lifecycle_status
    logger.info(
        "Web lane stream closed",
        lane="web",
        session_id=session_id,
        event_type="data-session-status",
        reason=close_reason,
    )
    return True, None


async def _tail_live_transcript(
    session_id: str,
    live_file: str,
    policy: VisibilityPolicy,
) -> AsyncIterator[str]:
    """Tail the live transcript file and yield incremental SSE events."""
    try:
        cursor = TranscriptTailCursor(offset=os.path.getsize(live_file))
    except OSError:
        logger.warning(
            "Unable to initialize live transcript tail",
            lane="web",
            session_id=session_id,
            event_type="data-session-status",
            exc_info=True,
        )
        yield convert_session_status("error", session_id)
        return
    idle_elapsed = 0.0
    current_live_file = live_file

    while idle_elapsed < LIVE_IDLE_TIMEOUT_S:
        await asyncio.sleep(LIVE_POLL_INTERVAL_S)

        should_close, rotated_live_file = await _resolve_stream_closure(session_id)
        if should_close:
            yield convert_session_status("closed", session_id)
            return

        if not Path(current_live_file).exists():
            return

        try:
            current_size = os.path.getsize(current_live_file)
        except OSError:
            logger.warning(
                "Unable to stat live transcript during tail",
                lane="web",
                session_id=session_id,
                event_type="data-session-status",
                exc_info=True,
            )
            yield convert_session_status("error", session_id)
            return
        if current_size <= cursor.offset:
            idle_elapsed += LIVE_POLL_INTERVAL_S
        else:
            idle_elapsed = 0.0
            try:
                next_cursor, live_events = await _load_live_transcript_events(
                    current_live_file,
                    cursor=cursor,
                    session_id=session_id,
                    policy=policy,
                )
            except TranscriptTailReadError:
                logger.warning(
                    "Unable to read live transcript during tail",
                    lane="web",
                    session_id=session_id,
                    event_type="data-session-status",
                    exc_info=True,
                )
                yield convert_session_status("error", session_id)
                return
            if next_cursor == cursor:
                return
            cursor = next_cursor
            for sse_event in live_events:
                yield sse_event

        if rotated_live_file and rotated_live_file != current_live_file and Path(rotated_live_file).exists():
            current_live_file = rotated_live_file
            cursor = TranscriptTailCursor()


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------


async def _stream_sse(
    session: Session,
    session_id: str,
    since_timestamp: str | None,
    user_message: str | None,
    policy: VisibilityPolicy,
) -> AsyncIterator[str]:
    """Generate SSE events: history replay then live tail.

    Yields SSE-formatted strings conforming to AI SDK v5 UIMessage Stream.
    Derives session status from canonical lifecycle_status (no hardcoded bypass).
    """
    agent_name = _get_agent_name(session)
    chain = _get_transcript_chain(session)
    message_id = f"msg-{session_id}"
    async for sse_event in _emit_initial_stream_events(session, session_id, message_id):
        yield sse_event

    async for sse_event in _deliver_user_message(session_id, user_message):
        yield sse_event

    async for sse_event in _replay_history(chain, agent_name, since_timestamp, policy):
        yield sse_event

    if not _stream_is_live(chain):
        async for sse_event in _emit_stream_finish(message_id):
            yield sse_event
        return

    async for sse_event in _tail_live_transcript(session_id, chain[-1], policy):
        yield sse_event

    async for sse_event in _emit_stream_finish(message_id):
        yield sse_event


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/stream")
async def chat_stream(http_request: Request, request: ChatStreamRequest) -> StreamingResponse:
    """SSE streaming endpoint for the web interface."""
    await check_session_access(http_request, request.session_id)

    # Validate session exists before creating streaming response
    session = await db.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Extract user message if present
    user_message: str | None = None
    if request.messages:
        for msg in reversed(request.messages):
            if msg.role == "user" and msg.content.strip():
                user_message = msg.content
                break

    recipient_email = http_request.headers.get("x-web-user-email") or session.human_email
    recipient_role = http_request.headers.get("x-web-user-role") or session.human_role
    policy = visibility_policy_for_person(
        human_role=recipient_role,
        person_email=recipient_email,
        surface=ProjectionSurface.WEB,
    )

    generator = _stream_sse(
        session=session,
        session_id=request.session_id,
        since_timestamp=request.since_timestamp,
        user_message=user_message,
        policy=policy,
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
