-- Context domain — doc snippet reflections and memory observations.
--
-- Snippets are read-only reflections of git-tracked markdown files,
-- synced by the file watcher. They are the fast-query layer for
-- `telec docs index` and `telec docs get`.
--
-- Memories are durable observations about people, scraped from sessions
-- by automated agents. They persist across sessions and drive context
-- injection for future interactions.

CREATE SCHEMA IF NOT EXISTS context;

-- Snippets: read-only reflections of doc files from git repositories.

CREATE TABLE context.snippets (
    id              TEXT PRIMARY KEY,
    project         TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT '',
    scope           TEXT NOT NULL DEFAULT '',
    snippet_type    TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    file_path       TEXT,
    frontmatter     JSONB NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_snippets_project ON context.snippets (project);
CREATE INDEX idx_snippets_domain ON context.snippets (domain);
CREATE INDEX idx_snippets_scope ON context.snippets (scope);
CREATE INDEX idx_snippets_type ON context.snippets (snippet_type);

-- Full-text search on snippet content and description.
ALTER TABLE context.snippets
    ADD COLUMN search_tsv TSVECTOR
    GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(description, '') || ' ' || COALESCE(content, ''))
    ) STORED;

CREATE INDEX idx_snippets_fts ON context.snippets USING GIN (search_tsv);

-- Memories: durable observations about people, scraped from sessions.

CREATE TABLE context.memories (
    id              BIGSERIAL PRIMARY KEY,
    project         TEXT NOT NULL DEFAULT '',
    person_email    TEXT,
    title           TEXT NOT NULL DEFAULT '',
    observation     TEXT NOT NULL,
    observation_type TEXT NOT NULL DEFAULT 'context',
    source_session  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_memories_project ON context.memories (project);
CREATE INDEX idx_memories_person ON context.memories (person_email);
CREATE INDEX idx_memories_type ON context.memories (observation_type);

-- Full-text search on memory observations.
ALTER TABLE context.memories
    ADD COLUMN observation_tsv TSVECTOR
    GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(title, '') || ' ' || observation)
    ) STORED;

CREATE INDEX idx_memories_fts ON context.memories USING GIN (observation_tsv);
