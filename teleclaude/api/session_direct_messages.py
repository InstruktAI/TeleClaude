"""Direct-conversation ignition helpers: caller resolution, intro framing, link reuse.

Resolves the caller session for a ``--direct`` ignition path, renders the
ignition intro from the human-facing message envelope, and creates or
reuses the direct link between caller and target. Independent of the route
module's daemon-client dispatch state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.sessions_responses import active_direct_link_response as _active_direct_link_response
from teleclaude.api_models import SendMessageResponseDTO
from teleclaude.config import config
from teleclaude.core.command_dispatch import dispatch_command
from teleclaude.core.conversation_bundle_delivery import persist_direct_ignition_bundle
from teleclaude.core.conversation_messages import format_peer_message
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import UnidentifiableCallerError
from teleclaude.core.models import HumanFacingMessage, MessageAuthor, MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    create_or_reuse_direct_link,
    get_peer_members,
    resolve_link_for_sender_target,
)
from teleclaude.core.session_status import is_session_terminal as _terminal
from teleclaude.types.commands import ProcessMessageCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_DIRECT_LINK_UNRESOLVED_DETAIL = "failed to resolve direct link"
_EMPTY_MESSAGE_TEXT = ""
_INTRO_LINE_SEPARATOR = "\n"
_DIRECT_IGNITION_BUNDLE_PERSISTED_EVENT = "direct_ignition_bundle_persisted"

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


def _direct_conversation_intro_body(message_text: str) -> str:
    """Build the authored body that direct ignition persists and delivers."""
    return _INTRO_LINE_SEPARATOR.join((*_DIRECT_CONVERSATION_INTRO_RULES, message_text.strip()))


def _format_direct_conversation_intro(  # pyright: ignore[reportUnusedFunction]
    *,
    author: MessageAuthor,
    occurred_at: datetime,
    message_text: str,
) -> str:
    """Render direct ignition through the canonical peer-message formatter."""
    return format_peer_message(
        messages=[
            HumanFacingMessage(
                author=author,
                occurred_at=occurred_at,
                body=_direct_conversation_intro_body(message_text),
            )
        ]
    )


async def _deliver_direct_message(  # pyright: ignore[reportUnusedFunction]
    *,
    client: AdapterClient,
    link_id: str,
    caller_session_id: str,
    session_id: str,
    message_text: str,
    message_body: str,
    metadata: MessageMetadata,
    caller_author: MessageAuthor,
    caller_job_role: str | None,
    occurred_at: datetime,
    ignition_path: str,
) -> int:
    """Persist and deliver one direct ignition to every active peer."""
    peers = await get_peer_members(link_id=link_id, sender_session_id=caller_session_id)
    delivery_targets = [peer.session_id for peer in peers] or [session_id]
    delivered_to = 0
    rendered_message = format_peer_message(
        messages=[HumanFacingMessage(author=caller_author, occurred_at=occurred_at, body=message_body)]
    )
    for target_id in delivery_targets:
        target_for_delivery = await db.get_session(target_id)
        if not target_for_delivery:
            logger.info("Skipping direct delivery to missing session %s", target_id)
            continue
        if _terminal(lifecycle_status=target_for_delivery.lifecycle_status, closed_at=target_for_delivery.closed_at):
            logger.info("Skipping direct delivery to closed session %s", target_id)
            continue
        source_message_id = await persist_direct_ignition_bundle(
            link_id=link_id,
            source_session_id=caller_session_id,
            target_session_id=target_id,
            author=caller_author,
            author_job_role=caller_job_role,
            occurred_at=occurred_at,
            body=message_body,
        )
        logger.info(
            _DIRECT_IGNITION_BUNDLE_PERSISTED_EVENT,
            outcome="persisted",
            ignition_path=ignition_path,
            link_id=link_id,
            source_session_id=caller_session_id,
            target_session_id=target_id,
            bundle_key=source_message_id,
            render_equals_persisted=rendered_message == message_text,
        )
        await dispatch_command(
            client,
            ProcessMessageCommand(
                session_id=target_id,
                text=message_text,
                origin=metadata.origin or InputOrigin.TERMINAL.value,
                actor_id=metadata.actor_id,
                actor_name=metadata.actor_name,
                actor_avatar_url=metadata.actor_avatar_url,
                source_message_id=source_message_id,
                source_channel_id=link_id,
                origin_metadata=metadata.origin_metadata,
                caller_session_id=caller_session_id,
                caller_author_kind=caller_author.kind.value,
                caller_author_display=caller_author.display,
                caller_agent_runtime=caller_author.agent_runtime,
                caller_thinking_mode=caller_author.thinking_mode,
                caller_machine_role=caller_author.machine_role,
                caller_job_role=caller_job_role,
            ),
        )
        delivered_to += 1
    return delivered_to


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
