-- TeleClaude Database Schema

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT,  -- NULL for headless sessions (standalone TTS/summarization)
    last_input_origin TEXT NOT NULL DEFAULT 'telegram',  -- Most recent input origin (e.g., "telegram", "cli")
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
    last_feedback_received TEXT,
    last_feedback_received_at TEXT,
    last_feedback_summary TEXT,  -- LLM-generated summary of last_feedback_received
    working_slug TEXT,  -- Slug of work item this session is working on (from state machine)
    lifecycle_status TEXT DEFAULT 'active'
    -- No unique constraint on (computer_name, tmux_session_name): tmux enforces
    -- its own name uniqueness, and headless sessions have NULL tmux_session_name.
);

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
