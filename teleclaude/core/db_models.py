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
    company: str | None = None
    created_at: datetime | None = None
    last_activity: datetime | None = None
    closed_at: datetime | None = None
    terminal_size: str | None = "80x24"
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
    last_memory_extraction_at: str | None = None
    help_desk_processed_at: str | None = None
    relay_status: str | None = None
    relay_channel_id: str | None = None
    relay_started_at: str | None = None
    relay_targets: str = "[]"
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


class DiscordSharedThreadContenderRow(SQLModel, table=True):
    """One computer's observational claim for a shared Discord child."""

    __tablename__ = "discord_shared_thread_contenders"
    __table_args__ = {"extend_existing": True}

    thread_id: int = Field(primary_key=True)
    computer: str = Field(primary_key=True)
    parent_id: int
    child_kind: str
    local_identity: str
    lifecycle: str
    protocol_generation: int


class ConversationBindingRow(SQLModel, table=True):
    """The mesh master's binding of one shared-adapter conversation to its latest session."""

    __tablename__ = "conversation_bindings"
    __table_args__ = {"extend_existing": True}

    origin: str = Field(primary_key=True)
    key_field: str = Field(primary_key=True)
    conversation_key: str = Field(primary_key=True)
    host: str
    session_id: str
    endpoint: str
    entered_at: str


class ConversationAdoptionSourceRow(SQLModel, table=True):
    """One computer whose open conversation sessions seed the master's bindings."""

    __tablename__ = "conversation_bindings_adoption"
    __table_args__ = {"extend_existing": True}

    computer: str = Field(primary_key=True)
    answered_at: str | None = None


class ConversationBindingOrphanRow(SQLModel, table=True):
    """A session a lost remote-create answer may have left on its host, to be closed by id."""

    __tablename__ = "conversation_binding_orphans"
    __table_args__ = {"extend_existing": True}

    session_id: str = Field(primary_key=True)
    host: str
    recorded_at: str


class DiscordSharedThreadOwnerRow(SQLModel, table=True):
    """The single winning owner for a shared Discord child after activation."""

    __tablename__ = "discord_shared_thread_owners"
    __table_args__ = {"extend_existing": True}

    thread_id: int = Field(primary_key=True)
    parent_id: int
    child_kind: str
    owner_computer: str
    local_identity: str
    lifecycle: str
    protocol_generation: int


class DiscordThreadClaimMemberRow(SQLModel, table=True):
    """A retained fleet member and its current claim-protocol adoption proof."""

    __tablename__ = "discord_thread_claim_members"
    __table_args__ = {"extend_existing": True}

    computer: str = Field(primary_key=True)
    protocol_generation: int
    adoption_state: str
    inventory_completed_epoch: int | None = None


class DiscordThreadReconciliationEpochRow(SQLModel, table=True):
    """The single durable epoch allocator for one claim protocol generation."""

    __tablename__ = "discord_thread_reconciliation_epochs"
    __table_args__ = {"extend_existing": True}

    protocol_generation: int = Field(primary_key=True)
    current_epoch: int
    phase: str


class DiscordThreadClaimInventoryItemRow(SQLModel, table=True):
    """One member's complete shared-child inventory entry for one durable epoch."""

    __tablename__ = "discord_thread_claim_inventory_items"
    __table_args__ = {"extend_existing": True}

    computer: str = Field(primary_key=True)
    protocol_generation: int = Field(primary_key=True)
    inventory_epoch: int = Field(primary_key=True)
    thread_id: int = Field(primary_key=True)
    parent_id: int
    child_kind: str
    local_identity: str
    lifecycle: str


class DiscordThreadOrphanCandidateRow(SQLModel, table=True):
    """Durable evidence that a shared provider child remained unclaimed across epochs."""

    __tablename__ = "discord_thread_orphan_candidates"
    __table_args__ = {"extend_existing": True}

    thread_id: int = Field(primary_key=True)
    parent_id: int
    first_qualifying_epoch: int
    last_qualifying_epoch: int
    consecutive_complete_epochs: int


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


class EventSubscriptionRow(SQLModel, table=True):
    """event_subscriptions table — one live request to receive catalog events."""

    __tablename__ = "event_subscriptions"
    __table_args__ = {"extend_existing": True}

    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    event_type: str = Field(index=True)
    mode: str
    narrowing_json: str
    created_position: str
    principal: str
    company: str | None = None
    claimed_event_id: str | None = None
    created_at: str


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
