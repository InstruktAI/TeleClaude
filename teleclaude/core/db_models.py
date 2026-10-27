"""SQLModel definitions for TeleClaude database schema.

These models mirror the SQLite schema for ORM usage.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

from teleclaude.core.agent_availability import AgentAvailabilityStatus
from teleclaude.core.inbound_types import InboundMessageType
from teleclaude.core.injected_text import TranscriptEntryKind
from teleclaude.core.origins import InputOrigin
from teleclaude.memory.types import MemoryState
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
    role: str | None = None
    job: str | None = None
    company: str | None = None
    created_at: datetime | None = None
    last_activity: datetime | None = None
    closed_at: datetime | None = None
    deleted_at: datetime | None = None
    project_path: str | None = None
    subdir: str | None = None
    config_subject: str | None = None
    subject_owner: str | None = None
    description: str | None = None
    initiated_by_ai: bool | None = False
    initiator_session_id: str | None = None
    initiator_computer: str | None = None
    detached: bool | None = False
    output_message_id: str | None = None
    turn_notifications_sent: str = "[]"
    native_session_id: str | None = None
    native_log_file: str | None = None
    active_agent: str | None = None
    thinking_mode: str | None = None
    tui_log_file: str | None = None
    tui_capture_started: int | None = 0
    lifecycle_status: str | None = "initializing"
    runtime_start_observed: bool | None = False
    runtime_run_id: str | None = None
    runtime_turn_id: str | None = None
    runtime_activity_at: datetime | None = None
    agent_status: str = "unknown"
    agent_status_reason: str = ""
    agent_status_since: datetime | None = None
    agent_status_version: int = 0
    open_tool_calls: str = "[]"
    lifecycle_transitioned_at: datetime | None = None
    lifecycle_transition_reason: str | None = None
    human_email: str | None = None
    human_role: str | None = None
    principal: str | None = None
    help_desk_processed_at: str | None = None
    idle_compaction_requested_at: str | None = None
    idle_compaction_completed_at: str | None = None
    idle_closed_at: str | None = None
    relay_status: str | None = None
    relay_channel_id: str | None = None
    relay_started_at: str | None = None
    relay_exchange: str = "[]"
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


class VoiceFocus(SQLModel, table=True):
    """voice_focus table."""

    __tablename__ = "voice_focus"
    __table_args__ = {"extend_existing": True}

    person_slug: str = Field(primary_key=True)
    focus_id: str
    focused_session_id: str | None = None
    basis: str = "derived"
    set_at: datetime | None = None


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
    source_message_id: str | None = None
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
    adapter_key: str
    message_id: str
    deletion_type: str
    created_at: datetime | None = None


class SessionStartupHandover(SQLModel, table=True):
    """session_startup_handovers table."""

    __tablename__ = "session_startup_handovers"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    launch_intent_json: str
    state: str
    updated_at: str


class SystemSetting(SQLModel, table=True):
    """system_settings table."""

    __tablename__ = "system_settings"
    __table_args__ = {"extend_existing": True}

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime | None = None


class DiscordReflectionRow(SQLModel, table=True):
    """Durable observed Discord provider state keyed by provider and logical identity."""

    __tablename__ = "discord_reflection_state"
    __table_args__ = {"extend_existing": True}

    provider: str = Field(primary_key=True)
    logical_key: str = Field(primary_key=True)
    artifact_kind: str
    scope_kind: str
    scope_value: str
    provider_id: int
    parent_provider_id: int | None = None
    metadata_json: str = "{}"
    verified_at: datetime | None = None


class DiscordInboundCursorRow(SQLModel, table=True):
    """The newest Discord message of one place (a session thread or a Team channel) whose handling has concluded."""

    __tablename__ = "discord_inbound_cursors"
    __table_args__ = {"extend_existing": True}

    place_id: int = Field(primary_key=True)
    message_id: int
    updated_at: str


class ConversationBindingRow(SQLModel, table=True):
    """The mesh master's binding of one shared-adapter conversation to its latest session."""

    __tablename__ = "conversation_bindings"
    __table_args__ = {"extend_existing": True}

    origin: str = Field(primary_key=True)
    key_field: str = Field(primary_key=True)
    conversation_key: str = Field(primary_key=True)
    session_id: str
    endpoint: str
    entered_at: str


class AgentAvailability(SQLModel, table=True):
    """agent_availability table."""

    __tablename__ = "agent_availability"
    __table_args__ = {"extend_existing": True}

    agent: str = Field(primary_key=True)
    model: str = Field(default="", primary_key=True)
    status: str = AgentAvailabilityStatus.AVAILABLE.value
    status_until: str | None = None
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
    message_type: str = InboundMessageType.TEXT.value
    text_kind: str = TranscriptEntryKind.ORDINARY.value
    source_feature: str = ""
    occurrence_key: str | None = None
    content: str = ""
    payload_json: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    status: str = "pending"
    created_at: str = ""
    processed_at: str | None = None
    reflected_at: str | None = None
    reflection_claimed_at: str | None = None
    attempt_count: int = 0
    next_retry_at: str | None = None
    last_error: str | None = None
    was_held: bool = False
    hold_notice_pending: bool = False
    hold_notice_attempt_count: int = 0
    hold_notice_next_retry_at: str | None = None
    hold_notice_error: str | None = None
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
    caller_origin_suffix_len: int | None = None
    binding_disposition: str | None = None


class AcceptedTurnBindingRow(SQLModel, table=True):
    """The durable composition root for one runtime-qualified user entry."""

    __tablename__ = "accepted_turn_bindings"
    __table_args__ = {"extend_existing": True}

    binding_id: str = Field(primary_key=True)
    session_id: str
    native_runtime: str
    native_session_id: str
    native_entry_id: str
    created_at: str


class TurnReceiptEnvelopeRow(SQLModel, table=True):
    """An accepted occurrence and the opaque envelope span it owns."""

    __tablename__ = "turn_receipt_envelopes"
    __table_args__ = {"extend_existing": True}

    binding_id: str = Field(primary_key=True)
    inbound_queue_id: int = Field(primary_key=True)
    envelope_index: int = Field(primary_key=True)
    occurrence_key: str
    envelope_span_start: int
    envelope_span_end: int
    body_span_start: int
    body_span_end: int
    authored_part_id: int | None = None


class BindingConflictCandidateRow(SQLModel, table=True):
    """A native entry considered for an accepted row that remains ambiguous."""

    __tablename__ = "binding_conflict_candidates"
    __table_args__ = {"extend_existing": True}

    inbound_queue_id: int = Field(primary_key=True)
    native_runtime: str = Field(primary_key=True)
    native_session_id: str = Field(primary_key=True)
    native_entry_id: str = Field(primary_key=True)
    created_at: str


class TurnAuthoredPartRow(SQLModel, table=True):
    """One ordered author-owned span extracted from a bound native turn."""

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
    author_channel_login: str | None = None
    author_channel_link: str | None = None


class SessionTurnRow(SQLModel, table=True):
    """The ordinal of one turn of a session, fixed when the completed-turns read first finds it."""

    __tablename__ = "session_turns"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    turn_identity: str = Field(primary_key=True)
    ordinal: int
    created_at: str


class SessionTurnSourceRow(SQLModel, table=True):
    """A transcript file of a session that a completed-turns read has taken turns from."""

    __tablename__ = "session_turn_sources"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    source_digest: str = Field(primary_key=True)
    created_at: str
    stop_at: str | None = None
    tail_open: bool = False


class GitHubConversationSendRow(SQLModel, table=True):
    """The time of one conversation append the fleet master sent."""

    __tablename__ = "github_conversation_sends"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    sent_at: str


class GitHubConversationBudgetRow(SQLModel, table=True):
    """The one row of conversation pause state: when requests may resume and how many unnamed limits ran in a row."""

    __tablename__ = "github_conversation_budget"
    __table_args__ = {"extend_existing": True}

    id: int = Field(default=1, primary_key=True)
    pause_until: str | None = None
    unnamed_limits: int = 0


class GitHubRateLimitNoticeRow(SQLModel, table=True):
    """A limit response this computer received that the fleet master has not yet been told."""

    __tablename__ = "github_rate_limit_notices"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    observed_at: str
    resume_at: str | None = None
    delivered_at: str | None = None


class ConversationLinkMode(StrEnum):
    """Kind of conversation a link aggregate represents."""

    DIRECT = "direct_link"
    GATHERING = "gathering_link"


class ControlDeliveryOutcome(StrEnum):
    """Terminal state owned by the control-delivery outbox."""

    DELIVERED = "delivered"
    FAILED = "failed"


class ControlDelivery(SQLModel, table=True):
    """One durable platform-control payload awaiting an agent hook boundary."""

    __tablename__ = "control_outbox"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    session_id: str
    envelope_name: str | None = None
    envelope_fields_json: str | None = None
    body: str
    body_digest: str
    source_key: str
    created_at: str
    outcome: str | None = None
    terminal_at: str | None = None


class ProcedureEventDeliveryOutcome(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SUSPENDED = "suspended"


class ProcedureEventInbox(SQLModel, table=True):
    """One accepted procedure activation retained independently of session lifetime."""

    __tablename__ = "procedure_event_inbox"
    __table_args__ = {"extend_existing": True}

    enqueue_order: int | None = Field(default=None, primary_key=True)
    activation_id: str = Field(unique=True)
    responsibility_key: str
    procedure_id: str
    home: str
    subject: str | None = None
    event_json: str
    identity: str
    attendance: str
    event_delivery: str
    interruptible: bool
    assigned_session_id: str | None = None
    outcome: str = ProcedureEventDeliveryOutcome.PENDING.value
    outcome_reason: str | None = None
    accepted_at: str
    terminal_at: str | None = None


class ProcedureEventDeliverySession(SQLModel, table=True):
    """Initialized per-session delivery policy and hook-entry correlation facts."""

    __tablename__ = "procedure_event_delivery_sessions"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    procedure_id: str
    responsibility_key: str
    event_delivery: str
    interruptible: bool
    initialized_at: str
    initial_entry_id: str | None = None
    initial_entry_consumed_at: str | None = None
    active_run_id: str | None = None
    consumed_entry_id: str | None = None
    wake_occurrence_id: str | None = None
    wake_accepted_occurrence_id: str | None = None
    wake_observed_last_input_at: str | None = None
    wake_observed_last_agent_stop_at: str | None = None
    wake_observed_last_agent_idle_at: str | None = None
    wake_observed_inbound_id: int | None = None


class OutputGenerationRow(SQLModel, table=True):
    """output_generations table — one cut turn boundary for a session."""

    __tablename__ = "output_generations"
    __table_args__ = {"extend_existing": True}

    generation_id: str = Field(primary_key=True)
    session_id: str
    native_runtime: str | None = None
    native_session_id: str | None = None
    native_entry_id: str | None = None
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


class ReminderRow(SQLModel, table=True):
    """reminders table — current aggregate generation for one session-local slug."""

    __tablename__ = "reminders"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    slug: str = Field(primary_key=True)
    profile: str | None = None
    intent: str
    trigger_type: str
    event_anchor: str | None = None
    recurrence: str
    interval_seconds: float | None = None
    armed_at: str
    next_fire_at: str | None = None
    generation: int
    occurrence_key: str
    firing_count: int = 0
    sliding: bool = False
    claimed_occurrence_key: str | None = None
    claimed_at: str | None = None


class ReminderEntryRow(SQLModel, table=True):
    """reminder_entries table — append-only typed lifecycle source."""

    __tablename__ = "reminder_entries"
    __table_args__ = {"extend_existing": True}

    entry_id: int | None = Field(default=None, primary_key=True)
    session_id: str
    slug: str
    generation: int
    transition: str
    profile: str | None = None
    intent: str
    trigger_type: str
    event_anchor: str | None = None
    recurrence: str
    interval_seconds: float | None = None
    armed_at: str
    occurred_at: str
    next_fire_at: str | None = None
    occurrence_key: str
    sliding: bool = False
    firing_number: int | None = None


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
    subject: str | None = None
    subject_owner: str | None = None
    principal: str | None = None
    state: str = MemoryState.CURRENT.value
    retired_at: str | None = None
    source_session_id: str | None = None
    extraction_id: str | None = None


class MemoryClosure(SQLModel, table=True):
    """memory_closures table: one eligible conversation closure captured from its ending event."""

    __tablename__ = "memory_closures"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    source_session_id: str
    ended_at: str
    identity_key: str
    desk: str | None = None
    home_kind: str
    home_slug: str
    extraction_id: str | None = None
    pending_reason: str | None = None
    settled_at: str | None = None
    created_at: str


class MemoryExtraction(SQLModel, table=True):
    """memory_extractions table: one bounded stretch of a source conversation released to a memory worker."""

    __tablename__ = "memory_extractions"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    source_session_id: str
    identity_key: str
    desk: str | None = None
    home_kind: str
    home_slug: str
    from_key: str | None = None
    through_key: str | None = None
    through_at: str | None = None
    message_count: int = 0
    missing_sources: str = "[]"
    status: str
    reason: str | None = None
    created_at: str
    updated_at: str


class MemorySourceProgress(SQLModel, table=True):
    """memory_source_progress table: how far each source conversation's messages have been extracted."""

    __tablename__ = "memory_source_progress"
    __table_args__ = {"extend_existing": True}

    source_session_id: str = Field(primary_key=True)
    through_key: str | None = None
    through_at: str | None = None
    time_bound: str | None = None
    updated_at: str


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


class SessionListenerRow(SQLModel, table=True):
    """session_listeners table — durable PUB-SUB for stop notifications."""

    __tablename__ = "session_listeners"
    __table_args__ = {"extend_existing": True}

    target_session_id: str = Field(primary_key=True)
    caller_session_id: str = Field(primary_key=True)
    caller_tmux_session: str
    registered_at: str
    one_shot: bool = False
    caller_computer: str | None = None
    startup_run_id: str | None = None


class ConversationLinkRow(SQLModel, table=True):
    """conversation_links table."""

    __tablename__ = "conversation_links"
    __table_args__ = {"extend_existing": True}

    link_id: str = Field(primary_key=True)
    # Persisted as the mode's value, never its member name. Stored rows hold
    # "direct_link"/"gathering_link"; typing this column as a SQLAlchemy enum
    # binds member names instead and fails to read every existing row.
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
    caller_session_id: str | None = None
    caller_computer: str | None = None
    caller_provenance_json: str | None = None
    client_request_id: str | None = None
    cwd: str | None = None
    session_project_path: str | None = None
    subject: str | None = None
    subject_owner: str | None = None
    slug: str | None = None
    payload_json: str
    state: str
    progress_phase: str | None = None
    progress_decision: str | None = None
    progress_reason: str | None = None
    result_text: str | None = None
    error_text: str | None = None
    error_payload: str | None = None
    work_feedback: str | None = None
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
    updated_at: str


class MemoryManualSession(SQLModel, table=True):
    """memory_manual_sessions table."""

    __tablename__ = "memory_manual_sessions"
    __table_args__ = {"extend_existing": True}

    memory_session_id: str = Field(primary_key=True)
    project: str
    created_at_epoch: int
