"""Direct-conversation ignition helpers: caller resolution, intro framing, link reuse.

Resolves the caller session for a ``--direct`` ignition path, renders the
ignition intro from the human-facing message envelope, and creates or
reuses the direct link between caller and target. Independent of the route
module's daemon-client dispatch state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.sessions_responses import active_direct_link_response as _active_direct_link_response
from teleclaude.api_models import CreateSessionRequest, SendMessageResponseDTO
from teleclaude.config import config
from teleclaude.core.conversation_messages import format_peer_header
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import UnidentifiableCallerError
from teleclaude.core.models import HumanFacingMessage, MessageAuthor
from teleclaude.core.session_listeners import create_or_reuse_direct_link, resolve_link_for_sender_target

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_DIRECT_LINK_UNRESOLVED_DETAIL = "failed to resolve direct link"
_HEADER_ONLY_BODY = ""
_EMPTY_MESSAGE_TEXT = ""
_INTRO_SECTION_SEPARATOR = "\n\n"
_INTRO_LINE_SEPARATOR = "\n"

# The static portion of the ignition intro; the caller's peer introduction
# text is appended as the final line at render time.
_DIRECT_CONVERSATION_INTRO_RULES: tuple[str, ...] = (
    "Rules:",
    "- Do not use `telec sessions send` for follow-up messages.",
    "- Just talk in normal output; your turn-complete output is delivered automatically.",
    "- Default emit state is false. Reply only if your output changes the peer's next action.",
    "- Valid replies answer a question, report a blocker or decision point, provide new information, or deliver a result or artifact.",
    "- Each cross-shared segment carries its own author header as framing, not content; only act on what a segment's body says.",
    "- Do not acknowledge, echo, narrate, or send status-only output such as `idle` or `done`.",
    "",
    "Protocol:",
    "- Agent-only default: `PROTOCOL: phase-locked (L4 inhale/hold, L3 exhale), artifacts in prose`",
    "- Human-observed default: `PROTOCOL: L1 prose, human in loop`",
    "",
    "Peer introduction:",
)


async def _resolve_direct_caller_session(caller_session_id: str) -> Session:
    """Resolve the caller session for a direct-conversation ignition path.

    Raises ``UnidentifiableCallerError`` when the caller session row is
    missing, or has no resolvable agent identity to render as the segment
    author. Ignition rejects an unidentifiable caller rather than proceeding
    with a defaulted identity.
    """
    caller_session = await db.get_session(caller_session_id)
    if caller_session is None or not caller_session.active_agent:
        raise UnidentifiableCallerError(caller_session_id=caller_session_id)
    return caller_session


def _format_direct_conversation_intro(
    *,
    caller_session: Session,
    message_text: str,
) -> str:
    """Wrap the first direct-conversation message with the required operating instructions."""
    assert caller_session.active_agent is not None  # guaranteed by _resolve_direct_caller_session
    author = MessageAuthor.for_agent(
        session_id=caller_session.session_id,
        active_agent=caller_session.active_agent,
        thinking_mode=caller_session.thinking_mode,
    )
    header = format_peer_header(
        HumanFacingMessage(author=author, occurred_at=datetime.now(UTC), body=_HEADER_ONLY_BODY)
    )
    body = _INTRO_LINE_SEPARATOR.join((*_DIRECT_CONVERSATION_INTRO_RULES, message_text.strip()))
    return f"{header}{_INTRO_SECTION_SEPARATOR}{body}"


async def _build_direct_launch_message(  # pyright: ignore[reportUnusedFunction]
    request: CreateSessionRequest,
    identity: CallerIdentity,
) -> tuple[str, Session | None]:
    """Format the initial direct-conversation message and return caller session."""
    if not request.direct or not identity.session_id or request.message is None:
        return request.message or _EMPTY_MESSAGE_TEXT, None

    caller_session = await _resolve_direct_caller_session(identity.session_id)
    return (
        _format_direct_conversation_intro(
            caller_session=caller_session,
            message_text=request.message,
        ),
        caller_session,
    )


@dataclass(frozen=True)
class DirectMessageContext:
    """Resolved caller/target metadata for direct conversations."""

    caller_session: Session
    caller_label: str
    target_label: str
    caller_computer: str
    target_computer: str


async def _build_direct_message_context(  # pyright: ignore[reportUnusedFunction]
    caller_session_id: str,
    target_session_id: str,
    target_session: Session | None,
) -> DirectMessageContext:
    """Load caller/target display context for direct messaging."""
    caller_session = await _resolve_direct_caller_session(caller_session_id)
    resolved_target_session = target_session or await db.get_session(target_session_id)
    return DirectMessageContext(
        caller_session=caller_session,
        caller_label=caller_session.title or caller_session_id,
        target_label=(
            resolved_target_session.title
            if resolved_target_session and resolved_target_session.title
            else target_session_id
        ),
        caller_computer=caller_session.computer_name,
        target_computer=resolved_target_session.computer_name if resolved_target_session else config.computer.name,
    )


async def _create_direct_link(  # pyright: ignore[reportUnusedFunction]
    caller_session_id: str,
    target_session_id: str,
    context: DirectMessageContext,
) -> tuple[str, int] | SendMessageResponseDTO:
    """Create or resolve the active direct link for this caller/target pair."""
    link_ctx = await resolve_link_for_sender_target(
        sender_session_id=caller_session_id,
        target_session_id=target_session_id,
    )
    if link_ctx:
        return _active_direct_link_response(link_ctx[0].link_id, already_active=True)

    link, _ = await create_or_reuse_direct_link(
        caller_session_id=caller_session_id,
        target_session_id=target_session_id,
        caller_name=context.caller_label,
        target_name=context.target_label,
        caller_computer=context.caller_computer,
        target_computer=context.target_computer,
    )
    resolved_link_ctx = await resolve_link_for_sender_target(
        sender_session_id=caller_session_id,
        target_session_id=target_session_id,
    )
    if not resolved_link_ctx:
        raise HTTPException(status_code=500, detail=_DIRECT_LINK_UNRESOLVED_DETAIL)
    return link.link_id, len(resolved_link_ctx[1])


async def _reject_existing_direct_link(  # pyright: ignore[reportUnusedFunction]
    session_id: str,
    identity: CallerIdentity,
) -> SendMessageResponseDTO | None:
    """Return the standard error response if a work send conflicts with a direct link."""
    if not identity.session_id:
        return None

    existing_link = await resolve_link_for_sender_target(
        sender_session_id=identity.session_id,
        target_session_id=session_id,
    )
    if not existing_link:
        return None
    return _active_direct_link_response(existing_link[0].link_id, already_active=False)
