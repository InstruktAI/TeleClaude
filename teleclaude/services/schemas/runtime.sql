-- Runtime domain — ephemeral session state, tmux mappings, adapter state.
--
-- These records have a 72-hour lifecycle. They represent active or
-- recently-active TeleClaude-managed sessions. The ledger schema holds
-- the permanent archive; runtime is the daemon's working set.

CREATE SCHEMA IF NOT EXISTS runtime;

-- Active sessions: the daemon's view of managed sessions.

CREATE TABLE runtime.sessions (
    session_id          TEXT PRIMARY KEY,
    native_session_id   TEXT,
    computer_name       TEXT NOT NULL,
    agent               TEXT NOT NULL,
    project_name        TEXT,
    project_root        TEXT,
    title               TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    tmux_session_name   TEXT,
    tmux_pane_id        TEXT,
    principal           TEXT,
    human_email         TEXT,
    human_role          TEXT,
    initiator_session_id TEXT,
    origin_metadata     JSONB,
    adapter_metadata    JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity       TIMESTAMPTZ,
    closed_at           TIMESTAMPTZ
);

CREATE INDEX idx_sessions_status ON runtime.sessions (status);
CREATE INDEX idx_sessions_computer ON runtime.sessions (computer_name);
CREATE INDEX idx_sessions_agent ON runtime.sessions (agent);
CREATE INDEX idx_sessions_native ON runtime.sessions (native_session_id);
CREATE INDEX idx_sessions_human ON runtime.sessions (human_email);
CREATE INDEX idx_sessions_initiator ON runtime.sessions (initiator_session_id);

-- Session tokens: auth tokens for daemon-spawned agent sessions.

CREATE TABLE runtime.session_tokens (
    token       TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES runtime.sessions(session_id) ON DELETE CASCADE,
    principal   TEXT NOT NULL,
    role        TEXT NOT NULL,
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at  TIMESTAMPTZ
);

CREATE INDEX idx_tokens_session ON runtime.session_tokens (session_id);

-- Operations: durable receipts for async operations.

CREATE TABLE runtime.operations (
    operation_id    TEXT PRIMARY KEY,
    session_id      TEXT,
    command_type    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    result          JSONB,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_operations_session ON runtime.operations (session_id);
CREATE INDEX idx_operations_status ON runtime.operations (status);

-- Session listeners: in-memory registry backed by persistent subscriptions.

CREATE TABLE runtime.session_listeners (
    id              BIGSERIAL PRIMARY KEY,
    target_session  TEXT NOT NULL,
    caller_session  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_listeners_target ON runtime.session_listeners (target_session);

-- Settings: per-session or global runtime settings.

CREATE TABLE runtime.settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
