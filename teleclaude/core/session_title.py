"""Canonical session title rules and transcript-driven title generation."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionTitleChangedContext, TeleClaudeEvents
from teleclaude.core.summarizer import generate_session_title
from teleclaude.utils.transcript import collect_transcript_messages, extract_last_user_message_with_timestamp

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_title_projection_signatures: dict[str, tuple[tuple[str, str], ...]] = {}


def initial_session_title(initial_input: str | None) -> str:
    """Return the birth title for a session from its initial input, if any."""
    if not initial_input:
        return "Untitled"
    if initial_input.lstrip().startswith("/"):
        return initial_input
    return "Untitled"


def clear_title_projection_state(session_id: str) -> None:
    """Drop cached title-dedupe state for a session."""
    _title_projection_signatures.pop(session_id, None)


async def generate_session_title_from_transcript(session: Session) -> Session:
    """Update semantic title from the last completed transcript turn, if allowed."""
    current_title = (session.title or "").strip()
    if current_title.startswith("/"):
        return session

    transcript_path = session.native_log_file
    active_agent = session.active_agent
    if not transcript_path or not active_agent:
        return session

    try:
        agent_name = AgentName.from_str(active_agent)
    except ValueError:
        return session

    latest_user = await asyncio.to_thread(extract_last_user_message_with_timestamp, transcript_path, agent_name)
    if latest_user is None:
        return session
    latest_user_text, latest_user_ts = latest_user
    if not latest_user_text.strip():
        return session

    messages = await asyncio.to_thread(collect_transcript_messages, transcript_path, agent_name)
    if not messages:
        return session

    last_user_idx: int | None = None
    for idx in range(len(messages) - 1, -1, -1):
        role, _text = messages[idx]
        if role == "user":
            last_user_idx = idx
            break
    if last_user_idx is None:
        return session

    user_role, user_text = messages[last_user_idx]
    assistant_parts = [text for role, text in messages[last_user_idx + 1 :] if role == "assistant" and text.strip()]
    if user_role != "user" or not user_text.strip() or not assistant_parts:
        return session

    finalized_turn = [("user", user_text), ("assistant", "\n\n".join(assistant_parts))]
    user_marker = latest_user_ts.isoformat() if isinstance(latest_user_ts, datetime) else latest_user_text
    turn_signature = (("user", user_marker),)
    if _title_projection_signatures.get(session.session_id) == turn_signature:
        return session

    try:
        new_title = await generate_session_title(finalized_turn)
    except Exception as exc:
        logger.warning("Title summarization failed: %s", exc)
        return session

    _title_projection_signatures[session.session_id] = turn_signature
    if not new_title or new_title == current_title:
        return session

    await db.update_session(session.session_id, title=new_title)
    session.title = new_title
    event_bus.emit(
        TeleClaudeEvents.SESSION_TITLE_CHANGED,
        SessionTitleChangedContext(session_id=session.session_id, title=new_title),
    )
    logger.info("Updated session title from transcript: %s", new_title)
    return session
