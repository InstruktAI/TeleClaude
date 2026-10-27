-- Core session management
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT,
    last_input_origin TEXT NOT NULL DEFAULT 'telegram',
    adapter_metadata TEXT,
    origin_metadata TEXT,
    role TEXT,
    job TEXT,
    company TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    deleted_at TIMESTAMP,
    project_path TEXT,
    subdir TEXT,
    config_subject TEXT,
    subject_owner TEXT,
    description TEXT,
    initiated_by_ai BOOLEAN DEFAULT 0,
    initiator_session_id TEXT,
    initiator_computer TEXT,
    output_message_id TEXT,
    turn_notifications_sent TEXT NOT NULL DEFAULT '[]',
    native_session_id TEXT,
    native_log_file TEXT,
    active_agent TEXT,
    thinking_mode TEXT,
    tui_log_file TEXT,
    tui_capture_started INTEGER DEFAULT 0,
    -- Accepted-input fingerprint; compared, never rendered. See session_fields.
    last_message_sent TEXT,
    last_message_sent_at TEXT,
    -- Human-visible span of the accepted turn; rendered, never compared.
    last_input TEXT,
    -- Acceptance time of that span; coupled to last_input, never to the fingerprint clock.
    last_input_written_at TEXT,
    last_projected_at TEXT,
    last_output_raw TEXT,
    last_output_stop_at TEXT,
    last_output_at TEXT,
    last_output_summary TEXT,
    last_output_digest TEXT,
    last_projected_output_digest TEXT,
    last_tool_done_at TEXT,
    last_tool_use_at TEXT,
    last_checkpoint_at TEXT,
    last_agent_stop_at TEXT,
    last_agent_idle_at TEXT,
    turn_anchor_sha TEXT,
    command TEXT,
    working_slug TEXT,
    lifecycle_status TEXT DEFAULT 'initializing',
    runtime_start_observed INTEGER DEFAULT 0,
    runtime_run_id TEXT,
    runtime_turn_id TEXT,
    runtime_activity_at TIMESTAMP,
    agent_status TEXT NOT NULL DEFAULT 'unknown',
    agent_status_reason TEXT NOT NULL DEFAULT '',
    agent_status_since TIMESTAMP,
    agent_status_version INTEGER NOT NULL DEFAULT 0,
    open_tool_calls TEXT NOT NULL DEFAULT '[]',
    lifecycle_transitioned_at TIMESTAMP,
    lifecycle_transition_reason TEXT,
    human_email TEXT,
    human_role TEXT,
    principal TEXT,
    help_desk_processed_at TEXT,
    idle_compaction_requested_at TEXT,
    idle_compaction_completed_at TEXT,
    idle_closed_at TEXT,
    relay_status TEXT,
    relay_channel_id TEXT,
    relay_started_at TEXT,
    relay_exchange TEXT NOT NULL DEFAULT '[]',
    char_offset INTEGER DEFAULT 0,
    transcript_files TEXT DEFAULT '[]',
    visibility TEXT DEFAULT 'private',
    detached INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_computer ON sessions(computer_name);
CREATE INDEX IF NOT EXISTS idx_sessions_closed_at ON sessions(closed_at);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_initiator ON sessions(initiator_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_lifecycle_status ON sessions(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_sessions_native_session_id ON sessions(native_session_id);

-- Session listeners (AI-to-AI notification subscriptions)
CREATE TABLE IF NOT EXISTS session_listeners (
    target_session_id TEXT NOT NULL,
    caller_session_id TEXT NOT NULL,
    caller_tmux_session TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    one_shot INTEGER NOT NULL DEFAULT 0,
    caller_computer TEXT,
    startup_run_id TEXT,
    PRIMARY KEY (target_session_id, caller_session_id)
);

CREATE INDEX IF NOT EXISTS idx_session_listeners_caller ON session_listeners(caller_session_id);

-- Inbound message queue
CREATE TABLE IF NOT EXISTS inbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text' CHECK(message_type IN ('text', 'voice', 'file', 'reminder')),
    text_kind TEXT NOT NULL DEFAULT 'ordinary' CHECK(text_kind IN ('platform_control', 'identity_content', 'reminder', 'third_party_runtime_artifact', 'ordinary')),
    source_feature TEXT NOT NULL DEFAULT '',
    occurrence_key TEXT,
    content TEXT NOT NULL DEFAULT '',
    payload_json TEXT,
    actor_id TEXT,
    actor_name TEXT,
    actor_avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'delivered', 'failed', 'expired')),
    created_at TEXT NOT NULL,
    processed_at TEXT,
    reflected_at TEXT,
    reflection_claimed_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    last_error TEXT,
    was_held INTEGER NOT NULL DEFAULT 0,
    hold_notice_pending INTEGER NOT NULL DEFAULT 0,
    hold_notice_attempt_count INTEGER NOT NULL DEFAULT 0,
    hold_notice_next_retry_at TEXT,
    hold_notice_error TEXT,
    locked_at TEXT,
    source_message_id TEXT,
    source_channel_id TEXT,
    caller_session_id TEXT,
    caller_author_kind TEXT,
    caller_author_display TEXT,
    caller_agent_runtime TEXT,
    caller_thinking_mode TEXT,
    caller_machine_role TEXT,
    caller_job_role TEXT,
    caller_origin_prefix_len INTEGER,
    caller_origin_suffix_len INTEGER,
    binding_disposition TEXT CHECK(binding_disposition IN ('legacy_pre_cutover', 'input_conflict'))
);

CREATE INDEX IF NOT EXISTS idx_inbound_queue_session_status ON inbound_queue(session_id, status, next_retry_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_queue_source_dedup ON inbound_queue(origin, source_message_id) WHERE source_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS accepted_turn_bindings (
    binding_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    native_runtime TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    native_entry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(native_runtime, native_session_id, native_entry_id)
);

CREATE TABLE IF NOT EXISTS turn_receipt_envelopes (
    binding_id TEXT NOT NULL,
    inbound_queue_id INTEGER NOT NULL,
    envelope_index INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL,
    envelope_span_start INTEGER NOT NULL,
    envelope_span_end INTEGER NOT NULL,
    body_span_start INTEGER NOT NULL,
    body_span_end INTEGER NOT NULL,
    authored_part_id INTEGER,
    PRIMARY KEY (binding_id, inbound_queue_id, envelope_index),
    UNIQUE (inbound_queue_id),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE,
    FOREIGN KEY (inbound_queue_id) REFERENCES inbound_queue(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS binding_conflict_candidates (
    inbound_queue_id INTEGER NOT NULL,
    native_runtime TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    native_entry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (inbound_queue_id, native_runtime, native_session_id, native_entry_id),
    FOREIGN KEY (inbound_queue_id) REFERENCES inbound_queue(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS turn_authored_parts (
    binding_id TEXT NOT NULL,
    part_id INTEGER NOT NULL,
    part_kind TEXT NOT NULL CHECK(part_kind IN ('local', 'caller', 'peer', 'github')),
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    original_source_session_id TEXT,
    author_kind TEXT NOT NULL,
    author_display TEXT NOT NULL,
    author_agent_runtime TEXT,
    author_thinking_mode TEXT,
    author_machine_role TEXT,
    author_job_role TEXT,
    author_channel_login TEXT,
    author_channel_link TEXT,
    PRIMARY KEY (binding_id, part_id),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
);

-- The ordinal of each turn of a session, recorded the first time the completed-turns read finds it.
CREATE TABLE IF NOT EXISTS session_turns (
    session_id TEXT NOT NULL,
    turn_identity TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_identity),
    UNIQUE (session_id, ordinal)
);

-- The transcript files of a session a completed-turns read has taken turns from, so a file gone later is known to have
-- held only turns that were recorded, and one never read is known to have held turns nothing recorded.
CREATE TABLE IF NOT EXISTS session_turn_sources (
    session_id TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, source_digest)
);

-- The fleet master's conversation request budget: the time of each append it sent within the last hour, the end of
-- any pause a limit response set, and the limit responses other computers still owe the master.
CREATE TABLE IF NOT EXISTS github_conversation_sends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_github_conversation_sends_sent_at ON github_conversation_sends(sent_at);

CREATE TABLE IF NOT EXISTS github_conversation_budget (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pause_until TEXT,
    unnamed_limits INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS github_rate_limit_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_at TEXT NOT NULL,
    resume_at TEXT,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_accepted_turn_bindings_session ON accepted_turn_bindings(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turn_receipt_envelopes_binding ON turn_receipt_envelopes(binding_id);

-- Durable control payloads delivered through agent hook boundaries.
CREATE TABLE IF NOT EXISTS control_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    body TEXT NOT NULL,
    body_digest TEXT NOT NULL,
    source_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    outcome TEXT CHECK(outcome IN ('delivered', 'failed')),
    terminal_at TEXT,
    envelope_name TEXT,
    envelope_fields_json TEXT,
    CHECK(
        (outcome IS NULL AND terminal_at IS NULL)
        OR (outcome IS NOT NULL AND terminal_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_control_outbox_pending_session
    ON control_outbox(session_id, id)
    WHERE outcome IS NULL;

-- Procedure activations retain responsibility-owned event work across session changes.
CREATE TABLE IF NOT EXISTS procedure_event_inbox (
    enqueue_order INTEGER PRIMARY KEY AUTOINCREMENT,
    activation_id TEXT NOT NULL UNIQUE,
    responsibility_key TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    home TEXT NOT NULL,
    subject TEXT,
    event_json TEXT NOT NULL,
    identity TEXT NOT NULL CHECK(identity IN ('home', 'subject')),
    attendance TEXT NOT NULL CHECK(attendance IN ('attended', 'unattended')),
    event_delivery TEXT NOT NULL CHECK(event_delivery IN ('sequential', 'batched')),
    interruptible INTEGER NOT NULL CHECK(interruptible IN (0, 1)),
    assigned_session_id TEXT,
    outcome TEXT NOT NULL DEFAULT 'pending' CHECK(outcome IN ('pending', 'delivered', 'failed', 'suspended')),
    outcome_reason TEXT,
    accepted_at TEXT NOT NULL,
    terminal_at TEXT,
    CHECK(
        (outcome IN ('pending', 'suspended') AND terminal_at IS NULL)
        OR (outcome IN ('delivered', 'failed') AND terminal_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_procedure_event_inbox_responsibility
    ON procedure_event_inbox(responsibility_key, enqueue_order)
    WHERE outcome IN ('pending', 'suspended');
CREATE INDEX IF NOT EXISTS idx_procedure_event_inbox_assigned
    ON procedure_event_inbox(assigned_session_id, enqueue_order)
    WHERE outcome = 'pending';

CREATE TABLE IF NOT EXISTS procedure_event_delivery_sessions (
    session_id TEXT PRIMARY KEY,
    procedure_id TEXT NOT NULL,
    responsibility_key TEXT NOT NULL,
    event_delivery TEXT NOT NULL CHECK(event_delivery IN ('sequential', 'batched')),
    interruptible INTEGER NOT NULL CHECK(interruptible IN (0, 1)),
    initialized_at TEXT NOT NULL,
    initial_entry_id TEXT,
    initial_entry_consumed_at TEXT,
    active_run_id TEXT,
    consumed_entry_id TEXT,
    wake_occurrence_id TEXT,
    wake_accepted_occurrence_id TEXT,
    wake_observed_last_input_at TEXT,
    wake_observed_last_agent_stop_at TEXT,
    wake_observed_last_agent_idle_at TEXT,
    wake_observed_inbound_id INTEGER
);

-- Pending message deletions (ephemeral UI message tracking)
CREATE TABLE IF NOT EXISTS pending_message_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    adapter_key TEXT NOT NULL,
    message_id TEXT NOT NULL,
    deletion_type TEXT NOT NULL CHECK(deletion_type IN ('user_input', 'feedback')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, adapter_key, message_id, deletion_type),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pending_deletions_session
    ON pending_message_deletions(session_id, adapter_key);

-- Startup handover: an acknowledged session start's launch intent and progress,
-- kept beside the session so a replacement of the service resumes or reports it.
CREATE TABLE IF NOT EXISTS session_startup_handovers (
    session_id TEXT PRIMARY KEY,
    launch_intent_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN (
        'accepted', 'agent_launched', 'submitting', 'reporting_uncertain',
        'handed_over', 'failed', 'delivery_uncertain'
    )),
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_startup_handovers_state
    ON session_startup_handovers(state);

-- Durable operations
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    caller_session_id TEXT,
    caller_computer TEXT,
    caller_provenance_json TEXT,
    client_request_id TEXT,
    cwd TEXT,
    session_project_path TEXT,
    subject TEXT,
    subject_owner TEXT,
    slug TEXT,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'completed', 'failed', 'stale', 'cancelled')),
    progress_phase TEXT,
    progress_decision TEXT,
    progress_reason TEXT,
    result_text TEXT,
    error_text TEXT,
    error_payload TEXT,
    work_feedback TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    heartbeat_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_operations_owner_state ON operations(caller_session_id, kind, state, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_request_dedupe ON operations(kind, caller_session_id, client_request_id) WHERE client_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_operations_state_heartbeat ON operations(state, heartbeat_at);

-- Conversation links (direct/gathering)
CREATE TABLE IF NOT EXISTS conversation_links (
    link_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode IN ('direct_link', 'gathering_link')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'closed')),
    created_by_session_id TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_conversation_links_status ON conversation_links(status);

CREATE TABLE IF NOT EXISTS conversation_link_members (
    link_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    participant_name TEXT,
    participant_number INTEGER,
    participant_role TEXT,
    computer_name TEXT,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (link_id, session_id),
    FOREIGN KEY (link_id) REFERENCES conversation_links(link_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_link_members_session ON conversation_link_members(session_id);

CREATE TABLE IF NOT EXISTS conversation_delivery_state (
    link_id TEXT NOT NULL,
    source_session_id TEXT NOT NULL,
    target_session_id TEXT NOT NULL,
    delivered_through_ts TEXT,
    pending_through_ts TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (link_id, source_session_id, target_session_id),
    FOREIGN KEY (link_id) REFERENCES conversation_links(link_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_conversation_delivery_source_target
ON conversation_delivery_state(source_session_id, target_session_id);

-- Notification outbox
CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    content TEXT NOT NULL,
    file_path TEXT,
    delivery_channel TEXT NOT NULL DEFAULT 'telegram',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    attempt_count INTEGER DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    locked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notification_outbox_status ON notification_outbox(status);
CREATE INDEX IF NOT EXISTS idx_notification_outbox_next_attempt_at ON notification_outbox(next_attempt_at);

-- REST and terminal outboxes
CREATE TABLE IF NOT EXISTS rest_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
    attempt_count INTEGER DEFAULT 0,
    last_error TEXT,
    delivered_at TEXT,
    locked_at TEXT,
    response TEXT
);

CREATE INDEX IF NOT EXISTS idx_rest_outbox_pending ON rest_outbox(delivered_at, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_rest_outbox_request ON rest_outbox(request_id);

CREATE TABLE IF NOT EXISTS terminal_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
    attempt_count INTEGER DEFAULT 0,
    last_error TEXT,
    delivered_at TEXT,
    locked_at TEXT,
    response TEXT
);

-- Agent availability
CREATE TABLE IF NOT EXISTS agent_availability (
    agent TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'available',
    status_until TEXT,
    reason TEXT,
    PRIMARY KEY (agent, model)
);

-- Daemon-owned process lifecycle policy and detached spawn registry
CREATE TABLE IF NOT EXISTS process_janitor_policies (
    signature_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    matcher_kind TEXT NOT NULL,
    matcher_params_json TEXT NOT NULL DEFAULT '{}',
    ttl_seconds INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    dry_run INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_process_janitor_policies_enabled
ON process_janitor_policies(enabled);

CREATE TABLE IF NOT EXISTS process_spawn_registry (
    owner TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    lease_expires_at TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_process_spawn_registry_lease
ON process_spawn_registry(lease_expires_at);

-- Voice assignments
-- One durable voice-focus record per person: which session their voice
-- utterances latch to and their replies play from. focus_id is generated
-- once per person and stays stable across every subsequent update.
CREATE TABLE IF NOT EXISTS voice_focus (
    person_slug TEXT PRIMARY KEY,
    focus_id TEXT NOT NULL,
    focused_session_id TEXT,
    basis TEXT NOT NULL DEFAULT 'derived' CHECK(basis IN ('derived', 'explicit')),
    set_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voice_assignments (
    id TEXT PRIMARY KEY,
    service_name TEXT,
    voice TEXT DEFAULT '',
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_voice_assignments_assigned_at ON voice_assignments(assigned_at);

-- Voice transcription durability and recovery
CREATE TABLE IF NOT EXISTS voice_transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    origin TEXT NOT NULL,
    notice_message_id TEXT,
    thread_id TEXT,
    actor_id TEXT,
    actor_name TEXT,
    actor_avatar_url TEXT,
    duration REAL,
    language TEXT,
    source_message_id TEXT,
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'in_progress', 'succeeded', 'failed', 'interrupted')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_voice_transcriptions_state_id ON voice_transcriptions(state, id);
CREATE INDEX IF NOT EXISTS idx_voice_transcriptions_session ON voice_transcriptions(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_transcriptions_audio_path ON voice_transcriptions(audio_path);

-- System settings (key-value)
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS discord_reflection_state (
    provider TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_value TEXT NOT NULL,
    provider_id INTEGER NOT NULL,
    parent_provider_id INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    verified_at TIMESTAMP,
    PRIMARY KEY (provider, logical_key)
);

CREATE INDEX IF NOT EXISTS idx_discord_reflection_scope
    ON discord_reflection_state (provider, scope_kind, scope_value);

-- The newest Discord message of one place (a session thread or a Team channel) whose handling has concluded.
-- Recovery after the daemon was away reads a place's history after this message.
CREATE TABLE IF NOT EXISTS discord_inbound_cursors (
    place_id INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- Memory observations and FTS
CREATE TABLE IF NOT EXISTS memory_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT,
    subtitle TEXT,
    facts TEXT,
    narrative TEXT,
    concepts TEXT,
    files_read TEXT,
    files_modified TEXT,
    prompt_number INTEGER,
    discovery_tokens INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    identity_key TEXT,
    subject TEXT,
    subject_owner TEXT,
    principal TEXT,
    state TEXT NOT NULL DEFAULT 'current',
    retired_at TEXT,
    source_session_id TEXT,
    extraction_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_obs_session ON memory_observations(memory_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_obs_project ON memory_observations(project, created_at_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_memory_obs_type ON memory_observations(type);
CREATE INDEX IF NOT EXISTS idx_memory_obs_identity ON memory_observations(project, identity_key);
CREATE INDEX IF NOT EXISTS idx_memory_obs_source_session ON memory_observations(source_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_obs_extraction ON memory_observations(extraction_id);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_observations_fts USING fts5(
    title, subtitle, narrative, facts, concepts,
    content='memory_observations',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS memory_obs_ai AFTER INSERT ON memory_observations BEGIN
    INSERT INTO memory_observations_fts(rowid, title, subtitle, narrative, facts, concepts)
    VALUES (new.id, new.title, new.subtitle, new.narrative, new.facts, new.concepts);
END;

CREATE TRIGGER IF NOT EXISTS memory_obs_ad AFTER DELETE ON memory_observations BEGIN
    INSERT INTO memory_observations_fts(memory_observations_fts, rowid, title, subtitle, narrative, facts, concepts)
    VALUES('delete', old.id, old.title, old.subtitle, old.narrative, old.facts, old.concepts);
END;

CREATE TRIGGER IF NOT EXISTS memory_obs_au AFTER UPDATE ON memory_observations BEGIN
    INSERT INTO memory_observations_fts(memory_observations_fts, rowid, title, subtitle, narrative, facts, concepts)
    VALUES('delete', old.id, old.title, old.subtitle, old.narrative, old.facts, old.concepts);
    INSERT INTO memory_observations_fts(rowid, title, subtitle, narrative, facts, concepts)
    VALUES (new.id, new.title, new.subtitle, new.narrative, new.facts, new.concepts);
END;

-- Memory-owned extraction state: a conversation's closures awaiting extraction, the extractions released from
-- them, and how far each source conversation has been processed.
CREATE TABLE IF NOT EXISTS memory_closures (
    id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    desk TEXT,
    home_kind TEXT NOT NULL,
    home_slug TEXT NOT NULL,
    extraction_id TEXT,
    pending_reason TEXT,
    settled_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_closures_source ON memory_closures(source_session_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_memory_closures_extraction ON memory_closures(extraction_id);

CREATE TABLE IF NOT EXISTS memory_extractions (
    id TEXT PRIMARY KEY,
    source_session_id TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    desk TEXT,
    home_kind TEXT NOT NULL,
    home_slug TEXT NOT NULL,
    from_key TEXT,
    through_key TEXT,
    through_at TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    missing_sources TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_extractions_source ON memory_extractions(source_session_id, status);

CREATE TABLE IF NOT EXISTS memory_source_progress (
    source_session_id TEXT PRIMARY KEY,
    through_key TEXT,
    through_at TEXT,
    time_bound TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    request TEXT,
    investigated TEXT,
    learned TEXT,
    completed TEXT,
    next_steps TEXT,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_sum_session ON memory_summaries(memory_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_sum_project ON memory_summaries(project, created_at_epoch DESC);

CREATE TABLE IF NOT EXISTS memory_manual_sessions (
    memory_session_id TEXT PRIMARY KEY,
    project TEXT UNIQUE NOT NULL,
    created_at_epoch INTEGER NOT NULL
);

-- Output generation identity: one row per cut turn boundary for a session.
-- Assistant output snapshots name their generation so an adapter can edit
-- only its own in-flight message, never a stale or later turn's.
CREATE TABLE IF NOT EXISTS output_generations (
    generation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    binding_id TEXT,
    is_legacy INTEGER NOT NULL DEFAULT 0,
    native_runtime TEXT,
    native_session_id TEXT,
    native_entry_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_output_generations_session ON output_generations(session_id, created_at);

-- Per-consumer delivery progress. One session may have multiple independent
-- consumers (origin adapter, admin mirror, additional relay lanes); each
-- owns its own cursor so one consumer's advance cannot mute another's.
CREATE TABLE IF NOT EXISTS output_consumer_cursors (
    session_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    generation_id TEXT,
    char_offset INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, consumer)
);

-- Current reminder aggregate generation. Public identity is session + slug;
-- occurrence_key is private acceptance-dedup infrastructure identity.
CREATE TABLE IF NOT EXISTS reminders (
    session_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    profile TEXT,
    intent TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('time', 'agent_event')),
    event_anchor TEXT,
    recurrence TEXT NOT NULL CHECK(recurrence IN ('one_shot', 'recurring')),
    interval_seconds REAL,
    armed_at TEXT NOT NULL,
    next_fire_at TEXT,
    generation INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL,
    firing_count INTEGER NOT NULL DEFAULT 0 CHECK(firing_count >= 0),
    sliding INTEGER NOT NULL DEFAULT 0,
    claimed_occurrence_key TEXT,
    claimed_at TEXT,
    PRIMARY KEY (session_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_reminders_next_fire
ON reminders(next_fire_at)
WHERE next_fire_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_reminders_event_anchor
ON reminders(session_id, event_anchor)
WHERE event_anchor IS NOT NULL;

-- Append-only reminder source entries. A firing occurrence is unique so a
-- crash after inbound acceptance cannot append a second firing entry.
CREATE TABLE IF NOT EXISTS reminder_entries (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    generation INTEGER NOT NULL,
    transition TEXT NOT NULL CHECK(transition IN ('armed', 'replaced', 'cancelled', 'firing')),
    profile TEXT,
    intent TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('time', 'agent_event')),
    event_anchor TEXT,
    recurrence TEXT NOT NULL CHECK(recurrence IN ('one_shot', 'recurring')),
    interval_seconds REAL,
    armed_at TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    next_fire_at TEXT,
    occurrence_key TEXT NOT NULL,
    sliding INTEGER NOT NULL DEFAULT 0,
    firing_number INTEGER CHECK(firing_number IS NULL OR firing_number > 0)
);

CREATE INDEX IF NOT EXISTS idx_reminder_entries_session
ON reminder_entries(session_id, entry_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reminder_entries_firing_occurrence
ON reminder_entries(occurrence_key)
WHERE transition = 'firing';

-- Per-consumer, per-generation delivery receipt: the platform message a
-- consumer is currently editing for a specific generation, and how much of
-- that generation's output has been written into it.
CREATE TABLE IF NOT EXISTS output_consumer_receipts (
    session_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    platform_message_id TEXT,
    delivered_char_offset INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, consumer, generation_id)
);

CREATE INDEX IF NOT EXISTS idx_output_consumer_receipts_session_consumer
ON output_consumer_receipts(session_id, consumer, updated_at DESC);

-- Durable Discord webhook create intent, persisted before dispatch so restart
-- can reconcile an unresolved create instead of blind-resending it. Bounded
-- terminal dispositions: 'resolved' (a platform id was recovered and
-- adopted), 'omitted' (reconciliation was inconclusive within its bound —
-- closed as not-delivered, releasing the lane for the next generation), and
-- 'replayed' (an explicit recovery action re-drove an omitted intent; the
-- retry is a fresh intent row referencing this one via replays_intent_id).
CREATE TABLE IF NOT EXISTS discord_send_intents (
    intent_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'resolved', 'omitted', 'replayed')),
    platform_message_id TEXT,
    replays_intent_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_discord_send_intents_session_gen
ON discord_send_intents(session_id, generation_id);

CREATE INDEX IF NOT EXISTS idx_discord_send_intents_status
ON discord_send_intents(status);

-- The mesh master's durable binding of each conversation on adapters whose
-- inbound messages reach every computer (Discord direct messages, WhatsApp):
-- the session its next message goes to. Written only on the master, whose
-- sessions they are. `endpoint` holds the endpoint stamp the session was created at.
CREATE TABLE IF NOT EXISTS conversation_bindings (
    origin TEXT NOT NULL,
    key_field TEXT NOT NULL,
    conversation_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    entered_at TEXT NOT NULL,
    PRIMARY KEY (origin, key_field, conversation_key)
);
