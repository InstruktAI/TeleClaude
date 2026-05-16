---
description: 'Migration order for v2: MVP first (workflow + CLI), then per-service alpha with narrow freezes. Parallel to v1, in same repo.'
id: 'project/design/architecture-v2/reconstruction-order'
scope: 'project'
type: 'design'
---

# Reconstruction Order — Design

## Required reads

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/file-layout.md

## Purpose

Define the order and shape of the v2 migration. v2 lives at `crates/`
alongside v1 (`teleclaude/`) and grows in-place. Migration is dedicated work
(not smeared across features), proceeds service-by-service after an MVP
proves the pattern, and uses narrow per-service freezes that never globally
block feature work.

## Inputs/Outputs

**Inputs:**

- the v2 target architecture (services as crates, Postgres-only, single Redis
  transport, observability, identity)
- the existing v1 codebase that must keep shipping during migration
- the principle (named with Maurice mid-discussion): migration is its own
  dedicated workstream, not a side effect of feature work
- AI-scale execution time (hours-to-days per service, not weeks-to-months)

**Outputs:**

- the wave structure (MVP first, spine next, services after)
- the per-service alpha + narrow freeze pattern
- the parallelism the dependency graph allows
- the feature/bug discipline during migration

## Invariants

- **Migration is a dedicated workstream.** Each migration is its own todo
  with PRD, architecture, plan, build, review, finalize. Not a side effect
  of feature work.
- **No global freeze.** Per-service migrations have a narrow freeze on that
  service's domain during the lift. Features in other domains continue.
- **Build alongside v1, cut over per service.** v2 services land in
  `crates/`; v1 keeps running. Each cutover is a focused PR with one-shot
  data migration from v1 storage to v2 Postgres.
- **No dual-write.** During transition, each service has one authoritative
  storage: v1 SQLite or v2 Postgres, never both simultaneously.
- **MVP proves the pattern.** Before any other service migrates, MVP must
  ship a working workflow service + Rust CLI end-to-end. The MVP reveals
  what the per-service alpha workflow actually takes.
- **Per-service alpha is small.** Each is hours-to-days of focused AI
  execution, not weeks. If a single service migration is taking longer,
  the scope is wrong — split it or simplify.

## Primary flows

### Phase 0 — Lock the architecture (done when these docs are stable)

**Deliverables:**

- this docset complete: overview, services, file-layout, transport-rules,
  auth-model, observability-model, event-bus-transports, redesign-list,
  reconstruction-order
- Rust testing policy at `software-development/policy/rust/testing.md`
- Rust core policy at `software-development/policy/rust/core.md`

**Why first:** Every subsequent wave references these. Without them, agent
sessions doing migration work re-derive architecture from priors and drift.

### Wave 1 — MVP (workflow + CLI + identity stub + observability + Postgres)

**Goal:** Prove the v2 pattern end-to-end with the most-touched service.

**Scope:**

1. Rust workspace bootstrap at `crates/` (Cargo.toml workspace, member
   list, shared deps).
2. `crates/shared/` — primitive types (`Slug`, `ProjectId`, time helpers).
3. `crates/observability/` — `tracing` wrapper emitting
   `instrukt_ai_logging` format to `/var/log/instrukt-ai/teleclaude/`.
4. `crates/storage/` — `sqlx::PgPool` helpers, migration runner.
5. `crates/event_bus/` — Redis Streams + pub/sub wrapper.
6. `crates/identity/` — single-user stub (returns `Principal::Human` from
   env, full implementation deferred).
7. `crates/workflow/` — full functional implementation:
   - Postgres `workflow` schema with migrations
   - Public API: list/create/get/update todos, roadmap, artifacts
   - State machine (lifecycle phases) for the workflow domain
   - Event emission on every mutation
8. `crates/telec/` — CLI binary:
   - `telec todo list/show/create/update`
   - `telec roadmap list/add/move/remove`
   - Embeds workflow + identity + observability
9. Postgres setup: `docker-compose.yml`, `make pg-up`/`make pg-down`.
10. Data migration tool: read v1 SQLite `todos.db` → write to v2 Postgres
    `workflow` schema. Run once.
11. Cutover: `telec todo` and `telec roadmap` route to v2 binary; v1 todo
    code paths deprecated.

**Result:** v1 TUI still works, sessions still work, Telegram still works.
Only workflow has moved. New todos created via Rust CLI; v1 TUI shows
post-migration state via its existing read paths (until TUI rewrites).

**Time:** Days, not weeks. Single focused work item.

### Wave 2 — Spine completion (identity, config, observability hardening)

**Goal:** Complete the spine pieces that the MVP stubbed.

**Scope:**

1. `crates/identity/` — full implementation:
   - Postgres `identity` schema
   - Real principal resolution (env, TTY login, HTTP headers, session tokens)
   - Token issuance/validation/revocation
2. `crates/config/` — config service:
   - Read overlays from `teleclaude.yml` / `config.yml` / per-person configs
   - Validation
   - Effective-config computation
3. `crates/observability/` — refinements based on MVP experience (any
   missing tracing patterns, log format gaps).

**Result:** Identity and config are fully v2. Other services that need them
(when they migrate) have real implementations to depend on.

**Time:** Days. Each is a focused service migration.

### Wave 3 — Knowledge (docs/snippets)

**Goal:** Migrate `telec docs index` / `telec docs get` to a Rust service.

**Scope:**

1. `crates/knowledge/`:
   - Postgres `knowledge` schema (snippet index, taxonomy)
   - Ingestion from `docs/` filesystem
   - Selection policy engine
2. CLI: `telec docs` subcommands route to knowledge service.
3. v1 docs index paths deprecated.

**Result:** Knowledge fully v2. `telec docs` is the v2 CLI binary's command.

**Time:** Days.

### Wave 4 — Agent runtime (the big one)

**Goal:** Migrate session lifecycle, tmux orchestration, agent CLI
supervision. Narrow v1 daemon to its remaining responsibilities.

**Scope:**

1. `crates/agent_runtime/`:
   - Postgres `agent_runtime` schema (sessions, operations, availability)
   - Tmux orchestration (replaces `teleclaude/core/tmux_bridge/`)
   - Agent CLI process supervision (spawning, monitoring, terminating
     the running Claude / Codex / Gemini processes)
   - Live I/O streaming
   - Event emission on session lifecycle
   - Subscription to `integration.inbox.agent_hook_*` events (emitted by
     integration when subprocess hooks fire) to react to lifecycle signals
2. `crates/telec-daemon/` — Rust daemon binary that hosts agent_runtime,
   spawns workers, runs WebSocket bridge.
3. v1 daemon shrinks dramatically — most of it dies.
4. Data migration: v1 `teleclaude.db` sessions → v2 Postgres.

**Not in this wave:** the `telec-hook` subprocess binary and hook payload
parsing/normalization. Those belong to `integration` (Wave 6) per the
change-axis heuristic — hook receiver code changes when external CLI
protocols change, which is integration's domain. agent_runtime is the
SUBSCRIBER to hook events, not the receiver. Until Wave 6, the v1 Python
hook receiver keeps running and publishes to Redis; v2 agent_runtime
subscribes from there.

**Result:** Daemon restart time drops dramatically (Wave 4 is the moment
"daemon restart pain" stops). Sessions managed by v2.

**Time:** Days (longest single migration; still bounded).

### Wave 5 — Session ledger

**Goal:** Replace mirrors with the canonical ledger service.

**Scope:**

1. `crates/session_ledger/`:
   - Postgres `session_ledger` schema
   - Transcript ingestion
   - Read API for history
2. `telec history` routes to ledger service.
3. v1 mirrors deprecated.

### Wave 6 — Integration & events (ALL inbound)

**Goal:** Migrate ALL inbound-from-external concerns: HTTP webhooks,
subprocess hook receivers, outbox/inbox, worker supervision.

**Scope:**

1. `crates/integration/`:
   - Postgres `integration` schema (outbox, inbox, dlq, worker_state)
   - HTTP webhook receivers (Telegram, Discord, WhatsApp)
   - Subprocess hook receivers (Claude Code, Codex, Gemini hooks):
     payload parsing, validation, normalization, event emission
   - Outbound delivery workers for at-least-once external delivery
2. `crates/telec-hook/` — small Rust binary, integration's subprocess
   entry point. Reads stdin JSON, calls `integration::ingest_agent_hook()`,
   exits. Registered with Claude Code / Codex / Gemini agent configs
   (replacing the v1 Python hook receiver).
3. Worker binaries spawned by `telec-daemon`.
4. v1 webhook/adapter code AND v1 Python hook receiver deprecated.
5. Agent CLI configs (`~/.claude/settings.json`, etc.) updated to
   reference `telec-hook` instead of the v1 Python receiver path.

**Why hooks and webhooks together:** both are inbound-from-external
following the same shape (receive payload → normalize → emit event).
Same change axis (external system protocol changes). Same Postgres
inbox/dlq machinery. Splitting by transport (HTTP vs subprocess) would
duplicate code for no gain. See `transport-rules.md` placement heuristic.

### Wave 7 — Agent artifacts

**Goal:** Move `agents/` source distribution into a Rust service.

**Scope:**

1. `crates/agent_artifacts/`:
   - Source manifest reading from `agents/`
   - Inflation (master → output)
   - Distribution to deployed runtime dirs
2. `telec sync` routes to artifacts service.
3. v1 distribution code deprecated.

### Wave 8 — HTTP API for browser

**Goal:** Replace v1 daemon's HTTP API with a Rust API binary.

**Scope:**

1. `crates/telec-api/`:
   - HTTP server (axum or similar)
   - Thin routes calling into service crates
   - OpenAPI contract for the browser
2. Frontend custom server bridges to telec-api instead of v1 daemon.
3. v1 daemon's HTTP API endpoints deprecated.

### Wave 9 — TUI rewrite

**Goal:** Rust TUI replacing the Python Textual TUI.

**Scope:**

1. `crates/telec-tui/`:
   - Ratatui app
   - Subscribes to Redis events for live updates
   - Embeds service crates for queries
2. v1 Python TUI deprecated.

**Position in sequence:** This can happen anywhere after Wave 1 (MVP). It's
parallelizable because the TUI consumes services rather than providing them.

### Wave 10 — Legacy purge

**Goal:** Delete `teleclaude/` (Python package) entirely.

**Scope:**

1. Verify no remaining v1 code paths are called.
2. Delete `teleclaude/` directory.
3. Delete v1-specific build/test configuration.
4. Update Makefile to remove v1 targets.

### Dependency graph

```
Phase 0 (architecture docs)
        ↓
Wave 1 (MVP: workflow + CLI + spine basics)
        ↓
Wave 2 (Spine: identity, config full)
        ↓
   ┌────┴────────┬─────────────────────┐
   ↓             ↓                     ↓
Wave 3        Wave 4              Wave 9
(knowledge)   (agent_runtime)     (TUI — anywhere after Wave 1)
              ↓
              Wave 5 (ledger) ↘
              Wave 6 (integration) → Wave 8 (HTTP API)
              ↓
              Wave 7 (agent_artifacts)
                            ↓
                    Wave 10 (legacy purge)
```

Many waves are parallelizable. Wave 1 blocks everything else (the MVP
proves the pattern). After Wave 2, several services can lift in parallel
because they don't depend on each other for code.

### Feature/bug discipline during migration

A service is in one of three states at any time:

1. **v1-only** — code lives in `teleclaude/`, storage in SQLite.
2. **Migrating** — active lift in progress, narrow freeze on the
   service's domain.
3. **v2-only** — code lives in `crates/`, storage in Postgres, v1
   counterpart deleted.

**Rules:**

- **New feature in a v1-only service** — lands in v1. Will be carried
  along when that service migrates.
- **New feature in a v2-only service** — lands in v2.
- **New feature in a migrating service** — pause until migration alpha
  lands. Per-service freeze.
- **Bug fix in a migrating service** — hot-patch v1 with an explicit
  "subsumed when migration lands" note. Migration PR either reapplies
  the fix in v2 form or makes it obsolete.
- **Bug fix elsewhere** — normal flow.

This is enforced via the discipline snippet read by prepare/build/review
agents. The snippet tracks which services are v1-only vs v2-only vs
migrating; agents check before deciding where to land code.

### Why MVP-first instead of spine-first

The doc's earlier version (when v2 was a TypeScript greenfield rewrite)
recommended spine-first. For the Rust in-place migration, MVP-first is
better because:

1. **The workflow service is the most-touched domain.** Cache-coherence
   bugs (the one that started this conversation) live there. Migrating
   first proves the v2 pattern resolves real production pain.
2. **The spine that the MVP needs is small.** Identity stub, observability,
   storage helpers, event bus. Not the full spine — just enough.
3. **The full spine completes as Wave 2** once the MVP has surfaced what's
   actually needed.
4. **AI scale supports this.** With Python's slower iteration, spine-first
   was safer. With Rust + AI agents, the MVP-and-iterate loop is faster
   and surfaces real requirements that pure design would miss.

### What changed from the prior version of this doc

The earlier version of this doc described a TypeScript greenfield rewrite
in a separate codebase. That strategy was abandoned because side-by-side
migration is required (Maurice's framing: "if we want to keep shipping,
we can't fork the language"). The current doc describes the Rust in-place
migration that actually proceeds.

The prior phases (Postgres-first, identity-first, workflow-second) are
re-ordered into MVP-first because the workflow service is the highest-
leverage migration and Rust's compile-time discipline makes the
iterate-after-MVP-ships strategy lower-risk than it would have been in
Python.

## Failure modes

- **Treating migration as a side effect of features.** Smearing v2 work
  across feature PRs produces hybrid code that's worse than either pure
  version. Migration is its own todos.
- **Global freeze.** Pausing all feature work for "v2 migration." Kills
  velocity. Per-service narrow freezes only.
- **Big-bang Wave 10.** Trying to migrate all services before any cutover.
  Each service cuts over independently as its alpha ships. v1 dies piece
  by piece.
- **Dual-write during a service's transition.** "Workflow in Rust writes
  to both Postgres and v1 SQLite for safety." No. One authoritative store
  at a time. Cutover is atomic per service (one-shot data migration + code
  switch).
- **Cross-service queries spanning v1 and v2.** "v1 daemon reads from v2
  Postgres workflow schema for the TUI." No. Each language reads its own
  side. The TUI shows v1 state until TUI rewrites.
- **MVP scope creep.** Trying to migrate identity + workflow + agent_runtime
  in MVP. Defeats the "prove the pattern small" purpose. MVP is
  workflow + CLI + identity-stub + observability + storage + event_bus,
  full stop.
- **Spine-first re-derivation.** Reading the prior version of this doc
  and recommending "spine first." That strategy was for a TypeScript
  greenfield rewrite that no longer applies. MVP-first is the call for
  this migration.

## See Also

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/file-layout.md
- docs/project/design/architecture-v2/redesign-list.md
- docs/project/design/architecture-v2/journey.md
