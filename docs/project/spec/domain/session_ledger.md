---
id: project/spec/domain/session_ledger
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-session-ledger, v2-session-ledger-cutover]
description: Session Ledger bounded context — canonical persisted record of agent sessions. Block-level normalized storage, deterministic ordering, windowed reads, search-ready projections.
---

# Session Ledger Domain Spec — Spec

## Required reads

- @docs/global/software-development/principle/domain-driven-design.md
- @docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `session_ledger` bounded context owns the durable, canonical record of agent sessions — what happened during each session, block by block, in deterministic order. It ingests raw transcripts produced by `agent_runtime`, normalizes them into typed blocks (user text, assistant text, thinking, tool use, tool result, compaction), persists them in Postgres, and exposes windowed/delta/search read interfaces for consumers (frontend timelines, UI adapters, history search).

This context is the system of record for session history. Consumers (web UI, `telec history`, search) STOP parsing transcript files directly; they read from the ledger. The v1 `mirrors/` and `history/` modules are replaced by this service.

This context does NOT own: live session state (`agent_runtime` owns that), workflow state (`workflow`), knowledge content (`knowledge`), or the act of producing transcripts (`agent_runtime` produces, ledger ingests).

## Canonical fields

### Ubiquitous language

**Session** (per glossary — historical record dimension)
:  Here, the persisted record of an agent session: identified by the same `session_id` agent_runtime uses, but representing the durable history rather than live state. The ledger's session record outlives the live session.

**Block**
:  The atomic unit of session history. One block per consumer-visible event in the conversation: user text, assistant text, thinking, tool use, tool result, compaction. Stored as a normalized row in `session_ledger.blocks`.

**Block kind**
:  Categorical label for the block: `user_text`, `assistant_text`, `thinking`, `tool_use`, `tool_result`, `compaction`. The taxonomy is fixed; new kinds require schema migration.

**Session_seq**
:  Per-session monotonic integer that orders blocks within the session. The canonical delta/read cursor. Strictly increasing; never gaps.

**Cursor**
:  A consumer's bookmark within a session: `(session_id, last_seen_session_seq)`. Consumers persist their own cursor durably and advance it as they process blocks.

**Projection**
:  A read model derived from blocks, materialized for fast access by a specific consumer pattern. Examples: per-session summary, search-ready snippet index, timeline windowed views.

**Projection state**
:  Per-session bookkeeping for the projection pipeline: source watermark (how far through transcripts have we ingested), dirty bit (does this session need re-projection), last projected session_seq, projection version, last error.

**Watermark**
:  The position in the source transcript stream the projector has consumed up to. Persisted per session; resumes from there on restart.

**Window**
:  A contiguous range of blocks within a session, defined by `(session_id, start_session_seq, count)` or `(session_id, anchor_session_seq, before, after)`. The primary read shape for the frontend timeline.

**Delta**
:  The set of new blocks since a given cursor. Consumed by live UI adapters as the session progresses.

**Summary** (first-class)
:  A short human-readable description of a session, stored on the session-level projection row. Computed during ingestion or by a separate summarization pass.

**History search snippet**
:  A query-centered excerpt of session text, returned by `telec history search`. Multiple snippets per matching session, each centered on a query hit. NOT a collapsed field.

**Subagent transcript**
:  A transcript produced by a subagent (a Task-tool invocation from within a parent session). Excluded from the ledger entirely; never ingested, never searched.

### Aggregates

#### Session (aggregate, historical record)

- **Root:** `SessionRecord`
- **Contains:** `session_id` (matches agent_runtime's session_id); `teleclaude_session_id` and `native_session_id` (both explicit); `agent` (which agent CLI); `started_at`, `updated_at`; `summary` (first-class, stored); `human_email` (admin-only at render time); the ordered Block collection (referenced, not contained — blocks are stored separately).
- **Invariants:**
  - `session_id` is shared with agent_runtime; the ledger never invents session ids.
  - `session_seq` within a session is dense (no gaps) and monotonic.
  - `started_at` is set when the first block is appended; never mutated.
  - `updated_at` is set on every block append and projection update.
  - Subagent transcripts are excluded; an attempted ingestion of a subagent session is silently dropped.
  - Identity fields are explicit: `teleclaude_session_id` and `native_session_id` are separate columns, never collapsed.
- **Identifier:** `session_id` (UUID).
- **Lifecycle:** Created when the first block is appended (on session start). Mutated by block append + projection update. Never deleted in normal operation; archival happens via separate retention policy if introduced.

#### Block (aggregate)

- **Root:** `Block`
- **Contains:** `session_id`, `session_seq`, `kind`, `content` (TEXT, possibly TOASTed for large payloads), `occurred_at` (UTC), `source_ordering_metadata` (deterministic ordering from transcript chain/file/entry/block order).
- **Invariants:**
  - Blocks are immutable once appended.
  - `(session_id, session_seq)` is unique.
  - Block ordering follows source transcript order deterministically — the database never invents semantic ordering.
  - Block kind is fixed at creation; mutations are forbidden (corrections happen via compensating append-only blocks if ever needed).
  - Control/lifecycle events are NOT blocks unless explicitly promoted (real-time only by default).
- **Identifier:** `(session_id, session_seq)`.
- **Lifecycle:** Appended by the projector during ingestion. Never updated. Removed only if the parent session is archived (rare).

#### Projection State (aggregate)

- **Root:** `ProjectionState` (one per session)
- **Contains:** `session_id`, `source_watermark`, `dirty_at` (nullable), `last_projected_session_seq`, `projection_version`, `last_error` (nullable), `error_at` (nullable), timestamps.
- **Invariants:**
  - Exactly one projection state row per session.
  - `dirty_at` is set when source changes detected; cleared when projection completes.
  - `projection_version` allows the schema to evolve; old-version sessions get reprojected as the version bumps.
  - `last_error` populated when projection fails; the projector retries via standard backoff.
- **Identifier:** `session_id`.
- **Lifecycle:** Created with the SessionRecord on first block append. Mutated by every projection pass.

### Domain events emitted

#### `session_ledger.block.appended`

- **Producer:** `session_ledger`
- **Emitted when:** a new block is persisted (during projection from raw transcript).
- **Payload:** `session_id`, `session_seq`, `kind`, `occurred_at`, `appended_at`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (live timeline append), UI adapters (delta consumers), search-index refresh.
- **Idempotency key:** `(session_id, session_seq)`.
- **Posture:** `commit-then-emit`.

#### `session_ledger.projection.updated`

- **Producer:** `session_ledger`
- **Emitted when:** the projection state advances (watermark moves, summary regenerated, snippet index refreshed).
- **Payload:** `session_id`, `from_seq`, `to_seq`, `projection_version`, `updated_at`.
- **Visibility:** CLUSTER
- **Known consumers:** `frontend` (refresh session-level metadata), search consumers.
- **Idempotency key:** `(session_id, to_seq)`.
- **Posture:** `commit-then-emit`.

### Domain events consumed

#### `agent_runtime.session.started`

- **Producer:** `agent_runtime`
- **Reaction:** open transcript ingestion for the new session_id. Create a SessionRecord stub (or wait for first block append, depending on implementation choice).
- **Failure handling:** if the ledger is unavailable, the session continues live (agent_runtime doesn't block); ingestion catches up on recovery.

#### `agent_runtime.session.updated`

- **Producer:** `agent_runtime`
- **Reaction:** mark the session dirty (set `dirty_at` on projection state); the dirty-set coalescer picks it up.
- **Failure handling:** dirty-marking is best-effort; the periodic reconciliation pass catches missed marks.

#### `agent_runtime.session.ended`

- **Producer:** `agent_runtime`
- **Reaction:** close transcript ingestion for the session. Final projection pass. Set `ended_at`.
- **Failure handling:** retried; the ledger eventually closes the record even if the live notification was lost.

### Use cases

#### UC-LDG-1: Web timeline windowed read

```
Given a frontend timeline view is rendered for a session
And the view has a locally persisted anchor session_seq
When the frontend calls session_ledger.window(session_id, anchor, before=N, after=M)
Then the ledger returns the N blocks before the anchor and the M blocks after, in session_seq order
And the response includes the next_cursor session_seq for pagination
```

#### UC-LDG-2: UI adapter delta consumer

```
Given a UI adapter is subscribed to a live session's history
And has a durable cursor at last_seen_session_seq
When new blocks are appended (session_ledger.block.appended events arrive)
Then the adapter pulls blocks (session_seq > cursor) from the ledger
And processes them in order
And advances its cursor durably
And replays don't duplicate (cursor is monotonic; advance is idempotent)
```

#### UC-LDG-3: History search returns per-session blocks

```
Given an operator runs `telec history search "<query>"`
When session_ledger executes the search
Then it returns one session block per matching session, NOT a collapsed table
Each block carries: Started, Last Active, Agent, TeleClaude Session ID, Native Session ID, [Human Email + Human Role if admin caller], Summary, multiple query-centered Context snippets
And subagent sessions are absent from the results
And summary is first-class (already stored on the projection)
And context snippets are computed at search time
```

#### UC-LDG-4: Live session searchable after completed turn

```
Given a live session reaches the end of a turn (the agent's response completes)
When the projector picks up the dirty session within the next coalesce window (~1s debounce)
Then the new blocks land in the ledger
And the search index refreshes for that session
And the next history search query can find the new content
```

#### UC-LDG-5: Visibility policy applied at read time

```
Given a session has thinking blocks and tool result blocks
When a caller requests window/delta with default visibility (include thinking: false, include tool_result: false)
Then those blocks are filtered out at read time
And the response contains only user_text + assistant_text + tool_use + compaction by default
And explicit opt-in (--thinking, --include-tool-results) returns them
```

#### UC-LDG-6: Restart resilience via watermark

```
Given the projector process restarts mid-ingestion
When the projector comes back up
Then it reads the watermark per session from projection_state
And resumes ingestion from the watermark
And no blocks are duplicated (deterministic ordering + (session_id, session_seq) uniqueness)
And no blocks are missed (the watermark only advances after the block is committed)
```

#### UC-LDG-7: Bad mirror row migration

```
Given existing mirror rows from v1 include subagent transcripts or wrongly-extracted identifiers
When the v1 → v2 migration runs (telec migrate-ledger-v1)
Then the migrator filters subagent sessions out
And corrects identifier extraction (especially Codex native session IDs)
And inserts valid records into the v2 ledger with deterministic ordering preserved
And the v1 mirrors.db is archived (renamed mirrors.db.v1-archive) for safety, not deleted
```

#### UC-LDG-8: Codex native session ID extraction correctness

```
Given Codex sessions have a different native session ID format than Claude
When ingestion processes a Codex transcript
Then the native_session_id column gets the correct Codex-format identifier
And the test suite covers Codex-specific extraction paths
And v1 bad rows (where Codex IDs were misextracted) are corrected by the migration
```

#### UC-LDG-9: Schema version migration

```
Given the projection schema bumps from version 1 to version 2
When the projector processes a session whose projection_version is 1
Then the projector reprojects from scratch (or from the affected blocks)
And updates projection_version to 2 on completion
And subsequent reads see the v2 projection
```

### Context map position

- **Partnership with `agent_runtime`** — these two contexts evolve together as the session story. Shared session_id namespace. Tight coordination on session lifecycle events. Ledger is downstream of runtime for live signals.
- **Customer-Supplier downstream of `identity`** — `human_email` and `human_role` admin-only rendering depend on identity resolution.
- **Customer-Supplier downstream of `config`** — projection cadence, retention policies (if added), read defaults.
- **Customer-Supplier upstream to `frontend`** (and `telec history` CLI surface) — these are read consumers.
- **Customer-Supplier upstream to UI adapters** — delta consumers via cursor.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/mirrors/` (~900 lines) + `teleclaude/history/` modules. The v2 ACL preserves the public CLI surface (`telec history list/search/show`) during the parallel-capable phase; v1 mirrors writer disables in coordination with `v2-agent-runtime` ceding the exclusive-writer role. Disappears at `v2-session-ledger-cutover`.

## Allowed values

- `block kind`: `user_text`, `assistant_text`, `thinking`, `tool_use`, `tool_result`, `compaction`.
- `projection_version`: starts at 1; monotonic.

## Known caveats

- **The ledger is the system of record for SESSION HISTORY only.** Live state lives in `agent_runtime`. Workflow state lives in `workflow`. The ledger doesn't try to be a general event log; it's session-specific.
- **Subagent transcripts are EXCLUDED entirely.** Per the history-search inheritance: no subagent runs in results, ever. They're filtered at ingestion.
- **Control/lifecycle events are real-time only by default.** They don't become blocks unless explicitly promoted (e.g., a future decision to make `session.started` a visible system block).
- **`human_email` rendering is admin-only.** Stored on the projection row; gated at render time based on caller's principal role. Never leaks to non-admin output.
- **Identity prerequisites must be solid before search trust.** History search's `Human Email` field is only useful if identity resolution is correct upstream (`edge-session-creation`, `identity-origin-cleanup-final` from the inherited requirements).
- **Default recall is conversation-first.** History search returns user/assistant text by default. Tool usage/results available via explicit flag for agent use cases.
- **Postgres TOAST handles large block payloads.** Block content can be large (long tool outputs, big code blobs). TOAST is transparent; queries don't change.
- **The dirty-set coalescer uses ~1s debounce.** Multiple updates to the same session within a 1-second window are coalesced into one projection pass. Lower latency than processing each individually; higher than 0 because the projector batches.
- **Ledger writer is the EXCLUSIVE writer in v2.** During the cutover window, v1 mirrors writer must be disabled BEFORE the v2 writer activates, or the double-write window creates inconsistency. See `v2-session-ledger-cutover` for the protocol.
