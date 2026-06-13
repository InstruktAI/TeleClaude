---
date: '2026-06-11'
description: 'New cross-node behavior is gated behind spec-like feature-IDs that unaware nodes safely ignore — the explicit, named form of the expand step. Each feature-ID is marked ignorable or must-negotiate, nodes advertise their capability set into a fleet capability map, and an ID is retired (with its gated code path) only once the slowest channel universally carries it. Feature-IDs gate new capabilities; they do not replace envelope versioning for evolving shared shapes.'
number: '27'
visibility: 'public'
---

# ADR-0027: Feature-ID Capability Gating — ADR

## Context

ADR-0026 establishes expand/contract gated on the slowest channel as the discipline for cross-version change. "Expand" needs a concrete mechanism a fleet of mixed versions can execute without central coordination. The platform previously had a crude `experiments.yaml` feature-toggle setup; the question is whether a feature-flag mechanism — features with stable IDs, like doc snippets have IDs, that nodes unaware of them simply bypass — is the right tool.

It is the right tool for exactly one of the two cross-version change kinds, and a category error for the other:

- **New capability** — a new event type, a new optional behavior, a new coordination step a node has never heard of. The safe default is to ignore it. Feature-IDs nail this.
- **Evolved shape** — a field changes on an event a node _already_ consumes. A feature-ID does nothing here; the node knows the event and must still process it, just resiliently. This is the envelope-versioning + tolerant-reader + upcaster lane (ADR-0026).

Used for shape evolution, feature-flags explode into a flag-per-field-change and never make the reader tolerant. Used for new capability, they are the cleanest expression of graceful degradation.

## Decision

Adopt **feature-IDs** as the capability-gating layer, sitting beside (not replacing) ADR-0026's envelope versioning.

- **A feature-ID is the named "expand" step.** Expand = ship the new behavior behind a feature-ID that unaware nodes ignore. Contract = retire the ID and delete the gated code path once the slowest channel universally carries it.
- **Graceful-ignore is the default.** An event or behavior tagged with feature-ID `F` is dropped cleanly by a node that does not carry `F` — fail-safe ignore, never fail-crash. The event-bus enforces this default.
- **Ignorable vs must-negotiate.** Each feature-ID is marked. _Ignorable_ features (most product behavior) are safe to bypass when unaware. _Must-negotiate_ features (fleet-coordination changes — a new lease format, a new dedup key) are NOT safe to bypass: an unaware node that ignores them silently does the old, unsafe thing, producing split-brain. Must-negotiate features refuse rather than degrade until the peer advertises support.
- **Fleet-advertised capability map.** Each node advertises its feature-ID set; `reconciliation` aggregates these into the fleet capability map (ADR-0024). The map is the authoritative input to "is it safe to require, or to contract, feature `F`?" — a more precise check than a SemVer compare, since a node may run a newer version with a feature disabled.
- **Lifecycle removal is mandatory.** A feature-ID is retired the moment the capability map shows the slowest channel universally carries it; retirement deletes the gated path. Feature-IDs that never die are themselves backward-compat cruft relocated from code branches into a registry — the exact debt the platform bans (ADR-0025). The removal gate is what keeps the registry honest.
- **Spec-like identity.** Feature-IDs are stable identifiers like doc-snippet IDs, giving a through-line: feature-ID → feature spec → the events it introduces → the version range it is live in.

## Consequences

**Positive:**

- Expand/contract becomes concrete and queryable: "do all live nodes advertise `F`?" replaces human version reasoning.
- New capabilities ship safely into a mixed-version fleet with graceful-ignore as the default failure mode.
- Combined with additive-only-within-a-major and tolerant readers, feature-IDs absorb the new-capability cases so wire upcasters are needed only for genuine non-additive shape changes — keeping the cheap path cheap.

**Negative:**

- A capability map and an advertisement protocol must exist; until they do, feature-IDs degrade to local ignore-if-unknown tags (still useful, but "safe to contract" cannot be answered).
- The ignorable/must-negotiate distinction must be modeled and respected; mislabeling a coordination change as ignorable reintroduces split-brain risk.
- Discipline burden: every feature-ID needs an owner accountable for its retirement, or the registry rots.

## Alternatives Considered

**Feature-flags for all cross-version change, including shape evolution.** Rejected: a flag per field change explodes combinatorially and never makes the reader tolerant. Shape evolution belongs to envelope versioning + upcasters (ADR-0026).

**No feature-IDs; rely on envelope versioning alone.** Rejected: versioning handles decoding an event you know, but a brand-new event type or behavior still needs a safe default for nodes that have never heard of it. Graceful-ignore at feature granularity is that default.

**Revive `experiments.yaml` as-is.** Rejected: local on/off toggles with no fleet advertisement and no removal gate. The new mechanism adds capability advertisement, the ignorable/must-negotiate axis, and lifecycle-gated removal.
