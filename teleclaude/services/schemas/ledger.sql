-- Ledger domain — permanent session archive with normalized blocks.
--
-- The ledger is the canonical session history. Native session ID is the
-- primary key. It does not know about TeleClaude session IDs — the
-- runtime schema points to the ledger, never the reverse.
--
-- Blocks are normalized from agent transcript files. Consumers read
-- structured blocks, never raw transcripts.

CREATE SCHEMA IF NOT EXISTS ledger;

-- Sessions: permanent session records keyed by native agent session ID.

CREATE TABLE ledger.sessions (
    native_id       TEXT PRIMARY KEY,
    agent           TEXT NOT NULL,
    computer        TEXT NOT NULL DEFAULT '',
    project         TEXT NOT NULL DEFAULT '',
    human_email     TEXT,
    title           TEXT NOT NULL DEFAULT '',
    summary         TEXT,
    started_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    message_count   INTEGER NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    visibility      TEXT NOT NULL DEFAULT 'private',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ledger_sessions_agent ON ledger.sessions (agent);
CREATE INDEX idx_ledger_sessions_human ON ledger.sessions (human_email);
CREATE INDEX idx_ledger_sessions_project ON ledger.sessions (project);
CREATE INDEX idx_ledger_sessions_started ON ledger.sessions (started_at);

-- Blocks: normalized session content — the canonical read model.

CREATE TABLE ledger.blocks (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES ledger.sessions(native_id) ON DELETE CASCADE,
    session_seq     INTEGER NOT NULL,
    block_type      TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    metadata        JSONB NOT NULL DEFAULT '{}',
    occurred_at     TIMESTAMPTZ NOT NULL,
    UNIQUE (session_id, session_seq)
);

CREATE INDEX idx_blocks_session ON ledger.blocks (session_id, session_seq);
CREATE INDEX idx_blocks_type ON ledger.blocks (block_type);

-- Full-text search on block content.

-- Note: Postgres FTS uses tsvector/tsquery instead of SQLite FTS5.
-- A generated column with GIN index provides fast full-text search.
ALTER TABLE ledger.blocks
    ADD COLUMN content_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

CREATE INDEX idx_blocks_fts ON ledger.blocks USING GIN (content_tsv);

-- Full-text search on session summaries.
ALTER TABLE ledger.sessions
    ADD COLUMN summary_tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', COALESCE(summary, ''))) STORED;

CREATE INDEX idx_sessions_fts ON ledger.sessions USING GIN (summary_tsv);

-- Projection state: tracks ingestion progress per session.

CREATE TABLE ledger.projections (
    session_id          TEXT PRIMARY KEY REFERENCES ledger.sessions(native_id) ON DELETE CASCADE,
    source_watermark    TEXT,
    last_projected_seq  INTEGER NOT NULL DEFAULT 0,
    projection_version  INTEGER NOT NULL DEFAULT 1,
    is_dirty            BOOLEAN NOT NULL DEFAULT FALSE,
    error_message       TEXT,
    projected_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_projections_dirty ON ledger.projections (is_dirty) WHERE is_dirty = TRUE;
