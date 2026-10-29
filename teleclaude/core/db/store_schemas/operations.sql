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
