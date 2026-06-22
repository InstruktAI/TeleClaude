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
    created_by_principal TEXT,       -- resolved principal of the creating caller (audit/attribution)
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

CREATE TABLE IF NOT EXISTS todo_dispatch_claims (
    slug            TEXT NOT NULL,
    lane            TEXT NOT NULL,
    owner           TEXT NOT NULL,
    claimed_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    PRIMARY KEY (slug, lane)
);
