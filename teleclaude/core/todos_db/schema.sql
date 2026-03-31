-- Todo lifecycle database schema.
-- DB is the sole source of truth for todo state, roadmap, and artifacts.

CREATE TABLE IF NOT EXISTS roadmap (
    id              TEXT PRIMARY KEY,       -- UUID, stable identifier
    slug            TEXT NOT NULL,
    position        INTEGER NOT NULL,
    group_slug      TEXT,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    delivered_at    TEXT,
    delivered_commit TEXT,
    children        TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
-- Active/icebox slugs must be unique; delivered slugs allow reuse.
CREATE UNIQUE INDEX IF NOT EXISTS idx_roadmap_slug_active
    ON roadmap(slug) WHERE status IN ('active', 'icebox');

CREATE TABLE IF NOT EXISTS todo_state (
    id              TEXT PRIMARY KEY,       -- matches roadmap.id
    slug            TEXT NOT NULL,           -- denormalized for convenience
    state           TEXT NOT NULL,           -- JSON blob (schema v2)
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS todo_artifacts (
    id              TEXT NOT NULL,           -- matches roadmap.id
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
    id              TEXT NOT NULL,           -- matches roadmap.id
    slug            TEXT NOT NULL,           -- denormalized for convenience
    name            TEXT NOT NULL,
    content         TEXT NOT NULL,
    digest          TEXT NOT NULL,
    updated_by      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_av_id_name ON todo_artifact_versions(id, name, created_at);

CREATE TABLE IF NOT EXISTS roadmap_deps (
    slug            TEXT NOT NULL,
    depends_on      TEXT NOT NULL,
    PRIMARY KEY (slug, depends_on)
);
