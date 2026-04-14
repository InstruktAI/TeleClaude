-- Core session management
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT,
    last_input_origin TEXT NOT NULL DEFAULT 'telegram',
    adapter_metadata TEXT,
    session_metadata TEXT,
    origin_metadata TEXT,
    system_role TEXT,
    job TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    terminal_size TEXT DEFAULT '80x24',
    project_path TEXT,
    subdir TEXT,
    description TEXT,
    initiated_by_ai BOOLEAN DEFAULT 0,
    initiator_session_id TEXT,
    output_message_id TEXT,
    notification_sent INTEGER DEFAULT 0,
    native_session_id TEXT,
    native_log_file TEXT,
    active_agent TEXT,
    thinking_mode TEXT,
    tui_log_file TEXT,
    tui_capture_started INTEGER DEFAULT 0,
    last_message_sent TEXT,
    last_message_sent_at TEXT,
    last_conversation_injected_at TEXT,
    last_output_raw TEXT,
    last_output_at TEXT,
    last_output_summary TEXT,
    last_output_digest TEXT,
    last_tool_done_at TEXT,
    last_tool_use_at TEXT,
    last_checkpoint_at TEXT,
    last_agent_stop_at TEXT,
    working_slug TEXT,
    lifecycle_status TEXT DEFAULT 'active',
    human_email TEXT,
    human_role TEXT,
    principal TEXT,
    last_memory_extraction_at TEXT,
    help_desk_processed_at TEXT,
    relay_status TEXT,
    relay_discord_channel_id TEXT,
    relay_started_at TEXT,
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

-- Session auth tokens
CREATE TABLE IF NOT EXISTS session_tokens (
    token TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    principal TEXT NOT NULL,
    role TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_tokens_session ON session_tokens(session_id);

-- Session listeners (AI-to-AI notification subscriptions)
CREATE TABLE IF NOT EXISTS session_listeners (
    target_session_id TEXT NOT NULL,
    caller_session_id TEXT NOT NULL,
    caller_tmux_session TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    PRIMARY KEY (target_session_id, caller_session_id)
);

CREATE INDEX IF NOT EXISTS idx_session_listeners_caller ON session_listeners(caller_session_id);

-- Inbound message queue
CREATE TABLE IF NOT EXISTS inbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text' CHECK(message_type IN ('text', 'voice', 'file')),
    content TEXT NOT NULL DEFAULT '',
    payload_json TEXT,
    actor_id TEXT,
    actor_name TEXT,
    actor_avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'delivered', 'failed', 'expired')),
    created_at TEXT NOT NULL,
    processed_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    last_error TEXT,
    locked_at TEXT,
    source_message_id TEXT,
    source_channel_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_inbound_queue_session_status ON inbound_queue(session_id, status, next_retry_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_queue_source_dedup ON inbound_queue(origin, source_message_id) WHERE source_message_id IS NOT NULL;

-- Pending message deletions (ephemeral UI message tracking)
CREATE TABLE IF NOT EXISTS pending_message_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    deletion_type TEXT NOT NULL CHECK(deletion_type IN ('user_input', 'feedback')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, message_id, deletion_type),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pending_deletions_session ON pending_message_deletions(session_id);

-- Durable operations
CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    caller_session_id TEXT NOT NULL,
    client_request_id TEXT,
    cwd TEXT NOT NULL,
    slug TEXT,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'completed', 'failed', 'stale', 'cancelled')),
    progress_phase TEXT,
    progress_decision TEXT,
    progress_reason TEXT,
    result_text TEXT,
    error_text TEXT,
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

-- Webhook contracts and outbox
CREATE TABLE IF NOT EXISTS webhook_contracts (
    id TEXT PRIMARY KEY,
    contract_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'api',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_contracts_active ON webhook_contracts(active);

CREATE TABLE IF NOT EXISTS webhook_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL,
    event_json TEXT NOT NULL,
    target_url TEXT NOT NULL,
    target_secret TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    locked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_webhook_outbox_status ON webhook_outbox(status);
CREATE INDEX IF NOT EXISTS idx_webhook_outbox_next_attempt ON webhook_outbox(next_attempt_at);

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
    agent TEXT PRIMARY KEY,
    available INTEGER DEFAULT 1,
    unavailable_until TEXT,
    reason TEXT,
    degraded_until TEXT
);

-- Voice assignments
CREATE TABLE IF NOT EXISTS voice_assignments (
    id TEXT PRIMARY KEY,
    service_name TEXT,
    voice TEXT DEFAULT '',
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_voice_assignments_assigned_at ON voice_assignments(assigned_at);

-- System settings (key-value)
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    identity_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_obs_session ON memory_observations(memory_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_obs_project ON memory_observations(project, created_at_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_memory_obs_type ON memory_observations(type);
CREATE INDEX IF NOT EXISTS idx_memory_obs_identity ON memory_observations(project, identity_key);

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
