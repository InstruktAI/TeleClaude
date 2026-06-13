---
date: '2026-06-11'
description: 'Two distinct migration concerns are separated: per-aggregate data evolution via lazy upcasting owned by each domain on a shared engine, and installation-level structural convergence owned by reconciliation. There is no central migrations domain; backward-compatibility branches in domain code are forbidden because the upcaster guarantees the domain only ever sees the latest shape.'
number: '25'
visibility: 'public'
---

# ADR-0025: Two-Layer Migration — Lazy Data Upcasting Per Domain, Installation Convergence in Reconciliation — ADR

## Context

The platform forbids backward-compatibility cruft in code. That rule is unenforceable for _persisted_ data unless something guarantees domain logic never encounters an old shape — otherwise every read path accretes version-branching, which is exactly the cruft the rule bans.

Two different things travel under the word "migration," and conflating them produces a muddled design:

1. **Installation/runtime convergence** — bring a host from the version it runs to the desired version: eager, ordered, run once per host per version.
2. **Per-aggregate data evolution** — bring a single stored record written under schema vN to the latest shape: lazy, per-record, idempotent, the record's own version stamp the only truth.

A further temptation is one "migrations" domain owning all data evolution — which would reach into every context's storage and break bounded-context autonomy.

## Decision

Separate the two concerns into **two layers, owned in two places**, plus a hard rule:

- **Layer 1 — per-aggregate data evolution via lazy upcasting, owned per domain.** A record carries a `schema_version`; on read it is upcast to the latest shape before any domain code sees it, and the upgraded form converges back to the store over time. The upcasting _engine_ is a shared kernel — tooling, not a domain; the _transformations_ are owned by each bounded context for its own aggregates, and no context reaches into another's data.
- **Layer 2 — installation structural convergence, owned by reconciliation.** The eager, ordered, once-per-host release migrations of structural state (DDL, on-disk layout), distinct from per-record upcasting.
- **No central migrations domain.** Data evolution belongs with the data; only the engine is shared.
- **Hard rule: domain code carries no backward-compatibility branches for old persisted shapes.** The upcaster guarantees the latest shape, which is what makes deleting old-shape handling safe. A compat branch in domain logic is a defect, not a pragmatic exception.

## Consequences

- The no-cruft principle becomes enforceable for persisted data: old-shape handling lives only in named, ordered upcasters, never smeared through domain logic.
- Bounded-context autonomy is preserved — each domain owns its own evolution; the engine is shared tooling, not a god-context.
- Two mechanisms with different invariants (lazy/per-record vs eager/per-host) stop being conflated.
- The lazy layer carries real implementation cost — write-back semantics, cold-data convergence, per-record version stamping, chain testing — owned by the engine design, not by this decision.

## Alternatives Considered

**One central migrations domain owning all data evolution.** Rejected: reaches into every context's storage, breaking bounded-context autonomy. The engine is shared _tooling_; the transformations belong with their data.

**Eager bulk migration for data too.** Rejected: couples data evolution to release windows, requires downtime or long-running batch jobs, and reintroduces the "did the migration run" coordination problem at the data layer. Lazy upcasting converges opportunistically without a migration window.

**Tolerate old shapes in domain code.** Rejected explicitly: this is the backward-compat cruft the platform bans. The upcaster makes that tolerance unnecessary.

## See Also

- docs/project/design/architecture-v2/data-upcasting.md — the Layer-1 upcasting engine design.
- docs/project/spec/domain/reconciliation.md — owns Layer-2 installation convergence.
