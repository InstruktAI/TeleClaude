---
adr_status: 'proposed'
date: '2026-06-11'
description: 'The ADR-0025 Layer-1 upcasting engine is shaped as a dedicated storage-agnostic transform core (crates/upcasting, serde_json only) plus a Postgres convergence binding in crates/storage; write-back is a non-blocking compare-and-set guarded by schema_version (skip-on-newer), and the engine never names tables — the consuming context implements a persistence trait with its own sqlx.'
number: '31'
visibility: 'public'
---

# ADR-0031: Upcasting Engine Shape — Dedicated Core Crate, CAS Write-Back, Trait-Owned SQL — ADR

## Context

`@docs/project/adr/0025-two-layer-migration-model` decided Layer 1 (per-aggregate lazy
upcasting) and located the shared engine loosely in "shared infrastructure
(`shared`/`storage`)." Realizing it surfaced three mechanism decisions ADR-0025 left open,
each of which a future agent will reasonably ask "why this way?" about. Grounding against the
v2 workspace fixed the answers:

- `crates/config` depends only on `crates/shared` and is **file-based YAML with no Postgres
  schema** — its `extra` passthrough is `#[serde(flatten)]`, not a stored JSONB aggregate. It
  cannot (and must not) depend on `storage`.
- `crates/workflow` depends on `storage` and persists the todo aggregate with a
  `state_extra` JSONB column already present for forward-compat, but **no `schema_version`**
  today.
- `crates/shared` is deliberately tiny (primitive newtypes + time only). `crates/storage`
  owns `sqlx::PgPool` helpers and the DDL migration runner. The v2 file layout already plans
  `crates/state-machine` as a dedicated generic-engine crate among the infrastructure
  crosscuts, establishing that pattern for the workspace.
- The current workspace has no off-request-path persistence helper to reuse:
  `WorkflowService::publish` awaits `self.events.emit(&envelope)` and returns
  `WorkflowError::EventEmitAfterCommit` on failure (`crates/workflow/src/service.rs:153`), so
  it is not a fire-and-forget precedent. A non-blocking write-back must be justified directly
  from the requirement, not borrowed from an existing pattern.

One invariant is non-negotiable and constrains the choice: write-back must **never clobber a
concurrent domain write or a newer record version**. The mechanism is open; the guarantee is
not.

## Decision

**1. Split the engine into a storage-agnostic core and a Postgres binding.**
The transform core lives in a new infrastructure-crosscut crate `crates/upcasting`,
depending only on `serde_json` (+ `thiserror`): the version-chain convention, the declarative
ops (rename / add-with-default / coerce), the `CustomStep` escape-hatch trait, and chain
execution. The Postgres read-through / write-back / sweep binding lives in `crates/storage`
(which already owns `PgPool`) and depends on the core. This is the concrete reading of
ADR-0025's "`shared`/`storage`."

**2. Write-back is a non-blocking, compare-and-set persist.**
The upgraded form is written back from a spawned task (`tokio::spawn`, fire-and-forget,
log-on-failure) so the read never blocks, and the persist is guarded
`… WHERE schema_version = $from_version`. If the row already advanced (concurrent write or a
newer convergence), the CAS matches nothing and the write-back skips — "skip-on-newer." This
honors the no-loss guarantee without locking the read path.

**3. The engine never names tables; the consumer owns its SQL via a trait.**
The consuming bounded context implements a persistence trait (fetch payload+version,
CAS-persist, select-cold-batch) with its own typed `sqlx` queries. The engine owns chain
execution and convergence orchestration only. No dynamic table/column interpolation exists,
so there is no SQL-injection surface and SQL ownership stays inside the owning context.

**4. The kernel ships zero domain transformations and touches no production table.**
The engine, the binding, and the sweep hook stand alone, exercised by tests against a
synthetic fixture aggregate; no production aggregate is wired by them. Wiring a real
aggregate — adding `schema_version` to `workflow.todos` and authoring workflow's `versions/`
— is outside this decision's scope. Config is not a binding consumer; the synchronous core is
reusable on its parsed document without the convergence binding.

## Consequences

**Positive:**

- The core is reusable by any consumer — including the file-based `config` — without pulling
  `sqlx`/`tokio`, and `shared` stays tiny.
- The no-loss guarantee is structural (a conditional `UPDATE`), not a coordination protocol,
  so it holds without locking or serializing the read path.
- SQL stays inside each bounded context; the engine has no schema knowledge to leak or
  mis-target.

**Negative — sharp edges the implementation must hold:**

- **CAS write-back can silently no-op** under contention; convergence of a hot, frequently-
  rewritten record may lag. Acceptable: such records are re-read and re-attempted, and hot
  records are not the retirement bottleneck — cold ones are, which the sweep handles.
- **A new crate is one more workspace member** to register and lint. Justified by the
  reuse/dependency boundary; the planned `state-machine` crate shows the pattern is normal for
  the workspace.
- **The persistence trait pushes boilerplate to each consumer.** Intended: it is the price of
  keeping SQL typed and context-owned rather than centralizing dynamic SQL in the engine.

## Alternatives Considered

- **Put the whole engine in `crates/storage`.** Rejected: `config` (and any future file-based
  consumer) could then never reuse the transform core without taking a Postgres dependency.
- **Put the core in `crates/shared`.** Rejected: `shared` is deliberately primitive-only;
  `serde_json`-driven transform machinery is too heavy for its mandate.
- **Generic engine that takes table/column names and builds SQL.** Rejected: dynamic SQL
  injection surface and a violation of single-schema-ownership — the engine would reach into
  a context's table shape.
- **Locking or transactional write-back to guarantee no-loss.** Rejected: it would block or
  serialize reads, defeating the lazy/non-blocking premise. CAS skip-on-newer gives the same
  no-loss guarantee without contention on the read path.
- **Eager bulk migration instead of lazy upcasting.** Already rejected by ADR-0025; restated
  here only to note the sweep is a retirement hook, not a re-introduction of bulk migration.
