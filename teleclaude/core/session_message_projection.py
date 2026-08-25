"""Structured session transcript projection."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from teleclaude.api_models import MessageDTO, SessionMessagesDTO
from teleclaude.config import config
from teleclaude.core import agents as agents_module
from teleclaude.core.command_handlers import get_session_data
from teleclaude.core.command_handlers._utils import SessionDataPayload
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.reminders.models import ReminderEntry, ReminderEntryReadItem, ReminderTransition
from teleclaude.core.reminders.ordering import ProjectionOrderKey, ProjectionSourceKind, projection_order_key
from teleclaude.core.reminders.presentation import format_agent_reminder, format_ui_reminder
from teleclaude.core.session_output import assistant_output_parts_are_bare_noop, is_bare_noop_output
from teleclaude.core.session_status import compute_agent_status
from teleclaude.output_projection import conversation_projector as conversation_projector_module
from teleclaude.output_projection import serializers as output_serializers
from teleclaude.output_projection.models import ProjectionSurface, visibility_policy_for_person
from teleclaude.types.commands import GetSessionDataCommand
from teleclaude.utils.transcript import StructuredMessage

_ASSISTANT_ROLE: Literal["assistant"] = "assistant"
_USER_ROLE: Literal["user"] = "user"

type _NativeEntryKey = tuple[int, int]


class SessionMessagesDb(Protocol):
    """Database operations needed by session message projection."""

    async def get_session(self, session_id: str) -> Session | None: ...

    async def list_reminder_entries(
        self, *, session_id: str, after_entry_id: int = 0
    ) -> list[ReminderEntryReadItem]: ...


class SessionDataService(Protocol):
    """Command-service operation needed for session data fallback."""

    async def get_session_data(self, cmd: GetSessionDataCommand) -> SessionDataPayload: ...


@dataclass(frozen=True)
class SessionMessageProjectionOptions:
    """Caller options for structured session message projection."""

    since: str | None = None
    include_tools: bool | None = None
    include_thinking: bool = False
    tail_chars: int = 10000
    tail_scope: str = "all"


@dataclass(frozen=True)
class NativeMessageProjection:
    """Native transcript messages plus structural suppression state."""

    messages: list[MessageDTO]
    bare_noop_suppressed: bool


def build_message_chain(transcript_files: str | None, native_log_file: str | None) -> list[str]:
    """Build transcript chain from stored session fields."""
    chain: list[str] = []
    if transcript_files:
        try:
            stored = json.loads(transcript_files)
            if isinstance(stored, list):
                chain = [str(path) for path in stored if path]
        except (json.JSONDecodeError, TypeError):
            pass
    if native_log_file and native_log_file not in chain:
        chain.append(native_log_file)
    return chain


def project_messages(
    chain: list[str],
    *,
    active_agent: str | None,
    recipient_email: str | None,
    recipient_role: str | None,
    options: SessionMessageProjectionOptions,
    hidden_user_texts: frozenset[str] = frozenset(),
) -> NativeMessageProjection:
    """Project transcript files into structured messages."""
    if not chain:
        return NativeMessageProjection(messages=[], bare_noop_suppressed=False)

    policy = visibility_policy_for_person(
        human_role=recipient_role,
        person_email=recipient_email,
        surface=ProjectionSurface.WEB,
        include_thinking=options.include_thinking,
    )
    if options.include_tools is False:
        policy = replace(policy, include_tools=False)

    projected_blocks = conversation_projector_module.project_conversation_chain(
        chain,
        agents_module.resolve_parser_agent(active_agent),
        policy,
        since=options.since,
    )
    structured_messages = [
        output_serializers.to_structured_message(projected_block) for projected_block in projected_blocks
    ]
    bare_noop_entries = _bare_noop_entry_keys(structured_messages)
    messages = [
        MessageDTO(
            role=cast(Literal["user", "assistant", "system"], message.role),
            type=cast(Literal["text", "compaction", "pre_tool_use", "tool_result", "thinking"], message.type),
            text=message.text,
            timestamp=message.timestamp,
            entry_index=message.entry_index,
            file_index=message.file_index,
        )
        for message in structured_messages
        if not _is_hidden_native_message(
            message,
            hidden_user_texts=hidden_user_texts,
            bare_noop_entries=bare_noop_entries,
        )
    ]
    return NativeMessageProjection(messages=messages, bare_noop_suppressed=bool(bare_noop_entries))


def _bare_noop_entry_keys(messages: list[StructuredMessage]) -> frozenset[_NativeEntryKey]:
    """Identify assistant entries whose complete projected content is the sentinel."""
    assistant_entries: dict[_NativeEntryKey, list[StructuredMessage]] = {}
    for message in messages:
        if message.role != _ASSISTANT_ROLE:
            continue
        key = (message.file_index, message.entry_index)
        assistant_entries.setdefault(key, []).append(message)
    return frozenset(
        key
        for key, entry_messages in assistant_entries.items()
        if assistant_output_parts_are_bare_noop((message.type, message.text) for message in entry_messages)
    )


def _is_hidden_native_message(
    message: StructuredMessage,
    *,
    hidden_user_texts: frozenset[str],
    bare_noop_entries: frozenset[_NativeEntryKey],
) -> bool:
    """Return whether a native message is structurally excluded from projection."""
    if message.role == _USER_ROLE and message.text.strip() in hidden_user_texts:
        return True
    return (message.file_index, message.entry_index) in bare_noop_entries


def _merge_reminder_messages(messages: list[MessageDTO], entries: list[ReminderEntry]) -> list[MessageDTO]:
    """Merge native and typed reminder sources with the fixed native-before-reminder tie break."""
    earliest = datetime.min.replace(tzinfo=UTC)
    merged: list[tuple[ProjectionOrderKey, MessageDTO]] = [
        (
            projection_order_key(
                occurred_at=parse_iso_datetime(message.timestamp) or earliest,
                source_kind=ProjectionSourceKind.NATIVE,
                stable_id=index,
            ),
            message,
        )
        for index, message in enumerate(messages)
    ]
    merged.extend(
        (
            projection_order_key(
                occurred_at=entry.occurred_at,
                source_kind=ProjectionSourceKind.REMINDER,
                stable_id=entry.entry_id,
            ),
            MessageDTO(
                role="system",
                type="text",
                text=format_ui_reminder(entry, timezone_name=config.computer.timezone),
                timestamp=entry.occurred_at.isoformat(),
                entry_index=entry.entry_id,
                file_index=-1,
            ),
        )
        for entry in entries
    )
    return [message for _order_key, message in sorted(merged, key=lambda item: item[0])]


def apply_session_tail_scope(messages: list[MessageDTO], tail_scope: str) -> list[MessageDTO]:
    """Apply a caller-requested message window to already projected messages."""
    if tail_scope != "latest_turn":
        return messages

    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return messages[index:]
    return messages


async def build_session_messages_dto(
    session_id: str,
    *,
    recipient_email: str | None,
    recipient_role: str | None,
    options: SessionMessageProjectionOptions,
    database: SessionMessagesDb | None = None,
    command_service: SessionDataService | None = None,
) -> SessionMessagesDTO:
    """Build the structured session messages DTO for a locally-owned session."""
    active_db = database or db
    session = await active_db.get_session(session_id)
    if not session:
        raise LookupError("Session not found")

    reminder_read_items = await active_db.list_reminder_entries(session_id=session_id)
    reminder_entries = [item for item in reminder_read_items if isinstance(item, ReminderEntry)]
    since = parse_iso_datetime(options.since)
    if since is not None:
        reminder_entries = [entry for entry in reminder_entries if entry.occurred_at >= since]
    hidden_user_texts = frozenset(
        format_agent_reminder(entry).strip()
        for entry in reminder_entries
        if entry.transition is ReminderTransition.FIRING
    )
    native_projection = project_messages(
        build_message_chain(session.transcript_files, session.native_log_file),
        active_agent=session.active_agent,
        recipient_email=recipient_email or session.human_email,
        recipient_role=recipient_role or session.human_role,
        options=options,
        hidden_user_texts=hidden_user_texts,
    )
    messages = native_projection.messages

    if not messages and not native_projection.bare_noop_suppressed:
        fallback_command = GetSessionDataCommand(
            session_id=session_id,
            since_timestamp=options.since,
            tail_chars=options.tail_chars if options.tail_chars > 0 else 10000,
        )
        if command_service is not None and hasattr(command_service, "get_session_data"):
            fallback_payload = await command_service.get_session_data(fallback_command)
        else:
            fallback_payload = await get_session_data(
                fallback_command,
            )
        fallback_text_raw = fallback_payload.get("messages")
        fallback_text = fallback_text_raw if isinstance(fallback_text_raw, str) else ""
        if fallback_text and not is_bare_noop_output(fallback_text):
            messages = [
                MessageDTO(
                    role="assistant",
                    type="text",
                    text=fallback_text,
                    timestamp=None,
                    entry_index=0,
                    file_index=0,
                )
            ]

    messages = _merge_reminder_messages(messages, reminder_entries)
    messages = apply_session_tail_scope(messages, options.tail_scope)

    last_activity_at = session.last_activity.isoformat() if session.last_activity else None
    last_input_at = session.last_message_sent_at.isoformat() if session.last_message_sent_at else None
    last_agent_stop_at = session.last_agent_stop_at.isoformat() if session.last_agent_stop_at else None
    agent_status = compute_agent_status(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
        last_activity=session.last_activity,
        last_input_at=session.last_message_sent_at,
        last_agent_stop_at=session.last_agent_stop_at,
        now=datetime.now(UTC),
    )

    return SessionMessagesDTO(
        session_id=session_id,
        agent=session.active_agent,
        last_activity=last_activity_at,
        last_input_at=last_input_at,
        last_agent_stop_at=last_agent_stop_at,
        agent_status=agent_status,
        messages=messages,
    )
