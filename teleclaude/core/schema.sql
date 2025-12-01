-- TeleClaude Database Schema

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT NOT NULL,
    origin_adapter TEXT NOT NULL DEFAULT 'telegram',  -- Single origin adapter (e.g., "telegram", "redis")
    adapter_metadata TEXT,  -- JSON string for platform-specific data
    closed BOOLEAN DEFAULT 0,  -- 0 = active, 1 = closed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    terminal_size TEXT DEFAULT '80x24',
    working_directory TEXT DEFAULT '~',
    description TEXT,  -- Description of why this session was created (for AI-to-AI sessions)
    ux_state TEXT,  -- JSON blob: {output_message_id, idle_notification_message_id, polling_active, claude_session_file, ...}
    UNIQUE(computer_name, tmux_session_name)
);

-- Key-value store for system settings
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
