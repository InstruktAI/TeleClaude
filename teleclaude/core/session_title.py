"""Canonical session title rules and transcript-driven title generation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.roles import Role, resolve_role
from teleclaude.core.session_transcript import session_transcript
from teleclaude.core.summarizer import generate_session_title
from teleclaude.utils.transcript import extract_last_authored_exchange

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_title_projection_signatures: dict[str, tuple[tuple[str, str], ...]] = {}
_COMMAND_TITLE_TEMPLATE = "{command} {args}"
_USER_ROLE = "user"
_ASSISTANT_ROLE = "assistant"
_REPLY_SEPARATOR = "\n\n"


def compose_command_session_title(command: str, args: str, *, role: str | None = None) -> str:
    """Render a command session title from its catalog role when available, otherwise its command."""
    resolved_role = resolve_role(role)
    title_identity = resolved_role.name.value if isinstance(resolved_role, Role) else command
    return _COMMAND_TITLE_TEMPLATE.format(command=title_identity, args=args).strip()


def clear_title_projection_state(session_id: str) -> None:
    """Drop cached title-dedupe state for a session."""
    _title_projection_signatures.pop(session_id, None)


async def generate_session_title_from_transcript(session: Session, adapter_client: AdapterClient) -> Session:
    """Update semantic title from the last completed transcript turn, if allowed.

    Title is a UI surface, not a transcript surface. When the value actually
    changes (dedup at this emit site), the new title is written to DB and
    pushed straight to the adapter via the routed update_channel_title call.
    No event broadcast, no projection: this is not a transcript projection.
    """
    if session.command is not None:
        return session
    current_title = (session.title or "").strip()

    transcript = session_transcript(session)
    if transcript is None:
        return session

    exchange = await asyncio.to_thread(extract_last_authored_exchange, transcript.path, transcript.agent)
    if exchange is None or not exchange.authored_text.strip() or not exchange.assistant_texts:
        return session

    finalized_turn = [
        (_USER_ROLE, exchange.authored_text),
        (_ASSISTANT_ROLE, _REPLY_SEPARATOR.join(exchange.assistant_texts)),
    ]
    user_marker = exchange.timestamp.isoformat() if exchange.timestamp is not None else exchange.authored_text
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
    logger.info("Updated session title from transcript: %s", new_title)
    await adapter_client.update_channel_title(session)
    return session
