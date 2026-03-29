-- Todo lifecycle database schema.
-- Replaces filesystem-based state.yaml, roadmap.yaml, delivered.yaml, and artifact files.

CREATE TABLE IF NOT EXISTS todo_state (
    slug            TEXT PRIMARY KEY,
    state           TEXT NOT NULL,           -- JSON blob (schema v2)
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS todo_artifacts (
    slug            TEXT NOT NULL,
    name            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    digest          TEXT NOT NULL DEFAULT '',
    updated_by      TEXT,
    updated_at      TEXT,
    PRIMARY KEY (slug, name)
);

CREATE TABLE IF NOT EXISTS todo_artifact_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT NOT NULL,
    name            TEXT NOT NULL,
    content         TEXT NOT NULL,
    digest          TEXT NOT NULL,
    updated_by      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_av_slug_name ON todo_artifact_versions(slug, name, created_at);

CREATE TABLE IF NOT EXISTS roadmap (
    slug            TEXT PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS roadmap_deps (
    slug            TEXT NOT NULL,
    depends_on      TEXT NOT NULL,
    PRIMARY KEY (slug, depends_on)
);
