"""SQLModel definitions for TeleClaude database schema.

These models mirror the SQLite schema for ORM usage.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from teleclaude.core.origins import InputOrigin
from teleclaude.session_fields import SessionRecentOutputColumns, SessionRecentToolColumns


class Session(SessionRecentOutputColumns, SessionRecentToolColumns, SQLModel, table=True):
    """sessions table."""

    __tablename__ = "sessions"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    computer_name: str
    title: str | None = None
    tmux_session_name: str | None = None
    last_input_origin: str = InputOrigin.TELEGRAM.value
    adapter_metadata: str | None = None
    origin_metadata: str | None = None
    system_role: str | None = None
    job: str | None = None
    created_at: datetime | None = None
    last_activity: datetime | None = None
    closed_at: datetime | None = None
    terminal_size: str | None = "80x24"
    project_path: str | None = None
    subdir: str | None = None
    description: str | None = None
    initiated_by_ai: bool | None = False
    initiator_session_id: str | None = None
    initiator_computer: str | None = None
    detached: bool | None = False
    output_message_id: str | None = None
    notification_sent: int | None = 0
    native_session_id: str | None = None
    native_log_file: str | None = None
    active_agent: str | None = None
    thinking_mode: str | None = None
    tui_log_file: str | None = None
    tui_capture_started: int | None = 0
    lifecycle_status: str | None = "active"
    human_email: str | None = None
    human_role: str | None = None
    principal: str | None = None
    last_memory_extraction_at: str | None = None
    help_desk_processed_at: str | None = None
    relay_status: str | None = None
    relay_channel_id: str | None = None
    relay_started_at: str | None = None
    transcript_files: str | None = "[]"
    char_offset: int | None = 0
    visibility: str | None = "private"


class VoiceAssignment(SQLModel, table=True):
    """voice_assignments table."""

    __tablename__ = "voice_assignments"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    service_name: str | None = None
    voice: str | None = ""
    assigned_at: datetime | None = None


class VoiceTranscription(SQLModel, table=True):
    """voice_transcriptions table."""

    __tablename__ = "voice_transcriptions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str
    audio_path: str
    origin: str
    notice_message_id: str | None = None
    thread_id: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    duration: float | None = None
    language: str | None = None
    state: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    created_at: str
    updated_at: str


class PendingMessageDeletion(SQLModel, table=True):
    """pending_message_deletions table."""

    __tablename__ = "pending_message_deletions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str
    message_id: str
    deletion_type: str
    created_at: datetime | None = None


class SystemSetting(SQLModel, table=True):
    """system_settings table."""

    __tablename__ = "system_settings"
    __table_args__ = {"extend_existing": True}

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime | None = None


class AgentAvailability(SQLModel, table=True):
    """agent_availability table."""

    __tablename__ = "agent_availability"
    __table_args__ = {"extend_existing": True}

    agent: str = Field(primary_key=True)
    available: int | None = 1
    unavailable_until: str | None = None
    degraded_until: str | None = None
    reason: str | None = None


class ProcessJanitorPolicy(SQLModel, table=True):
    """process_janitor_policies table."""

    __tablename__ = "process_janitor_policies"
    __table_args__ = {"extend_existing": True}

    signature_id: str = Field(primary_key=True)
    name: str
    matcher_kind: str
    matcher_params_json: str = "{}"
    ttl_seconds: int
    enabled: int = 1
    dry_run: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class ProcessSpawnRegistryEntry(SQLModel, table=True):
    """process_spawn_registry table."""

    __tablename__ = "process_spawn_registry"
    __table_args__ = {"extend_existing": True}

    owner: str = Field(primary_key=True)
    pid: int
    lease_expires_at: str
    registered_at: str


class HookOutbox(SQLModel, table=True):
    """hook_outbox table."""

    __tablename__ = "hook_outbox"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str
    event_type: str
    payload: str
    created_at: str | None = None
    next_attempt_at: str | None = None
    attempt_count: int | None = 0
    last_error: str | None = None
    locked_at: str | None = None


class InboundQueue(SQLModel, table=True):
    """inbound_queue table."""

    __tablename__ = "inbound_queue"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str
    origin: str
    message_type: str = "text"
    content: str = ""
    payload_json: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    status: str = "pending"
    created_at: str = ""
    processed_at: str | None = None
    attempt_count: int = 0
    next_retry_at: str | None = None
    last_error: str | None = None
    locked_at: str | None = None
    source_message_id: str | None = None
    source_channel_id: str | None = None
    caller_session_id: str | None = None
    caller_author_kind: str | None = None
    caller_author_display: str | None = None
    caller_agent_runtime: str | None = None
    caller_thinking_mode: str | None = None
    caller_machine_role: str | None = None
    caller_job_role: str | None = None
    caller_origin_prefix_len: int | None = None
    binding_disposition: str | None = None


class AcceptedTurnBindingRow(SQLModel, table=True):
    """accepted_turn_bindings table — links a native turn to a receipt when present."""

    __tablename__ = "accepted_turn_bindings"
    __table_args__ = {"extend_existing": True}

    binding_id: str = Field(primary_key=True)
    session_id: str
    inbound_queue_id: int | None = None
    injected_span_start: int | None = None
    injected_span_end: int | None = None
    native_runtime: str | None = None
    native_session_id: str | None = None
    native_entry_id: str | None = None
    created_at: str


class BindingConflictCandidateRow(SQLModel, table=True):
    """binding_conflict_candidates table — exact native entries measured for a conflict."""

    __tablename__ = "binding_conflict_candidates"
    __table_args__ = {"extend_existing": True}

    inbound_queue_id: int = Field(primary_key=True)
    native_runtime: str = Field(primary_key=True)
    native_session_id: str = Field(primary_key=True)
    native_entry_id: str = Field(primary_key=True)
    created_at: str


class TurnAuthoredPartRow(SQLModel, table=True):
    """turn_authored_parts table — one ordered authored span of a bound turn."""

    __tablename__ = "turn_authored_parts"
    __table_args__ = {"extend_existing": True}

    binding_id: str = Field(primary_key=True)
    part_id: int = Field(primary_key=True)
    part_kind: str
    span_start: int
    span_end: int
    original_source_session_id: str | None = None
    author_kind: str
    author_display: str
    author_agent_runtime: str | None = None
    author_thinking_mode: str | None = None
    author_machine_role: str | None = None
    author_job_role: str | None = None
    origin_surface: str | None = None


class OutputGenerationRow(SQLModel, table=True):
    """output_generations table — one cut turn boundary for a session."""

    __tablename__ = "output_generations"
    __table_args__ = {"extend_existing": True}

    generation_id: str = Field(primary_key=True)
    session_id: str
    binding_id: str | None = None
    is_legacy: int = 0
    created_at: str


class OutputConsumerCursorRow(SQLModel, table=True):
    """output_consumer_cursors table — one consumer's independent delivery progress."""

    __tablename__ = "output_consumer_cursors"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    consumer: str = Field(primary_key=True)
    generation_id: str | None = None
    char_offset: int = 0
    updated_at: str


class OutputConsumerReceiptRow(SQLModel, table=True):
    """output_consumer_receipts table — one consumer's edit target for one generation."""

    __tablename__ = "output_consumer_receipts"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    consumer: str = Field(primary_key=True)
    generation_id: str = Field(primary_key=True)
    platform_message_id: str | None = None
    delivered_char_offset: int = 0
    updated_at: str


class DiscordSendIntentRow(SQLModel, table=True):
    """discord_send_intents table — durable webhook create intent tracking."""

    __tablename__ = "discord_send_intents"
    __table_args__ = {"extend_existing": True}

    intent_id: str = Field(primary_key=True)
    session_id: str
    generation_id: str
    channel_id: str
    status: str = "pending"
    platform_message_id: str | None = None
    replays_intent_id: str | None = None
    created_at: str
    resolved_at: str | None = None


class MemoryObservation(SQLModel, table=True):
    """memory_observations table."""

    __tablename__ = "memory_observations"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    memory_session_id: str
    project: str
    type: str
    title: str | None = None
    subtitle: str | None = None
    facts: str | None = None
    narrative: str | None = None
    concepts: str | None = None
    files_read: str | None = None
    files_modified: str | None = None
    prompt_number: int | None = None
    discovery_tokens: int | None = 0
    created_at: str
    created_at_epoch: int
    identity_key: str | None = None


class MemorySummary(SQLModel, table=True):
    """memory_summaries table."""

    __tablename__ = "memory_summaries"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    memory_session_id: str
    project: str
    request: str | None = None
    investigated: str | None = None
    learned: str | None = None
    completed: str | None = None
    next_steps: str | None = None
    created_at: str
    created_at_epoch: int


class WebhookContract(SQLModel, table=True):
    """webhook_contracts table."""

    __tablename__ = "webhook_contracts"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    contract_json: str
    active: int | None = 1
    source: str | None = "api"
    created_at: str | None = None
    updated_at: str | None = None


class WebhookOutbox(SQLModel, table=True):
    """webhook_outbox table."""

    __tablename__ = "webhook_outbox"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    contract_id: str
    event_json: str
    target_url: str
    target_secret: str | None = None
    status: str | None = "pending"
    created_at: str | None = None
    delivered_at: str | None = None
    attempt_count: int | None = 0
    next_attempt_at: str | None = None
    last_error: str | None = None
    locked_at: str | None = None


class SessionListenerRow(SQLModel, table=True):
    """session_listeners table — durable PUB-SUB for stop notifications."""

    __tablename__ = "session_listeners"
    __table_args__ = {"extend_existing": True}

    target_session_id: str = Field(primary_key=True)
    caller_session_id: str = Field(primary_key=True)
    caller_tmux_session: str
    registered_at: str
    one_shot: bool = False


class ConversationLinkRow(SQLModel, table=True):
    """conversation_links table."""

    __tablename__ = "conversation_links"
    __table_args__ = {"extend_existing": True}

    link_id: str = Field(primary_key=True)
    mode: str
    status: str = "active"
    created_by_session_id: str
    metadata_json: str | None = None
    created_at: str
    updated_at: str
    closed_at: str | None = None


class Operation(SQLModel, table=True):
    """operations table."""

    __tablename__ = "operations"
    __table_args__ = {"extend_existing": True}

    operation_id: str = Field(primary_key=True)
    kind: str
    caller_session_id: str
    client_request_id: str | None = None
    cwd: str
    slug: str | None = None
    payload_json: str
    state: str
    progress_phase: str | None = None
    progress_decision: str | None = None
    progress_reason: str | None = None
    result_text: str | None = None
    error_text: str | None = None
    error_payload: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    heartbeat_at: str | None = None
    attempt_count: int = 0


class ConversationLinkMemberRow(SQLModel, table=True):
    """conversation_link_members table."""

    __tablename__ = "conversation_link_members"
    __table_args__ = {"extend_existing": True}

    link_id: str = Field(primary_key=True)
    session_id: str = Field(primary_key=True)
    participant_name: str | None = None
    participant_number: int | None = None
    participant_role: str | None = None
    computer_name: str | None = None
    joined_at: str


class ConversationDeliveryStateRow(SQLModel, table=True):
    """conversation_delivery_state table."""

    __tablename__ = "conversation_delivery_state"
    __table_args__ = {"extend_existing": True}

    link_id: str = Field(primary_key=True)
    source_session_id: str = Field(primary_key=True)
    target_session_id: str = Field(primary_key=True)
    delivered_through_ts: str | None = None
    pending_through_ts: str | None = None
    disposition: str | None = None
    disposition_entry_ref: str | None = None
    disposition_reason: str | None = None
    updated_at: str


class MemoryManualSession(SQLModel, table=True):
    """memory_manual_sessions table."""

    __tablename__ = "memory_manual_sessions"
    __table_args__ = {"extend_existing": True}

    memory_session_id: str = Field(primary_key=True)
    project: str
    created_at_epoch: int


class PeerBundleRow(SQLModel, table=True):
    """peer_bundles table — one accepted structured peer delivery."""

    __tablename__ = "peer_bundles"
    __table_args__ = {"extend_existing": True}

    bundle_key: str = Field(primary_key=True)
    link_id: str
    source_session_id: str
    target_session_id: str
    created_at: str


class PeerBundleSegmentRow(SQLModel, table=True):
    """peer_bundle_segments table — one authored span within a bundle, in order.

    The author snapshot is immutable at write time: kind, display identity,
    and the class-specific qualifiers (agent runtime/thinking mode, machine
    role, raw JobRole) travel with the segment rather than being re-resolved
    from the source session later.
    """

    __tablename__ = "peer_bundle_segments"
    __table_args__ = {"extend_existing": True}

    bundle_key: str = Field(primary_key=True)
    segment_id: int = Field(primary_key=True)
    original_source_session_id: str
    author_kind: str
    author_display: str
    author_agent_runtime: str | None = None
    author_thinking_mode: str | None = None
    author_machine_role: str | None = None
    author_job_role: str | None = None
    occurred_at: str
    body: str = ""


class SessionToken(SQLModel, table=True):
    """session_tokens table — agent session authentication ledger."""

    __tablename__ = "session_tokens"
    __table_args__ = {"extend_existing": True}

    token: str = Field(primary_key=True)
    session_id: str
    principal: str  # "human:<email>" or "system:<stable-id>"
    role: str  # authorization role (e.g. "admin", "worker")
