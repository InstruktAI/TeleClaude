-- TeleClaude Database Schema

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT,  -- NULL for headless sessions (standalone TTS/summarization)
    last_input_origin TEXT NOT NULL DEFAULT 'telegram',  -- Most recent input origin (InputOrigin.*.value)
    adapter_metadata TEXT,  -- JSON string for platform-specific data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP,
    terminal_size TEXT DEFAULT '80x24',
    project_path TEXT,  -- Base project path (first-class, no subdir)
    subdir TEXT,  -- Optional subdirectory/worktree relative to project_path
    description TEXT,  -- Description of why this session was created (for AI-to-AI sessions)
    initiated_by_ai BOOLEAN DEFAULT 0,  -- 0 = human-initiated (Opus), 1 = AI-initiated (Sonnet)
    initiator_session_id TEXT,  -- Session ID of the AI that created this session (for AI-to-AI nesting)
    -- UX state fields (migrated from JSON blob)
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
    last_output_raw TEXT,
    last_output_at TEXT,
    last_output_summary TEXT,  -- LLM-generated summary of last_output_raw
    working_slug TEXT,  -- Slug of work item this session is working on (from state machine)
    lifecycle_status TEXT DEFAULT 'active',
    last_memory_extraction_at TEXT,
    help_desk_processed_at TEXT,
    relay_status TEXT,
    relay_discord_channel_id TEXT,
    relay_started_at TEXT,
    human_email TEXT,
    human_role TEXT,
    user_role TEXT DEFAULT 'admin',
    transcript_files TEXT DEFAULT '[]'  -- JSON array of transcript file paths (chain for multi-file sessions)
    -- No unique constraint on (computer_name, tmux_session_name): tmux enforces
    -- its own name uniqueness, and headless sessions have NULL tmux_session_name.
);

-- Performance indexes for sessions table
CREATE INDEX IF NOT EXISTS idx_sessions_closed_at ON sessions(closed_at);
CREATE INDEX IF NOT EXISTS idx_sessions_lifecycle_status ON sessions(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_native_session_id ON sessions(native_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_initiator ON sessions(initiator_session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_computer ON sessions(computer_name);

-- Voice assignments for TTS (persists across tmux session restarts)
-- Two-phase storage:
-- 1. At tmux creation: store keyed by teleclaude_session_id (our session_id)
-- 2. When Agent session_start event arrives: copy to record keyed by native_session_id
-- On session reopen, lookup by native_session_id first (from ux_state), then assign new if not found.
-- Records expire after 7 days (cleaned up by daemon.cleanup_stale_voice_assignments)
CREATE TABLE IF NOT EXISTS voice_assignments (
    id TEXT PRIMARY KEY,  -- Either teleclaude_session_id or native_session_id
    service_name TEXT,
    voice TEXT DEFAULT '',
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for TTL cleanup queries
CREATE INDEX IF NOT EXISTS idx_voice_assignments_assigned_at ON voice_assignments(assigned_at);

-- Pending message deletions (replaces pending_deletions/pending_feedback_deletions lists from ux_state)
CREATE TABLE IF NOT EXISTS pending_message_deletions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    deletion_type TEXT NOT NULL CHECK(deletion_type IN ('user_input', 'feedback')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, message_id, deletion_type),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pending_deletions_session
    ON pending_message_deletions(session_id);

-- Key-value store for system settings
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agent availability tracking for next-machine workflow
-- Tracks temporary unavailability due to rate limits, quotas, or outages
CREATE TABLE IF NOT EXISTS agent_availability (
    agent TEXT PRIMARY KEY,           -- "codex", "claude", "gemini"
    available INTEGER DEFAULT 1,      -- 0 = unavailable, 1 = available
    unavailable_until TEXT,           -- ISO timestamp, NULL if available
    degraded_until TEXT,              -- ISO timestamp for degraded state expiry
    reason TEXT                       -- "quota_exhausted", "rate_limited", "service_outage"
);

-- Hook outbox for durable agent events (fire-and-forget with retry)
CREATE TABLE IF NOT EXISTS hook_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,            -- JSON payload (data dict)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
    attempt_count INTEGER DEFAULT 0,
    last_error TEXT,
    delivered_at TEXT,
    locked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_hook_outbox_pending ON hook_outbox(delivered_at, next_attempt_at);

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

-- Memory observations (ported from memory-management-api)
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
    identity_key TEXT,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_obs_project ON memory_observations(project, created_at_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_memory_obs_session ON memory_observations(memory_session_id);
CREATE INDEX IF NOT EXISTS idx_memory_obs_type ON memory_observations(type);
CREATE INDEX IF NOT EXISTS idx_memory_obs_identity ON memory_observations(project, identity_key);

-- Memory summaries
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

CREATE INDEX IF NOT EXISTS idx_memory_sum_project ON memory_summaries(project, created_at_epoch DESC);
CREATE INDEX IF NOT EXISTS idx_memory_sum_session ON memory_summaries(memory_session_id);

-- Manual sessions for API-created memory observations (one per project)
CREATE TABLE IF NOT EXISTS memory_manual_sessions (
    memory_session_id TEXT PRIMARY KEY,
    project TEXT UNIQUE NOT NULL,
    created_at_epoch INTEGER NOT NULL
);

-- Webhook contracts for subscriber-first event routing
CREATE TABLE IF NOT EXISTS webhook_contracts (
    id TEXT PRIMARY KEY,
    contract_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'api',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_webhook_contracts_active ON webhook_contracts(active);

-- Webhook outbox for durable external delivery
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

-- Inbound message queue for guaranteed delivery (enqueue-first, worker-drain pattern)
CREATE TABLE IF NOT EXISTS inbound_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    origin TEXT NOT NULL,                -- InputOrigin value (discord, telegram, terminal, webhook, ...)
    message_type TEXT NOT NULL DEFAULT 'text' CHECK(message_type IN ('text', 'voice', 'file')),
    content TEXT NOT NULL DEFAULT '',    -- Text content (or empty for voice/file)
    payload_json TEXT,                   -- JSON: voice URL, file_id, or other adapter-specific data
    actor_id TEXT,
    actor_name TEXT,
    actor_avatar_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'delivered', 'failed', 'expired')),
    created_at TEXT NOT NULL,
    processed_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,                  -- NULL = eligible immediately; future ISO = retry after this time
    last_error TEXT,
    locked_at TEXT,
    source_message_id TEXT,              -- Platform message ID for dedup (e.g. Discord message.id)
    source_channel_id TEXT               -- Platform channel ID for additional context
);

CREATE INDEX IF NOT EXISTS idx_inbound_queue_session_status
    ON inbound_queue(session_id, status, next_retry_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_inbound_queue_source_dedup
    ON inbound_queue(origin, source_message_id)
    WHERE source_message_id IS NOT NULL;

-- Session listeners for durable PUB-SUB stop notifications
-- Survives daemon restarts (previously in-memory only)
CREATE TABLE IF NOT EXISTS session_listeners (
    target_session_id TEXT NOT NULL,
    caller_session_id TEXT NOT NULL,
    caller_tmux_session TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    PRIMARY KEY (target_session_id, caller_session_id)
);
CREATE INDEX IF NOT EXISTS idx_session_listeners_caller
    ON session_listeners(caller_session_id);

-- Shared conversation links for direct peer conversations and future gathering orchestration
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

CREATE INDEX IF NOT EXISTS idx_conversation_links_status
    ON conversation_links(status);

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

CREATE INDEX IF NOT EXISTS idx_conversation_link_members_session
    ON conversation_link_members(session_id);
