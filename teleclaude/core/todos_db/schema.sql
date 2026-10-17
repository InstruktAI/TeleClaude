-- Todo lifecycle database schema.
-- DB is the sole source of truth for todo state, entries, and artifacts.

CREATE TABLE IF NOT EXISTS todo (
    id              TEXT PRIMARY KEY,       -- UUID, stable identifier
    slug            TEXT NOT NULL,
    ready_since     TEXT,
    schedule        TEXT,
    group_slug      TEXT,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    delivered_at    TEXT,
    delivered_commit TEXT,
    children        TEXT,
    lineage         TEXT,            -- Creation Record: chain-root authority [>acting agent session] (audit/attribution)
    entry_point     TEXT,            -- Creation Record: creation door (tui|cli|agent|split)
    human_involved  INTEGER NOT NULL DEFAULT 0,  -- Creation Record: derived true for human doors, declared for agent
    context         TEXT,            -- Creation Record: door-specific reference data (e.g. split's parent slug)
    removed_doc_reconciliation TEXT, -- Exact pending-documentation tombstone snapshot
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
-- Active/icebox slugs must be unique; delivered slugs allow reuse.
CREATE UNIQUE INDEX IF NOT EXISTS idx_todo_slug_active
    ON todo(slug) WHERE status IN ('active', 'icebox');

CREATE TABLE IF NOT EXISTS todo_state (
    id              TEXT PRIMARY KEY,       -- matches todo.id
    slug            TEXT NOT NULL,           -- denormalized for convenience
    state           TEXT NOT NULL,           -- JSON blob (schema v2)
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS todo_artifacts (
    id              TEXT NOT NULL,           -- matches todo.id
    slug            TEXT NOT NULL,           -- denormalized for convenience
    name            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    digest          TEXT NOT NULL DEFAULT '',
    updated_by      TEXT,
    updated_at      TEXT,
    PRIMARY KEY (id, name)
);

CREATE TABLE IF NOT EXISTS todo_artifact_versions (
    version_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    id              TEXT NOT NULL,           -- matches todo.id
    slug            TEXT NOT NULL,           -- denormalized for convenience
    name            TEXT NOT NULL,
    content         TEXT NOT NULL,
    digest          TEXT NOT NULL,
    updated_by      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_av_id_name ON todo_artifact_versions(id, name, created_at);

CREATE TABLE IF NOT EXISTS todo_deps (
    slug            TEXT NOT NULL,
    depends_on      TEXT NOT NULL,
    PRIMARY KEY (slug, depends_on)
);

CREATE TABLE IF NOT EXISTS todo_docs_local_identity_cutovers (
    migration_key   TEXT PRIMARY KEY,
    completed_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commit_review (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sha                 TEXT NOT NULL,
    verdict             TEXT NOT NULL,
    reviewer_session_id TEXT NOT NULL,
    producer_session_ids TEXT,
    stamped_at          TEXT NOT NULL,
    reason              TEXT NOT NULL DEFAULT '',
    migration_source    TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_commit_review_sha ON commit_review(sha, id);

CREATE TABLE IF NOT EXISTS documentation_transfer (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_slug          TEXT NOT NULL,
    target_slug          TEXT NOT NULL,
    parent_id            TEXT NOT NULL,
    source_sha           TEXT,
    source_path_blobs    TEXT NOT NULL,
    target_path_blobs    TEXT NOT NULL,
    transition_id        TEXT NOT NULL,
    reconciliation_commit TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documentation_transfer_target ON documentation_transfer(target_slug, id);
