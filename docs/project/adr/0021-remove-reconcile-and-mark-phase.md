---
date: '2026-06-09'
description: 'Removed the telec todo reconcile and mark-phase commands and the mechanical-invalidation subsystem; lifecycle_phase derives from evidence on dispatch, and drift materiality stays an intelligence judgment.'
number: '21'
visibility: 'public'
---

# ADR-0021: Remove reconcile and mark-phase — ADR

## Context

`telec todo reconcile` and `telec todo mark-phase` were operator surfaces for realigning or overriding a todo's `lifecycle_phase`, fail-safes from an era when agents left todo state inconsistent. That era is past: `lifecycle_phase` is now derived from evidence (artifacts, review verdicts, approval/skip/drift stamps) on every dispatch, so manual realignment is redundant — the next dispatch re-derives the pointer.

Both surfaces were also defective. `reconcile` required the caller to assert the stage up front, which contradicts its own premise (you reconcile _because_ you do not know the correct state) and could not cross stage boundaries; `mark-phase` had no real caller and its only effect was mechanically clearing human approvals on artifact edits — a value judgment that belongs to intelligence, not to code firing on any edit.

## Decision

Remove both commands and the dead mechanical-invalidation subsystem behind them, across every surface (CLI, HTTP API, TUI, core, and the Rust CLI), re-pointing the one internal caller at the evidence-derivation path directly.

`lifecycle_phase` continues to be derived from evidence on dispatch (unchanged). Drift between artifacts is detected objectively, but its materiality is judged only by the intelligence-stamped drift-review cascade; no command and no write clears a human approval as a mechanical side effect.

## Consequences

- The broken reconcile surface is resolved by removing it rather than patching it, and the mechanical-approval-clearing footgun is gone — approval invalidation is exclusively an intelligence judgment.
- A smaller, honest surface: no command can set the pointer against its evidence.
- Cost: correcting a pointer after an out-of-band artifact edit now happens at the next dispatch rather than via a dedicated command — acceptable, since disciplined flows always advance after mutating, and there is intentionally no escape hatch to force a pointer against evidence.
- Atomic, correct-by-construction phase derivation within the mutation transaction is recorded as a v2 workflow-service design requirement, not built in v1.
