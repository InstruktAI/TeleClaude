"""Small shared helpers for session API routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, principal_for_carried_caller
from teleclaude.config.machine import config
from teleclaude.core.command_dispatch import RelayFailure, RemoteDispatchReason, dispatch_command, is_remote_target
from teleclaude.core.conversation_messages import (
    format_identity_conversation,
    format_identity_header,
    machine_role_label,
    resolve_session_event_author,
)
from teleclaude.core.db import db
from teleclaude.core.injected_text import CALLER_CATEGORY_PART_SEPARATOR, MachineRoleLabel
from teleclaude.core.models import JsonDict, JsonValue, MessageAuthor, MessageMetadata
from teleclaude.core.operation_caller_identity import get_relayed_caller
from teleclaude.core.operations.service import SerializedOperation
from teleclaude.types.commands import InternalCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_SESSION_EVENT_IDENTITY_RESOLVED_EVENT = "session_event_identity_resolved"


@dataclass(frozen=True)
class ResolvedSessionEventIdentity:
    author: MessageAuthor
    job_role: str | None
    header: str


def build_metadata(*, origin: str = "terminal", **kwargs: object) -> MessageMetadata:
    """Build API boundary metadata with explicit origin."""
    return MessageMetadata(origin=origin, **kwargs)


def close_accepted(receipt: SerializedOperation) -> JSONResponse:
    """Return the operation receipt as the close command's 202 response.

    The receipt's own ``computer`` field already names the owning computer,
    so no separate location label is needed here.
    """
    return JSONResponse(status_code=202, content=dict(receipt))


def http_exception_for_relay_failure(error: RelayFailure) -> HTTPException:
    """Translate a typed relay failure at the API boundary."""
    if error.reason is RemoteDispatchReason.NOT_FOUND:
        status_code = 404
    elif error.reason is RemoteDispatchReason.UNREACHABLE:
        status_code = 504
    elif error.reason is RemoteDispatchReason.REFUSED_BY_TARGET:
        status_code = 403
    else:
        status_code = 502
    return HTTPException(status_code=status_code, detail=str(error))


async def resolve_caller_event_identity(caller_session_id: str) -> ResolvedSessionEventIdentity:
    """Compose the identity of the carried caller session from its record on this computer.

    The caller runs on the computer whose request surface it called, and its
    carried session is taken as given (caller verification). A request another
    computer carried here names a caller session that computer holds: only its
    address is known, so its identity is the generic machine author at that address.
    """
    caller = await db.get_session(caller_session_id)
    if caller is None:
        relayed = get_relayed_caller()
        assert relayed is not None and relayed.session_id == caller_session_id
        role, agent, thinking_mode, job_role, computer = None, None, None, None, relayed.computer
    else:
        role = caller.role
        agent = caller.active_agent
        thinking_mode = caller.thinking_mode
        job_role = caller.role
        computer = caller.computer_name
    author = resolve_session_event_author(
        session_id=caller_session_id,
        role=role,
        active_agent=agent,
        thinking_mode=thinking_mode,
    )
    category_parts = [part for part in (agent.title() if agent else None, job_role) if part]
    header = format_identity_header(
        role=MachineRoleLabel.AGENT if agent else machine_role_label(role),
        category=CALLER_CATEGORY_PART_SEPARATOR.join(category_parts) or None,
        session_id=caller_session_id,
        computer=computer or config.computer.name,
        occurred_at=datetime.now(UTC),
    )
    logger.info(
        _SESSION_EVENT_IDENTITY_RESOLVED_EVENT,
        source_session_id=caller_session_id,
        author_kind=author.kind.value,
        agent_runtime=author.agent_runtime,
        job_role=job_role,
        machine_role=author.machine_role,
    )
    return ResolvedSessionEventIdentity(author=author, job_role=job_role, header=header)


async def envelope_caller_message(
    metadata: MessageMetadata,
    identity: CallerIdentity,
    message_text: str,
) -> tuple[str, str | None]:
    """Stamp the carried caller's authorship on ``metadata`` and wrap ``message_text`` in its identity envelope.

    Returns the text to deliver and the occurrence key minted for it. A call that
    carries no caller session is delivered as given, with no key.
    """
    if not identity.session_id:
        return message_text, None
    event_identity = await resolve_caller_event_identity(identity.session_id)
    caller_author = event_identity.author
    occurrence_key = uuid4().hex
    wrapped_text, prefix_len, suffix_len = format_identity_conversation(
        header=event_identity.header,
        body=message_text,
        occurrence_key=occurrence_key,
    )
    metadata.caller_session_id = identity.session_id
    metadata.caller_author_kind = caller_author.kind.value
    metadata.caller_author_display = caller_author.display
    metadata.caller_agent_runtime = caller_author.agent_runtime
    metadata.caller_thinking_mode = caller_author.thinking_mode
    metadata.caller_machine_role = caller_author.machine_role
    metadata.caller_job_role = event_identity.job_role
    metadata.caller_origin_prefix_len = prefix_len
    metadata.caller_origin_suffix_len = suffix_len
    return wrapped_text, occurrence_key


async def dispatch_caller_command(
    client: AdapterClient | None,
    command: InternalCommand,
    identity: CallerIdentity,
) -> JsonValue | None:
    """Dispatch a caller's command with the verified principal required by remote targets."""
    principal = principal_for_carried_caller(
        identity,
        required=is_remote_target(command.computer, config.computer.name),
    )
    return await dispatch_command(client, command, principal=principal)


async def resolve_created_session_transport(data: JsonDict) -> tuple[str, str]:
    """Resolve mandatory session creation response fields."""
    session_id = data.get("session_id")
    tmux_session_name = data.get("tmux_session_name")
    if session_id and not tmux_session_name:
        try:
            session = await db.get_session(str(session_id))
        except RuntimeError:
            session = None
        if session:
            tmux_session_name = session.tmux_session_name
    if not session_id or not tmux_session_name:
        logger.error(
            "create_session missing required fields (session_id=%s, tmux_session_name=%s)",
            session_id,
            tmux_session_name,
        )
        raise HTTPException(status_code=500, detail="Failed to create session: missing session_id or tmux_session_name")
    return str(session_id), str(tmux_session_name)
