-- 0001_init.sql — initial Postgres schema for the identity service.
--
-- The identity service owns this schema. No other service queries it
-- directly; cross-service access goes through the `identity` crate API.
--
-- Style mirrors workflow/migrations/0001_init.sql: lowercase SQL keywords,
-- 2-space indent, snake_case identifiers, everything schema-qualified.
--
-- Modeling choices:
--   * `identity.role` is a Postgres enum mirroring identity::models::Role.
--     The Rust enum uses serde + sqlx rename_all = "snake_case"; the SQL
--     literals here ARE the contract.
--   * `identity.principal_kind` is a Postgres enum mirroring the kind tag of
--     identity::models::Principal. Per the auth model anonymous principals
--     are never materialized; the enum keeps the tag for completeness and
--     parity with the Rust type.
--   * `identity.principals` is a single table whose payload columns are
--     null-or-not-null by kind. Check constraints enforce the per-kind
--     shape so the schema mirrors the Rust enum variants byte-for-byte.
--   * Session tokens are UUIDs (matching v1's `str(uuid.uuid4())` shape)
--     with revocation as the only lifecycle boundary — no TTL column,
--     no background sweeper. See auth-model.md.

create extension if not exists "pgcrypto";  -- gen_random_uuid()

create schema identity;

-- ---------------------------------------------------------------------------
-- Enum types
-- ---------------------------------------------------------------------------

create type identity.role as enum (
  'owner',
  'admin',
  'member',
  'contributor',
  'newcomer'
);

create type identity.principal_kind as enum (
  'human',
  'agent_session',
  'system',
  'anonymous'
);

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- identity.principals
-- Stores the durable principals known to the system: humans (by email),
-- agent sessions (by session id), and system service identities (by
-- service name). Anonymous principals are not stored — they are returned
-- by resolution when no auth evidence is present.
create table identity.principals (
  id          bigserial                  primary key,
  uuid_id     uuid                       not null default gen_random_uuid() unique,
  kind        identity.principal_kind    not null,
  email       text,
  session_id  uuid,
  service     text,
  role        identity.role,
  created_at  timestamptz                not null default now(),

  constraint principals_shape_matches_kind check (
    (kind = 'human'
      and email is not null and role is not null
      and session_id is null and service is null) or
    (kind = 'agent_session'
      and session_id is not null and role is not null
      and email is null and service is null) or
    (kind = 'system'
      and service is not null
      and email is null and session_id is null and role is null) or
    (kind = 'anonymous'
      and email is null and session_id is null
      and service is null and role is null)
  )
);

-- Per-kind uniqueness. Partial unique indexes let one column carry the
-- natural key for one kind without colliding with the null payload of
-- other kinds.
create unique index principals_human_email_uq
  on identity.principals(email)
  where kind = 'human';

create unique index principals_agent_session_uq
  on identity.principals(session_id)
  where kind = 'agent_session';

create unique index principals_system_service_uq
  on identity.principals(service)
  where kind = 'system';

-- identity.session_tokens
-- Tokens issued to agent sessions. v1 used opaque UUID strings; v2 keeps
-- the same surface. Revocation flips `revoked_at`; the row is retained so
-- post-mortem tooling can correlate token use with session lifecycle.
--
-- `session_id` is duplicated alongside the principal FK so revocation by
-- session id is a fast indexed update without joining principals.
create table identity.session_tokens (
  token         uuid           primary key default gen_random_uuid(),
  principal_id  bigint         not null references identity.principals(id) on delete cascade,
  session_id    uuid           not null,
  role          identity.role  not null,
  created_at    timestamptz    not null default now(),
  revoked_at    timestamptz
);

create index session_tokens_session_idx
  on identity.session_tokens(session_id);

create index session_tokens_active_idx
  on identity.session_tokens(principal_id)
  where revoked_at is null;
