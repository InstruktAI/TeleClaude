-- 0001_init.sql — initial Postgres schema for the workflow service.
--
-- The workflow service owns this schema. No other service queries it
-- directly; cross-service access goes through the `workflow` crate API.
--
-- Style: lowercase SQL keywords, 2-space indent, snake_case identifiers,
-- everything schema-qualified.
--
-- Identifier convention:
--   * Local `id` columns are BIGSERIAL — compact, fast joins, opaque to
--     callers. Used for foreign-key edges inside this schema.
--   * `uuid_id` columns expose the row to the rest of the system. The
--     Rust newtypes (e.g. `TodoId(Uuid)`) wrap these UUIDs; the BIGSERIAL
--     id is never crossed into application code.
--   * `(project_id, slug)` is the natural key for todos and roadmap
--     entries, mirroring v1's per-project slug uniqueness.

create extension if not exists "pgcrypto";  -- gen_random_uuid()

create schema workflow;

-- ---------------------------------------------------------------------------
-- Enum types
-- ---------------------------------------------------------------------------

-- Mirrors teleclaude.types.lifecycle.LifecyclePhase (snake_case string values).
-- The Rust LifecyclePhase enum uses serde rename_all = "snake_case"; literals
-- here ARE the contract — Rust must match.
create type workflow.lifecycle_phase as enum (
  'draft',
  'prd_drafting',
  'prd_human_approval',
  'architecture_drafting',
  'architecture_review',
  'architecture_human_approval',
  'test_specs_drafting',
  'test_specs_review',
  'test_specs_human_approval',
  'plan_drafting',
  'plan_review',
  'plan_human_approval',
  'prepared',
  'blocked',
  'build_started',
  'build_complete',
  'review_changes_requested',
  'review_approved',
  'finalize_ready',
  'handed_off'
);

-- Todo kind discriminator. Mirrors the v1 `kind` strings carried in the
-- todo_state JSON blob and the `--kind` flag of `telec todo create`.
create type workflow.todo_kind as enum (
  'feature',
  'bug',
  'refactor',
  'migration',
  'prepped'
);

-- Roadmap entry status. Mirrors v1's `roadmap.status` text column values.
-- See teleclaude/core/todos_db/schema.sql and _roadmap.py.
create type workflow.roadmap_status as enum (
  'active',
  'icebox',
  'delivered'
);

-- Canonical artifact names. Mirrors the `<name>` enum surface of
-- `telec todo artifacts {read,write,diff,remove}` (see CLI_SURFACE in
-- teleclaude/cli/telec.py).
create type workflow.artifact_name as enum (
  'input',
  'prd',
  'requirements',
  'architecture',
  'test-specs',
  'implementation-plan',
  'bug',
  'quality-checklist',
  'design-spec',
  'deferrals',
  'requirements-review-findings',
  'architecture-review-findings',
  'spec-review-findings',
  'plan-review-findings',
  'review-findings'
);

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- workflow.projects
-- v1 had no explicit projects table; project context was implicit per
-- todos.db file path. v2 makes the project an explicit, joinable entity so
-- a single workflow schema can host multiple projects.
create table workflow.projects (
  id          uuid        primary key default gen_random_uuid(),
  name        text        not null unique,
  root_path   text        not null,
  created_at  timestamptz not null default now()
);

-- workflow.roadmap_entries
-- Mirrors v1's `roadmap` table. Owns ordering, status (active/icebox/
-- delivered), delivery metadata, and the dependency edge set (carried as
-- a JSONB array of slugs for self-contained reads; the normalized edge
-- table below mirrors v1's roadmap_deps for relational queries).
create table workflow.roadmap_entries (
  id                bigserial               primary key,
  uuid_id           uuid                    not null default gen_random_uuid() unique,
  project_id        uuid                    not null,
  slug              text                    not null,
  position          integer                 not null,
  group_slug        text,
  description       text,
  status            workflow.roadmap_status not null default 'active',
  frozen            boolean                 not null default false,
  -- JSONB array of dependency slugs (e.g. '["foo", "bar"]'). The
  -- normalized roadmap_deps table below is the relational source of
  -- truth; this column is a denormalized convenience for read paths.
  after             jsonb                   not null default '[]'::jsonb,
  delivered_at      timestamptz,
  delivered_commit  text,
  created_at        timestamptz             not null default now(),
  updated_at        timestamptz             not null default now(),
  constraint fk_roadmap_entries_project
    foreign key (project_id) references workflow.projects (id) on delete restrict
);

-- Active and icebox slugs must be unique per project. Delivered slugs may
-- repeat (matches v1's partial-unique-index semantics on roadmap.slug).
create unique index idx_roadmap_entries_slug_active
  on workflow.roadmap_entries (project_id, slug)
  where status in ('active', 'icebox');

create index idx_roadmap_entries_project on workflow.roadmap_entries (project_id);
create index idx_roadmap_entries_status on workflow.roadmap_entries (status);

-- workflow.todos
-- Mirrors v1's `todo_state` table (which stored most fields as a JSON
-- blob). v2 promotes the queryable fields (kind, lifecycle_phase, etc.)
-- to typed columns; free-form state survives as a `state_extra` JSONB
-- bag for forward-compatibility during the v1 → v2 migration.
create table workflow.todos (
  id                  bigserial                  primary key,
  uuid_id             uuid                       not null default gen_random_uuid() unique,
  project_id          uuid                       not null,
  -- 1:1 link to the roadmap entry; cascades so deleting a roadmap entry
  -- removes its todo state (matches v1's shared-id design).
  roadmap_entry_id    bigint                     not null unique,
  slug                text                       not null,
  kind                workflow.todo_kind         not null,
  lifecycle_phase     workflow.lifecycle_phase   not null default 'draft',
  -- v1 carried free-form integration_phase / finalize_status strings in
  -- the JSON state blob; keep them as nullable text for now (typed enums
  -- can land in a later migration once the v2 contract stabilises).
  integration_phase   text,
  finalize_status     text,
  group_slug          text,
  description         text,
  -- Dependency slugs as JSONB array; see roadmap_entries.after.
  after               jsonb                      not null default '[]'::jsonb,
  -- Unmodelled v1 state fields land here so the v1 → v2 importer can
  -- preserve fidelity without dropping data.
  state_extra         jsonb                      not null default '{}'::jsonb,
  created_at          timestamptz                not null default now(),
  updated_at          timestamptz                not null default now(),
  delivered_at        timestamptz,
  constraint fk_todos_project
    foreign key (project_id) references workflow.projects (id) on delete restrict,
  constraint fk_todos_roadmap_entry
    foreign key (roadmap_entry_id) references workflow.roadmap_entries (id) on delete cascade
);

create unique index idx_todos_slug_per_project on workflow.todos (project_id, slug);
create index idx_todos_project on workflow.todos (project_id);
create index idx_todos_lifecycle_phase on workflow.todos (lifecycle_phase);
create index idx_todos_kind on workflow.todos (kind);

-- workflow.roadmap_deps
-- Normalized dependency edges between roadmap slugs within a project.
-- Mirrors v1's `roadmap_deps` table. Co-exists with the `after` JSONB
-- column on roadmap_entries / todos as the relational source of truth.
create table workflow.roadmap_deps (
  project_id  uuid not null,
  slug        text not null,
  depends_on  text not null,
  primary key (project_id, slug, depends_on),
  constraint fk_roadmap_deps_project
    foreign key (project_id) references workflow.projects (id) on delete cascade
);

create index idx_roadmap_deps_depends_on on workflow.roadmap_deps (project_id, depends_on);

-- workflow.artifacts
-- Current contents per (todo, artifact_name). Mirrors v1 todo_artifacts.
create table workflow.artifacts (
  id          bigserial               primary key,
  todo_id     bigint                  not null,
  name        workflow.artifact_name  not null,
  content     text                    not null default '',
  digest      text                    not null default '',
  updated_by  text,
  created_at  timestamptz             not null default now(),
  updated_at  timestamptz             not null default now(),
  constraint fk_artifacts_todo
    foreign key (todo_id) references workflow.todos (id) on delete cascade
);

create unique index idx_artifacts_todo_name on workflow.artifacts (todo_id, name);

-- workflow.artifact_versions
-- Append-only history of artifact writes. Mirrors v1
-- todo_artifact_versions; the digest column lets `telec todo artifacts
-- diff` resolve two snapshots without re-reading content.
create table workflow.artifact_versions (
  version_id  bigserial               primary key,
  todo_id     bigint                  not null,
  name        workflow.artifact_name  not null,
  content     text                    not null,
  digest      text                    not null,
  updated_by  text,
  created_at  timestamptz             not null default now(),
  constraint fk_artifact_versions_todo
    foreign key (todo_id) references workflow.todos (id) on delete cascade
);

create index idx_artifact_versions_todo_name_created
  on workflow.artifact_versions (todo_id, name, created_at);

-- workflow.state_transitions
-- Append-only log of lifecycle phase transitions per todo. `principal`
-- captures the actor (human or agent) as a JSONB document so the schema
-- does not depend on the identity service's shape.
create table workflow.state_transitions (
  id          bigserial                  primary key,
  todo_id     bigint                     not null,
  from_phase  workflow.lifecycle_phase,
  to_phase    workflow.lifecycle_phase   not null,
  signal      text,
  principal   jsonb                      not null default '{}'::jsonb,
  occurred_at timestamptz                not null default now(),
  constraint fk_state_transitions_todo
    foreign key (todo_id) references workflow.todos (id) on delete cascade
);

create index idx_state_transitions_todo_occurred
  on workflow.state_transitions (todo_id, occurred_at);

-- workflow.migrations_v1
-- One row per project successfully migrated from v1 (SQLite todos.db) to
-- v2 (this Postgres schema). The v1 → v2 importer (Wave G1) writes here
-- on completion; presence of a row signals "do not re-import."
create table workflow.migrations_v1 (
  project_name      text         primary key,
  migrated_at       timestamptz  not null default now(),
  source_db_sha256  text         not null,
  rows_migrated     integer      not null
);
