---
visibility: public
number: 0054
date: 2026-06-20
description: v1 (Python) is the canonical running system; the v2 Rust rewrite is retired as a destination, and capabilities conceived under v2 that are genuinely needed are built in v1.
---

# v1 Is the System; the v2 Rewrite Is Retired as a Destination — ADR

## Context

The platform carried a parallel rewrite: the running v1 (Python daemon, SQLite,
the event pipeline, the adapters) was being reimplemented as v2 (Rust crates, a
Rust daemon, Postgres). The rewrite started, partially landed, and never
converged.

Two forces made the split untenable:

- **The v2 parts do not function.** The Rust work — the webhook ingress, the
  integration crate, the hooks service — does not run in production, even where
  internal status records report it complete. The running system is v1, end to end.
- **The documentation drifted toward the v2 target.** Domain specs increasingly
  described the v2 Rust contract as if it were the live contract. New work read
  those specs, built toward an unbuilt
  destination, and repeatedly stalled on the v1/v2 fault line (live state in v1,
  an attempted boundary in v2, bridged buses between them). Status fields and
  specs described a system that does not exist.

The standing cost was a per-feature rewrite tax: every new capability had to be
built in the system being abandoned or blocked on the system not finished, and
the docs could not be trusted as a description of reality.

## Decision

v1 (Python) is the canonical running system and the home for all functionality.

- The v2 Rust rewrite is **retired as a destination**. The Rust crates and Rust
  daemon are not the target, not maintained as the contract, and not built toward
  for new work.
- A capability is "the system" when it runs in v1, regardless of whether it was
  first conceived under v2. Net-new capabilities that are genuinely needed — the
  redis cluster event bus, single-ingress webhook termination — are realized in
  v1 Python.
- Documentation describes v1 reality. The v2 architecture vision is preserved as
  an explicitly frozen, aspirational reference only; it is never the contract that
  governs current or new work.

## Consequences

- Documentation re-anchors to what runs: specs describe the live v1 contract, and
  the class of drift where docs describe an unbuilt destination is eliminated at
  the source.
- New work unblocks: there is one system to build in, with no fault line to land
  on per feature.
- Trust in status is restored only after re-baselining — the retired Rust work is
  not functional regardless of how its internal status records read, and those
  records must be corrected rather than believed.
- The investment in the Rust crates is shelved (sunk cost), and any v2 design
  worth keeping must be re-realized in v1 — the webhook ingress and any other
  needed boundary are rebuilt in Python, not inherited.
- v1's known weaknesses do not get "fixed by the rewrite" — they remain in v1 and
  must be addressed there directly.
- The frozen v2 architecture docs must be marked unambiguously as aspirational, or
  agents will build toward them again.

## Alternatives Considered

- **Finish the v2 cutover** — freeze v1 feature work and complete the Rust rewrite.
  Rejected: the rewrite was far behind with no convergence in sight, there is no
  performance or correctness forcing function that requires Rust, and for an
  operation that must keep shipping, a half-finished rewrite is pure liability.
- **Keep the dual-platform status quo** — continue maintaining both. Rejected: the
  coexistence is the active source of the drift, the per-feature flailing, and the
  status fields that misreport reality. It costs every feature twice and erodes
  trust in the docs.

## Status

Superseded by ADR-0068
