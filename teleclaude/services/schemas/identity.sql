-- Identity domain — people, credentials, roles.
--
-- People are domain entities, not config entries. They have credentials
-- across platforms, roles that determine access, and profiles that
-- drive attunement and memory extraction focus.

CREATE SCHEMA IF NOT EXISTS identity;

-- People: the canonical person registry.

CREATE TABLE identity.people (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    email       TEXT NOT NULL UNIQUE,
    role        TEXT NOT NULL DEFAULT 'newcomer',
    profile     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_people_email ON identity.people (email);
CREATE INDEX idx_people_role ON identity.people (role);

-- Credentials: per-platform identifiers for a person.

CREATE TABLE identity.credentials (
    id          BIGSERIAL PRIMARY KEY,
    person_id   BIGINT NOT NULL REFERENCES identity.people(id) ON DELETE CASCADE,
    platform    TEXT NOT NULL,
    platform_user_id    TEXT,
    platform_username   TEXT,
    platform_chat_id    TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (person_id, platform)
);

CREATE INDEX idx_credentials_person ON identity.credentials (person_id);
CREATE INDEX idx_credentials_platform ON identity.credentials (platform, platform_user_id);
