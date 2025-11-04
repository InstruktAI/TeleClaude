-- TeleClaude Database Schema

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT NOT NULL,
    adapter_type TEXT NOT NULL DEFAULT 'telegram',
    adapter_metadata TEXT,  -- JSON string for platform-specific data
    closed BOOLEAN DEFAULT 0,  -- 0 = active, 1 = closed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    terminal_size TEXT DEFAULT '80x24',
    working_directory TEXT DEFAULT '~',
    command_count INTEGER DEFAULT 0,
    output_message_id TEXT,  -- Current output message ID for appending status (non-NULL = polling active)
    idle_notification_message_id TEXT,  -- Idle notification message ID (for "no output for N seconds" messages)
    UNIQUE(computer_name, tmux_session_name)
);

CREATE INDEX IF NOT EXISTS idx_sessions_closed ON sessions(closed);
CREATE INDEX IF NOT EXISTS idx_sessions_computer ON sessions(computer_name);
CREATE INDEX IF NOT EXISTS idx_sessions_adapter ON sessions(adapter_type);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON sessions(last_activity);

CREATE TABLE IF NOT EXISTS recordings (
    recording_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    recording_type TEXT NOT NULL,  -- 'text' or 'video'
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recordings_session ON recordings(session_id);
CREATE INDEX IF NOT EXISTS idx_recordings_timestamp ON recordings(timestamp);
CREATE INDEX IF NOT EXISTS idx_recordings_type ON recordings(recording_type);
