---
id: project/spec/domain/memory
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-memory, v2-memory-cutover]
description: Memory bounded context — durable observations agents store and query. Per-principal, per-project, full-text searchable. Foundation for cross-session continuity.
---

# Memory Domain Spec — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `memory` bounded context owns durable observations the platform accumulates — facts, gotchas, decisions, patterns worth remembering across sessions and projects. Each observation is authored by an agent (or human via CLI) at runtime, persists in Postgres, and is queryable by full-text search + filters.

Memory is distinct from:

- **Context** (docs/skills/agents) — authored, schema-validated, deployed reference content. Static.
- **Session_mirrors** — eternal session transcripts. Per-session, full text.
- **Memory** — curated observations. Per-fact, agent-authored, dynamic.

Both `agent_runtime.session.ended` consumers and the mining-via-CLI pattern (see `transport-rules.md`) can produce memories — the latter via `telec memory save`.

This context does NOT own: docs/skills/agents (`context`), session transcripts (`session_mirrors`), workflow state (`workflow`), live agent sessions (`agent_runtime`).

## Canonical fields

### Ubiquitous language

**Observation**
: The atomic unit of memory. A discrete fact, gotcha, decision, or pattern worth remembering. Identified by its own UUID. Persisted in Postgres.

**Observation type**
: Categorical tag for the observation: `gotcha`, `decision`, `pattern`, `preference`, `relationship`, `fact`. Free-form extensible per project conventions.

**Title**
: Short human-readable label (typical: under 80 chars). Used in list/search rendering.

**Body**
: The observation content. Free-form text. Search-indexed.

**Author principal**
: The principal that authored the observation. Resolved by `identity`. Used for filtering ("show me observations I made") and audit.

**Project scope**
: Optional project the observation pertains to. Per `project_slug`. Cross-project observations leave this null.

**Anchor**
: Optional reference to another observation that this observation relates to. Enables timeline queries ("show observations around anchor X").

**Saved_at, updated_at**
: Timestamps. Saved_at is immutable; updated_at advances on edits.

**Timeline**
: Query returning observations chronologically before/after an anchor observation. Used for "what was happening around this decision."

### Aggregates

#### Observation (aggregate)

- **Root:** `Observation`
- **Contains:** `observation_id` (UUID, own identity); `type`; `title`; `body`; `author_principal` (email for human, id for machine, session_id for session principal); `project_slug` (nullable); `anchor_id` (nullable, references another observation); `saved_at`; `updated_at`.
- **Invariants:**
  - `observation_id` is a UUID generated at creation; never reused.
  - `body` is search-indexed; full-text search returns matches against it + title.
  - `author_principal` is set at creation by `identity` resolution; never mutated.
  - `saved_at` is immutable.
  - `anchor_id`, if set, references an existing observation in this schema (FK enforced).
  - Observations are mutable (`updated_at`, `title`, `body`, `type`, `project_slug`) but the author cannot be changed.
- **Identifier:** `observation_id`.
- **Lifecycle:** Created via `telec memory save`. Mutated via `telec memory update`. Removed via `telec memory delete`. Persists in Postgres indefinitely until explicit delete.

### Domain events emitted

#### `memory.observation.saved`

- **Producer:** `memory`
- **Emitted when:** a new observation is persisted.
- **Payload:** `observation_id`, `type`, `title`, `author_principal`, `project_slug`, `saved_at`.
- **Visibility:** CLUSTER
- **Known consumers:** audit log consumers; future "memory miner" that observes patterns in observations.
- **Idempotency key:** `observation_id`.
- **Posture:** `commit-then-emit`.

#### `memory.observation.deleted`

- **Producer:** `memory`
- **Emitted when:** an observation is removed via `telec memory delete`.
- **Payload:** `observation_id`, `deleted_at`, `deleted_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** audit log consumers.
- **Idempotency key:** `observation_id`.
- **Posture:** `commit-then-emit`.

### Domain events consumed

#### `config.effective.updated`

- **Producer:** `config`
- **Reaction:** invalidate cached configuration values used by memory (retention policies if added, per-project scoping defaults).
- **Failure handling:** stale config tolerated for one request.

### Use cases

#### UC-MEM-1: Save an observation

```
Given an agent (or human) wants to remember a fact
When they run `telec memory save "<text>" [--type gotcha] [--title "<short>"] [--project <slug>]`
Then memory resolves the caller's principal via identity
And creates a new Observation row with own UUID
And emits memory.observation.saved
And returns the observation_id
```

#### UC-MEM-2: Full-text search

```
Given an agent needs to recall observations matching a query
When they run `telec memory search "<query>" [--type <t>] [--project <slug>] [--author <principal>] [--limit N]`
Then memory runs full-text search against title + body
And filters by type/project/author as specified
And returns matching observations with snippet excerpts (query-centered)
```

#### UC-MEM-3: List recent observations

```
Given an agent wants context on recent observations
When they run `telec memory list [--limit N] [--type <t>] [--project <slug>]`
Then memory returns the N most recent observations matching filters
And ordered by saved_at descending
```

#### UC-MEM-4: Timeline around an anchor

```
Given an agent has an observation_id of interest
When they run `telec memory timeline <id> [--before N] [--after N] [--project <slug>]`
Then memory returns the N observations saved before and after the anchor
And ordered chronologically
And bounded by the project_slug filter if given
```

#### UC-MEM-5: Update or delete

```
Given an observation exists
When the author (or an authorized operator) runs `telec memory update <id> --title <t>` or `--body <text>`
Then memory updates the fields, advances updated_at
And emits memory.observation.saved (treated as a revision)

When delete is invoked:
Then memory removes the row, emits memory.observation.deleted
```

#### UC-MEM-6: Mining-driven memory (consumer-of-agent_runtime pattern)

```
Given an intelligence agent (the memory miner) is running on scheduler ticks
When the miner reads new agent_runtime windows via `telec sessions extract-window --consumer memory-miner`
Then the miner reasons about the window content
And for each pattern worth remembering, the miner calls `telec memory save "<observation>" --type pattern`
And the miner calls `telec sessions ack --consumer memory-miner --position <X>` to advance its cursor
And memory accumulates observations without knowing the miner exists — the miner is just another CLI caller
```

### v1 inventory (applies_to: v1, status: actual)

- `docs/project/spec/feature/memory/observation-save.md` — Save a memory observation: default-project fallback, auto-title derivation, per-project manual-session reuse, identity tagging.
- `docs/project/spec/feature/memory/observation-recent-list.md` — `telec memories list` — CLI-only verb implemented as an empty-query search that lands in the LIKE fallback.
- `docs/project/spec/feature/memory/observation-full-text-search.md` — `GET /api/memory/search` — FTS5 primary path with LIKE fallback; project, type, and identity filters.
- `docs/project/spec/feature/memory/observation-timeline.md` — `GET /api/memory/timeline` — chronological window of observations around an anchor id.
- `docs/project/spec/feature/memory/observation-delete.md` — `DELETE /api/memory/{id}` — hard delete; FTS5 trigger keeps the index in sync.
- `docs/project/spec/feature/memory/observation-bulk-fetch.md` — `POST /api/memory/batch` — HTTP-only convenience over `SELECT … IN (…)`.
- `docs/project/spec/feature/memory/memory-context-injection.md` — Render recent observations as Markdown for agent context injection (async HTTP `/inject` and sync in-process via the hook receiver).
- `docs/project/spec/feature/memory/observation-type-taxonomy.md` — The closed seven-value v1 type set (`preference, decision, discovery, gotcha, pattern, friction, context`) with `discovery` as default.
- `docs/project/spec/feature/memory/identity-key-ownership.md` — v1's per-row identity ownership: opaque string at save, inclusion-of-unscoped semantic at query, HTTP-only access surface.

### Context map position

- **Customer-Supplier downstream of `identity`** — every save/update/delete resolves and records the author principal; queries filter by author.
- **Customer-Supplier downstream of `config`** — reads retention policy (if any), per-project defaults.
- **Open Host Service to any caller** — agents save and query memory throughout their work; humans via CLI.
- **NO partnership with `session_mirrors`** — they're related (both about historical knowledge) but operate independently. Memory is per-fact; mirrors are per-session. The mining-via-CLI pattern (intelligence + scheduler bridge + extract-window) is what bridges them when bridging is wanted, but the architectures stay separate.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/memory/` module. The v2 ACL preserves the public CLI surface (`telec memories list/search/save/delete/timeline`) during the parallel-capable phase.

## Allowed values

- `type`: `gotcha`, `decision`, `pattern`, `preference`, `relationship`, `fact` (extensible; project conventions add more).

## Known caveats

- **Postgres-backed.** Schema: `memory.observations` with full-text index on (title || body). TOAST handles large body content transparently.
- **Per-principal authoring; per-project optional scoping.** Memory is multi-tenant by principal; project scoping is opt-in per observation.
- **No retention policy by default.** Observations persist indefinitely. Operators can add a retention policy via config if needed; default is forever.
- **Mining is OUTSIDE this context.** The memory miner is an intelligence agent that uses `telec sessions extract-window` and writes via `telec memory save`. No code in memory's crate concerns mining.
- **No vector search.** Full-text search over title + body is the primary retrieval. If semantic search becomes a need, it goes through a separate adapter, not memory's primary surface.
- **`anchor_id` enables timeline traversal.** Not required for normal operation; useful for connecting related observations.
- **Authoring authorization is principal-based.** Any principal can save observations as themselves. Updating/deleting requires being the author OR an authorized operator (admin role).
