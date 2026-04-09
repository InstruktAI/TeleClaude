-- Work domain — todos, artifacts, roadmap.
--
-- Supports any domain's work lifecycle (SDLC, CRM, marketing) via
-- the domain discriminator column. State machines in application code
-- define valid phases per domain.

CREATE SCHEMA IF NOT EXISTS work;

-- Roadmap: ordered work items with dependencies and grouping.

CREATE TABLE work.roadmap (
    id          TEXT PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    domain      TEXT NOT NULL DEFAULT 'sdlc',
    description TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'feature',
    "group"     TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending',
    parent_id   TEXT REFERENCES work.roadmap(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_roadmap_domain ON work.roadmap (domain);
CREATE INDEX idx_roadmap_status ON work.roadmap (status);
CREATE INDEX idx_roadmap_position ON work.roadmap (position);
CREATE INDEX idx_roadmap_parent ON work.roadmap (parent_id);

-- Dependencies between roadmap entries.

CREATE TABLE work.roadmap_deps (
    id          TEXT NOT NULL REFERENCES work.roadmap(id) ON DELETE CASCADE,
    depends_on  TEXT NOT NULL REFERENCES work.roadmap(id) ON DELETE CASCADE,
    PRIMARY KEY (id, depends_on)
);

-- Todo state: phase/status tracking for the work lifecycle.

CREATE TABLE work.todo_state (
    id          TEXT PRIMARY KEY REFERENCES work.roadmap(id) ON DELETE CASCADE,
    slug        TEXT NOT NULL,
    state       JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Artifacts: content attached to work items.

CREATE TABLE work.artifacts (
    id          BIGSERIAL PRIMARY KEY,
    todo_id     TEXT NOT NULL REFERENCES work.roadmap(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (todo_id, name)
);

CREATE INDEX idx_artifacts_todo ON work.artifacts (todo_id);

-- Artifact versions: historical snapshots for audit trail.

CREATE TABLE work.artifact_versions (
    id          BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT NOT NULL REFERENCES work.artifacts(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_artifact_versions_artifact ON work.artifact_versions (artifact_id);
