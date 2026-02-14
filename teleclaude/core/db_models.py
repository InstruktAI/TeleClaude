"""SQLModel definitions for TeleClaude database schema.

These models mirror the SQLite schema for ORM usage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from teleclaude.core.origins import InputOrigin


class Session(SQLModel, table=True):
    """sessions table."""

    __tablename__ = "sessions"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    computer_name: str
    title: Optional[str] = None
    tmux_session_name: Optional[str] = None
    last_input_origin: str = InputOrigin.TELEGRAM.value
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
    last_output_digest: Optional[str] = None
    last_tool_done_at: Optional[datetime] = None
    last_tool_use_at: Optional[datetime] = None
    last_checkpoint_at: Optional[datetime] = None
    working_slug: Optional[str] = None
    lifecycle_status: Optional[str] = "active"
    human_email: Optional[str] = None
    human_role: Optional[str] = None


class VoiceAssignment(SQLModel, table=True):
    """voice_assignments table."""

    __tablename__ = "voice_assignments"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    service_name: Optional[str] = None
    voice: Optional[str] = ""
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


class MemoryObservation(SQLModel, table=True):
    """memory_observations table."""

    __tablename__ = "memory_observations"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    memory_session_id: str
    project: str
    type: str
    title: Optional[str] = None
    subtitle: Optional[str] = None
    facts: Optional[str] = None
    narrative: Optional[str] = None
    concepts: Optional[str] = None
    files_read: Optional[str] = None
    files_modified: Optional[str] = None
    prompt_number: Optional[int] = None
    discovery_tokens: Optional[int] = 0
    created_at: str
    created_at_epoch: int


class MemorySummary(SQLModel, table=True):
    """memory_summaries table."""

    __tablename__ = "memory_summaries"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    memory_session_id: str
    project: str
    request: Optional[str] = None
    investigated: Optional[str] = None
    learned: Optional[str] = None
    completed: Optional[str] = None
    next_steps: Optional[str] = None
    created_at: str
    created_at_epoch: int


class WebhookContract(SQLModel, table=True):
    """webhook_contracts table."""

    __tablename__ = "webhook_contracts"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    contract_json: str
    active: Optional[int] = 1
    source: Optional[str] = "api"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WebhookOutbox(SQLModel, table=True):
    """webhook_outbox table."""

    __tablename__ = "webhook_outbox"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    contract_id: str
    event_json: str
    target_url: str
    target_secret: Optional[str] = None
    status: Optional[str] = "pending"
    created_at: Optional[str] = None
    delivered_at: Optional[str] = None
    attempt_count: Optional[int] = 0
    next_attempt_at: Optional[str] = None
    last_error: Optional[str] = None
    locked_at: Optional[str] = None


class MemoryManualSession(SQLModel, table=True):
    """memory_manual_sessions table."""

    __tablename__ = "memory_manual_sessions"
    __table_args__ = {"extend_existing": True}

    memory_session_id: str = Field(primary_key=True)
    project: str
    created_at_epoch: int
