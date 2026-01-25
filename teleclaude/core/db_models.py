"""SQLModel definitions for TeleClaude database schema.

These models mirror the SQLite schema for ORM usage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Session(SQLModel, table=True):
    """sessions table."""

    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("computer_name", "tmux_session_name"), {"extend_existing": True})

    session_id: str = Field(primary_key=True)
    computer_name: str
    title: Optional[str] = None
    tmux_session_name: str
    last_input_origin: str = "telegram"
    adapter_metadata: Optional[str] = None
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    terminal_size: Optional[str] = "80x24"
    project_path: Optional[str] = None
    subdir: Optional[str] = None
    description: Optional[str] = None
    initiated_by_ai: Optional[bool] = False
    initiator_session_id: Optional[str] = None
    output_message_id: Optional[str] = None
    notification_sent: Optional[int] = 0
    native_session_id: Optional[str] = None
    native_log_file: Optional[str] = None
    active_agent: Optional[str] = None
    thinking_mode: Optional[str] = None
    tui_log_file: Optional[str] = None
    tui_capture_started: Optional[int] = 0
    last_message_sent: Optional[str] = None
    last_message_sent_at: Optional[datetime] = None
    last_feedback_received: Optional[str] = None
    last_feedback_received_at: Optional[datetime] = None
    last_feedback_summary: Optional[str] = None
    working_slug: Optional[str] = None
    lifecycle_status: Optional[str] = "active"


class VoiceAssignment(SQLModel, table=True):
    """voice_assignments table."""

    __tablename__ = "voice_assignments"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    voice_name: Optional[str] = None
    elevenlabs_id: Optional[str] = ""
    macos_voice: Optional[str] = ""
    openai_voice: Optional[str] = ""
    service_name: Optional[str] = None
    assigned_at: Optional[datetime] = None


class PendingMessageDeletion(SQLModel, table=True):
    """pending_message_deletions table."""

    __tablename__ = "pending_message_deletions"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str
    message_id: str
    deletion_type: str
    created_at: Optional[datetime] = None


class SystemSetting(SQLModel, table=True):
    """system_settings table."""

    __tablename__ = "system_settings"
    __table_args__ = {"extend_existing": True}

    key: str = Field(primary_key=True)
    value: str
    updated_at: Optional[datetime] = None


class AgentAvailability(SQLModel, table=True):
    """agent_availability table."""

    __tablename__ = "agent_availability"
    __table_args__ = {"extend_existing": True}

    agent: str = Field(primary_key=True)
    available: Optional[int] = 1
    unavailable_until: Optional[str] = None
    reason: Optional[str] = None


class HookOutbox(SQLModel, table=True):
    """hook_outbox table."""

    __tablename__ = "hook_outbox"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str
    event_type: str
    payload: str
    created_at: Optional[str] = None
    next_attempt_at: Optional[str] = None
    attempt_count: Optional[int] = 0
    last_error: Optional[str] = None
    delivered_at: Optional[str] = None
    locked_at: Optional[str] = None
