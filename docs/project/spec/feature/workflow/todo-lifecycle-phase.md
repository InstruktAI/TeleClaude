---
id: 'project/spec/feature/workflow/todo-lifecycle-phase'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Canonical lifecycle_phase pointer naming where a Todo stands in its journey, plus the operator override (mark-phase) and the evidence-driven realignment (reconcile).'
---

# Todo Lifecycle Phase — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`lifecycle_phase` is the canonical pointer a Todo carries to name exactly where it stands in its journey from draft to delivered. It is one validated enum value per Todo, persisted in `todos.db`, and read by every state machine, every CLI render, and every routing decision the workflow makes. Two operator surfaces mutate it directly: `telec todo mark-phase` records an authoritative override, and `telec todo reconcile` re-derives the pointer from the Todo's current evidence (artifacts, review verdicts, approval stamps, skip stamps, drift-review stamps) — bounded to one Stage so it cannot quietly jump lanes. Legacy v0/v1/v2/v3 phase strings persisted on older Todos auto-upcycle to v4 on read; the canonical pointer is the single source of truth for "where is this Todo, right now."

## Canonical fields

### Use cases

```
Given a Todo whose persisted lifecycle_phase is "prd_drafting"
When any caller (state machine, CLI, dispatcher) reads the Todo's state
Then the canonical phase coerces to LifecyclePhase.PRD_DRAFTING via coerce_lifecycle_phase
And every downstream routing decision uses that single pointer as the source of truth
```

```
Given an operator runs `telec todo mark-phase my-slug --phase plan_review`
When handle_mark_phase validates the requested value against the LifecyclePhase enum
Then validate_mark_phase_preconditions enforces stage- and worktree-appropriate preconditions
And the StateWriter persists lifecycle_phase = "plan_review" through the validated state-write boundary
And the prior phase, target phase, and resulting phase are logged
```

```
Given an operator passes an unknown phase value to `telec todo mark-phase`
When handle_mark_phase compares the value against {p.value for p in LifecyclePhase}
Then the command prints the valid lifecycle_phase values, the legacy prepare_phase values, and the legacy work_phase values to stderr
And exits with status 1 without touching state
```

```
Given a Todo with prd_approved stamped, requirements artifact present, but no architecture artifact yet
When an operator runs `telec todo reconcile my-slug --stage prepare`
Then reconcile_phase_state derives the highest prepare-lane phase the current evidence supports
And writes that phase as the new lifecycle_phase
And refuses to advance past evidence (cannot promote into work-lane phases from a --stage prepare reconcile)
```

```
Given a persisted Todo carries a legacy v2 lifecycle_phase like "input_assessment"
When upcycle_state_dict runs at read time
Then _upcycle_v2_to_v3 maps the legacy value through _V2_TO_V3_PHASE
And the read returns a valid v4 LifecyclePhase value
And the on-disk row stays unchanged until the next persisted write canonicalizes it
```

```
Given a Todo whose stored lifecycle_phase is the empty string or a value not in the enum
When require_lifecycle_phase is called with the read context
Then it raises ValueError naming the slug context and the offending raw value
And the calling state machine treats the Todo as invalid rather than guessing a phase
```

### Implementation pointers (v1)

- `teleclaude/core/next_machine/lifecycle.py:85-93` — `coerce_lifecycle_phase` normalizes legacy strings via `LEGACY_LIFECYCLE_PHASE_NORMALIZATION` and returns `LifecyclePhase | None`
- `teleclaude/core/next_machine/lifecycle.py:96-101` — `require_lifecycle_phase` raises with context on missing or invalid persisted phase
- `teleclaude/core/next_machine/lifecycle.py:104-116` — `lifecycle_phase_index`, `is_prepare_lifecycle_phase`, `is_work_lifecycle_phase` derive stage membership from the canonical order
- `teleclaude/core/next_machine/lifecycle.py:119-143` — `infer_lifecycle_stage`, `is_ready_for_work`, `is_in_prepare_lane` are the routing predicates state machines read
- `teleclaude/core/next_machine/lifecycle.py:472` — `reconcile_lifecycle_phase` is the evidence-driven re-derivation, bounded by `LifecycleStage`
- `teleclaude/core/next_machine/lifecycle.py:666` — `normalize_mark_phase` projects the requested override onto the typed `TodoState` (clearing dependent sub-state where required)
- `teleclaude/cli/telec/handlers/todo.py:55-79` — `handle_mark_phase` validates the operator's requested phase against the enum and prints the legacy candidates on failure
- `teleclaude/cli/telec/handlers/todo.py:82-114` — `_handle_todo_mark_phase` argv adapter that dispatches to `handle_mark_phase`
- `teleclaude/cli/telec/handlers/todo.py:117-156` — `_handle_todo_reconcile` parses `--stage` and invokes `reconcile_phase_state`
- `teleclaude/core/next_machine/state_io.py:168-186` — `read_phase_state` / `write_phase_state` are the typed read/write helpers every phase mutation goes through
- `teleclaude/core/next_machine/state_io.py:285-308` — `mark_phase_state` runs precondition validation, syncs reconcile artifacts, and persists through `StateWriter`
- `teleclaude/core/next_machine/state_io.py:311-349` — `reconcile_phase_state` derives the highest supported phase within one `LifecycleStage` and refuses to cross lanes
- `teleclaude/core/todos_db/_upcycle.py:87-141` — `_infer_v1_lifecycle_phase` builds the v1 phase from grounding, review verdicts, finalize status, and artifact presence
- `teleclaude/core/todos_db/_upcycle.py:169-233` — `_upcycle_v0_to_v1`, `_upcycle_v1_to_v2`, `_upcycle_v2_to_v3`, and `_upcycle_v3_to_v4` migrate persisted phase strings to the latest enum
- `teleclaude/core/todos_db/_upcycle.py:236-252` — `_upcycle_to_latest` is the read-time gateway that guarantees every state load carries a valid v4 `lifecycle_phase`

### Cross-context references

- `agent_runtime` — worker dispatch decisions read the canonical phase to decide which Worker command (`next-prepare`, `next-build`, `next-finalize`, etc.) to run for a given Todo. Workers never re-derive the phase; they trust the pointer.

## Known caveats

- `telec todo mark-phase` is an escape hatch. It bypasses the evidence requirements that the state machine normally enforces and writes the authoritative `lifecycle_phase` field directly — use it to unstick a Todo, not as a routine advance mechanism.
- `telec todo reconcile` never advances past the evidence on disk. If artifacts, stamps, and verdicts only support `prd_drafting`, reconcile will not promote the Todo to `prd_review` no matter how often it is run.
- Reconcile is **stage-bounded**. Passing `--stage prepare` will not promote a Todo into a work-lane phase even if the work-lane evidence is present; the operator must explicitly pass `--stage work` (or run `telec todo work`) to cross the lane boundary.
- The canonical lifecycle is **strictly forward**: draft → prepare-lane phases → prepared → work-lane phases → finalize_ready → delivered. Neither mark-phase nor reconcile is permitted to rewind a Todo to an earlier stage; rewinding requires a deliberate refinement flow that invalidates downstream approvals via `apply_authoritative_signal` / `invalidate_downstream_on_refine`.
- Legacy persisted rows with `lifecycle_phase="handed_off"` or `finalize.status="handed_off"` normalize on read to `lifecycle_phase="finalize_ready"` and `finalize.status="ready"`; no operator action is required.
- Legacy phase strings (`work_phase`, `prepare_phase`, `phase`, `grounding`, etc.) from v0/v1/v2 Todos are still tolerated on read: `_infer_v1_lifecycle_phase` reconstructs the canonical pointer from whatever evidence the older row carried. The mapping table in `_V2_TO_V3_PHASE` is intentionally preserved so historical rows continue to load.
- An invalid persisted `lifecycle_phase` is treated as a hard error, not a default. `require_lifecycle_phase` raises immediately — the platform refuses to guess a phase for a Todo whose pointer is missing or unrecognized.
