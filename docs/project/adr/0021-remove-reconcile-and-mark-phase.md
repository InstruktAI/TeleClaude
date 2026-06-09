---
id: 'project/adr/0021-remove-reconcile-and-mark-phase'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '21'
date: '2026-06-09'
adr_status: 'accepted'
description: 'Removed the telec todo reconcile and mark-phase commands and the mechanical-invalidation subsystem; lifecycle_phase derives from evidence on dispatch, and drift materiality stays an intelligence judgment.'
---

# ADR-0021: Remove reconcile and mark-phase — ADR

## Context

`telec todo reconcile` and `telec todo mark-phase` were operator surfaces for
realigning or overriding a Todo's `lifecycle_phase`. They originated as fail-safes
from an era when agents left Todo state inconsistent and needed a manual way to
correct it.

That era is past. `lifecycle_phase` is now derived from evidence — artifacts,
review verdicts, approval stamps, skip stamps, drift-review stamps — by the
workflow engine (`adopt_prepare_handoff_phase`, `apply_authoritative_signal`),
re-derived on every prepare/work dispatch. Manual realignment is therefore
redundant: the next dispatch already re-derives the pointer.

Two further facts forced the decision:

- `reconcile` was defective on its only live surface. The TUI `r` action sent no
  `--stage`, so the core inferred the stage from the (possibly wrong) current
  pointer and clamped to it — it could not cross stage boundaries — and the TUI
  reported success even when nothing changed. The flag itself contradicted the
  operation's premise: you reconcile *because* you do not know the correct state,
  so requiring the caller to assert the stage up front is incoherent.
- `mark-phase` had no API route, no internal caller, and no-op validation. Its
  only behavioral effect was the mechanical clearing of human approvals on
  artifact refinement — a value judgment that belongs to intelligence
  (`general/principle/intelligence-boundaries`), not to code that fires on any
  edit.

A separate question — whether state correctness should be guaranteed atomically
at mutation time rather than re-derived on the next dispatch — was considered and
declined for v1: no consumer routes on objective drift between dispatches, and the
workflow layer is slated for a v2 rewrite. The correctness-by-construction
invariant is recorded as a v2 design requirement instead of retrofitted into v1
plumbing.

ADR-0001 (git-stash-prevention, 2026-03-20) lists a "mark-phase auto-commit"
measure among its stash-prevention decisions; that description predates the
`state.yaml` → `todos.db` migration and is historical. This ADR does not modify
ADR-0001: ADR-0001 remains an accurate record of what was decided then, and its
stash-prevention decisions (test isolation, autostash prevention, the permission
tiers) are unaffected by this removal.

## Decision

Remove both commands and the dead subsystem behind them, on every surface:

- Delete `telec todo reconcile` from the Python CLI, the HTTP API
  (`/reconcile/{slug}`), its auth clearance, the TUI (`r` binding +
  `action_reconcile`), and the core (`reconcile_phase_state`,
  `reconcile_lifecycle_phase`, the stage inference and `LifecycleStage` enum).
  Re-point the one internal caller (`prepare.py`) at `adopt_prepare_handoff_phase`
  directly.
- Delete `telec todo mark-phase` from the CLI and the core
  (`mark_phase_state`, the no-op validators), together with the
  mechanical-invalidation subsystem it alone reached: `normalize_mark_phase`,
  `_clear_prepare_target`, `invalidate_downstream_on_refine`. Delete the dead
  `notify_phase_transition` (zero callers).
- Delete the corresponding Rust `telec-cli` command variants and dispatch arms,
  and regenerate the public CLI manifest.

`lifecycle_phase` continues to be derived from evidence on dispatch (unchanged).
Drift between artifacts is detected objectively (`derive_lifecycle_drift`) and its
materiality is judged only by the intelligence-stamped `substantive` drift-review
cascade; no command and no write clears a human approval as a mechanical side
effect.

## Consequences

**Positive:**

- The original `fix-reconcile-in-tui` defect is resolved by removing the broken
  surface rather than patching it.
- The mechanical-approval-clearing footgun is gone; approval invalidation is
  exclusively an intelligence judgment.
- A smaller, honest operator/agent surface: no command can set the pointer against
  its evidence.

**Negative / costs:**

- Correcting a Todo's pointer after an out-of-band artifact edit now happens at the
  next `telec todo prepare`/`work` dispatch rather than via a dedicated command.
  This is acceptable because disciplined flows always advance after mutating, and
  the dispatch re-derives across stages without `reconcile`'s stage-clamp defect.
- There is no longer an operator escape hatch to force a pointer against evidence.
  This is intentional: the prior escape hatch's only real effect was unsafe.

**Deferred:**

- Atomic, correct-by-construction `lifecycle_phase` derivation within the mutation
  transaction is recorded as a v2 workflow-service design requirement, not built in
  v1.
