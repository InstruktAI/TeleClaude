---
adr_status: 'accepted'
date: '2026-06-11'
description: 'Two distinct migration concerns are separated: per-aggregate data evolution via lazy upcasting (migrate-on-read, write-back) owned by each domain on a shared engine, and installation-level structural convergence owned by reconciliation. There is no central migrations domain; backward-compatibility branches in domain code are forbidden because the upcaster guarantees the domain only ever sees the latest shape.'
number: '25'
visibility: 'public'
---

# ADR-0025: Two-Layer Migration — Lazy Data Upcasting Per Domain, Installation Convergence in Reconciliation — ADR

## Context

The platform forbids backward-compatibility cruft in code ("when removing code, remove it completely; no backward compatibility unless explicitly required"). That rule is unenforceable for _persisted_ data unless something guarantees domain logic never encounters an old shape — otherwise every read path accretes version-branching, which is exactly the cruft the rule bans.

Two different things travel under the word "migration," and conflating them produces a muddled design:

1. **Installation/runtime convergence** — "this host runs 1.2.3; desired is 1.3.0; run the ordered steps to get there." Eager, ordered, run once per host per version, tracked by a global applied-or-not flag (today: `migrations/v<x>/` + `migration_runner.py` + `migration_state.json`).
2. **Per-aggregate data evolution** — "this todo row / this config document was written under schema vN; bring it to the latest shape." Lazy, per-record, idempotent; the record's own version stamp is the only truth, with no global flag.

A separate temptation is to create one "migrations" domain that owns all data evolution. That would reach into every context's storage and violate bounded-context autonomy — `workflow` owns its todo schema, `config` owns its config schema.

## Decision

Adopt **two layers**, owned in two different places, plus a hard rule that ties them to the no-cruft principle.

**Layer 1 — Per-aggregate data evolution via lazy upcasting (owned per domain).** A stored record carries a `schema_version`. On read it is pulled through an ordered upcaster chain vN → vN+1 → … → latest before any domain code sees it; the migrated form is written back (best-effort/async, so a read is never blocked on the persist) so the store converges over time. Domain code only ever knows the latest shape. The mechanism splits into:

- **A shared upcasting engine (kernel, not a domain).** A `versions/`-per-aggregate convention, a declarative transformer for the common cases (rename, add-with-default, coerce), an escape hatch to custom imperative handlers for complex cases, and the read-through/write-back machinery. Lives in shared infrastructure (`shared`/`storage`).
- **The transformations themselves, owned by each bounded context.** `workflow` ships its own `versions/` for the todo aggregate; `config` ships its own for the config document; each _uses_ the shared engine. No context reaches across into another's data.

Semi-structured payloads (`workflow.todos.state_extra` JSONB, config YAML `extra` passthrough, artifact bodies) are the primary upcasting surface; rigid table DDL stays with structural migrations (Layer 2 / sqlx).

**Layer 2 — Installation structural convergence (owned by `reconciliation`).** The eager, ordered, once-per-host release migrations that bring an installation's structural state (DDL, on-disk layout) from one version to the next. This is reconciliation's `version` convergence concern (ADR-0024), distinct from per-record upcasting.

**The hard rule.** Domain code MUST NOT carry backward-compatibility branches for old persisted shapes. The upcaster is what makes deleting old-shape handling safe: the domain is guaranteed the latest shape. A compat branch in domain logic is a defect, not a pragmatic exception.

## Consequences

**Positive:**

- The no-cruft principle becomes enforceable for persisted data: old-shape handling lives only in named, ordered, testable upcasters, never smeared through domain logic.
- Bounded-context autonomy is preserved — each domain owns its own evolution; the engine is shared tooling, not a god-context.
- Two clean mechanisms with different invariants (lazy/per-record vs eager/per-host) stop being conflated.

**Negative — the sharp edges the implementing spec must address:**

- **Reads become writes.** Write-back complicates read replicas, caching, and transaction boundaries; it must be best-effort/async so reads are not blocked on persistence.
- **Cold data never migrates.** Records never read keep their old version forever. An old upcaster therefore cannot be deleted on the assumption "everything is migrated" without a background sweeper that force-migrates cold records. Absent the sweeper, the chain grows unbounded.
- **Per-record version stamping.** Every persisted aggregate needs a `schema_version`; today's `migration_state.json` is installation-level, so this is new per-aggregate metadata.
- **Chain testing.** Each vN→vN+1 step needs golden-fixture tests so composition stays correct as the chain lengthens.

## Alternatives Considered

**One central migrations domain owning all data evolution.** Rejected: reaches into every context's storage, breaking bounded-context autonomy. The engine is shared _tooling_; the transformations belong with their data.

**Eager bulk migration on upgrade for data too.** Rejected: couples data evolution to release windows, requires downtime or long-running batch jobs, and reintroduces the "did the migration run" coordination problem at the data layer. Lazy upcasting converges opportunistically without a migration window.

**Tolerate old shapes in domain code (status quo for LLM-authored code).** Rejected explicitly: this is the backward-compat cruft the platform bans. The whole point of the upcaster is to make that tolerance unnecessary.
