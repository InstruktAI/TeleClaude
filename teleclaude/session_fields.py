"""Shared field groups for session-facing models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlmodel import SQLModel


@dataclass(kw_only=True)
class SessionSnapshotTimestampFields:  # pylint: disable=too-many-instance-attributes
    """Shared timing fields carried by session snapshots and DTOs."""

    created_at: str | None = None
    last_activity: str | None = None
    closed_at: str | None = None
    last_input: str | None = None
    last_input_at: str | None = None
    last_agent_stop_at: str | None = None
    last_output_summary: str | None = None
    last_output_summary_at: str | None = None


@dataclass(kw_only=True)
class SessionSnapshotDetachmentField:
    """Shared detachment flag carried by session snapshots and DTOs."""

    detached: bool = False


@dataclass(kw_only=True)
class SessionSnapshotIdentityFields(SessionSnapshotDetachmentField):
    """Shared identity fields carried by session snapshots and DTOs."""

    last_output_digest: str | None = None
    native_session_id: str | None = None
    tmux_session_name: str | None = None
    initiator_session_id: str | None = None
    computer: str | None = None
    human_email: str | None = None
    human_role: str | None = None


class SessionDTOTimestampFields(BaseModel):
    """Shared timing fields carried by session API DTOs."""

    model_config = ConfigDict(frozen=True)

    created_at: str | None = None
    last_activity: str | None = None
    closed_at: str | None = None
    last_input: str | None = None
    last_input_at: str | None = None
    last_agent_stop_at: str | None = None
    last_output_summary: str | None = None
    last_output_summary_at: str | None = None


class SessionDTODetachmentField(BaseModel):
    """Shared detachment flag carried by session API DTOs."""

    model_config = ConfigDict(frozen=True)

    detached: bool = False


class SessionDTOIdentityFields(SessionDTODetachmentField):
    """Shared identity fields carried by session API DTOs."""

    model_config = ConfigDict(frozen=True)

    last_output_digest: str | None = None
    native_session_id: str | None = None
    tmux_session_name: str | None = None
    initiator_session_id: str | None = None
    computer: str | None = None
    human_email: str | None = None
    human_name: str | None = None
    human_role: str | None = None


@dataclass(kw_only=True)
class SessionRecentOutputFields:
    """Shared output-history fields for in-memory and ORM session models."""

    last_message_sent: str | None = None
    last_message_sent_at: datetime | None = None
    last_conversation_injected_at: datetime | None = None
    last_output_raw: str | None = None
    last_output_at: datetime | None = None
    last_output_summary: str | None = None
    last_output_digest: str | None = None


@dataclass(kw_only=True)
class SessionRecentToolFields:
    """Shared tool-activity fields for in-memory and ORM session models."""

    last_tool_done_at: datetime | None = None
    last_tool_use_at: datetime | None = None
    last_checkpoint_at: datetime | None = None
    last_agent_stop_at: datetime | None = None
    working_slug: str | None = None


class SessionRecentOutputColumns(SQLModel):
    """Shared ORM output-history columns for session models."""

    last_message_sent: str | None = None
    last_message_sent_at: datetime | None = None
    last_conversation_injected_at: datetime | None = None
    last_output_raw: str | None = None
    last_output_at: datetime | None = None
    last_output_summary: str | None = None
    last_output_digest: str | None = None


class SessionRecentToolColumns(SQLModel):
    """Shared ORM tool-activity columns for session models."""

    last_tool_done_at: datetime | None = None
    last_tool_use_at: datetime | None = None
    last_checkpoint_at: datetime | None = None
    last_agent_stop_at: datetime | None = None
    working_slug: str | None = None
