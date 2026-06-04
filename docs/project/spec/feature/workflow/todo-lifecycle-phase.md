---
id: 'project/spec/feature/workflow/todo-lifecycle-phase'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Canonical lifecycle_phase pointer naming where a Todo stands in its journey, plus the operator override (mark-phase) and the evidence-driven realignment (reconcile).'
---

# Todo Lifecycle Phase — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`lifecycle_phase` is the canonical pointer a Todo carries to name exactly where it stands in its journey from draft to delivered. It is one validated enum value per Todo, owned by the workflow context, and read by every state machine, every CLI render, and every routing decision the workflow makes. Two operator surfaces mutate it directly: `telec todo mark-phase` records an authoritative override, and `telec todo reconcile` re-derives the pointer from the Todo's current evidence (artifacts, review verdicts, approval stamps, skip stamps, drift-review stamps) — bounded to one Stage so it cannot quietly jump lanes. Legacy phase strings on older Todos auto-upcycle on read; the canonical pointer is the single source of truth for "where is this Todo, right now."

## Canonical fields

### Use cases

```
Given a Todo whose persisted lifecycle_phase is "prd_drafting"
When any caller (state machine, CLI, dispatcher) reads the Todo's state
Then the canonical phase coerces to PRD_DRAFTING
And every downstream routing decision uses that single pointer as the source of truth
```

```
Given the operator runs "telec todo mark-phase my-slug --phase plan_review"
When the workflow service validates the requested value against the canonical phase enum
Then it enforces stage- and worktree-appropriate preconditions
And persists lifecycle_phase = "plan_review" through the validated state-write boundary
And the prior phase, target phase, and resulting phase are logged
```

```
Given the operator passes an unknown phase value to "telec todo mark-phase"
When the workflow service compares the value against the canonical enum
Then the command reports the valid canonical phases and any legacy phase values still recognised
And exits with status 1 without touching state
```

```
Given a Todo with prd_approved stamped, requirements artifact present, but no architecture artifact yet
When the operator runs "telec todo reconcile my-slug --stage prepare"
Then the workflow service derives the highest prepare-lane phase the current evidence supports
And writes that phase as the new lifecycle_phase
And refuses to advance past evidence (cannot promote into work-lane phases from a --stage prepare reconcile)
```

```
Given a persisted Todo carries a legacy lifecycle_phase value
When state is read
Then the upcycle layer maps the legacy value through the canonical normalization table
And the read returns a valid canonical lifecycle_phase
And the persisted value stays unchanged until the next persisted write canonicalizes it
```

```
Given a Todo whose stored lifecycle_phase is the empty string or a value not in the enum
When the workflow service is asked for the canonical phase
Then it raises an error naming the slug context and the offending raw value
And the calling state machine treats the Todo as invalid rather than guessing a phase
```

### Cross-context references

- `agent_runtime` — worker dispatch decisions read the canonical phase to decide which Worker command (`next-prepare`, `next-build`, `next-finalize`, etc.) to run for a given Todo. Workers never re-derive the phase; they trust the pointer.

## Known caveats

- `telec todo mark-phase` is an escape hatch. It bypasses the evidence requirements that the state machine normally enforces and writes the authoritative `lifecycle_phase` field directly — use it to unstick a Todo, not as a routine advance mechanism.
- `telec todo reconcile` never advances past the evidence on disk. If artifacts, stamps, and verdicts only support `prd_drafting`, reconcile will not promote the Todo to `prd_review` no matter how often it is run.
- Reconcile is **stage-bounded**. Passing `--stage prepare` will not promote a Todo into a work-lane phase even if the work-lane evidence is present; the operator must explicitly pass `--stage work` (or run `telec todo work`) to cross the lane boundary.
- The canonical lifecycle is **strictly forward**: draft → prepare-lane phases → prepared → work-lane phases → finalize_ready → delivered. Neither mark-phase nor reconcile is permitted to rewind a Todo to an earlier stage; rewinding requires a deliberate refinement flow that invalidates downstream approvals.
- Legacy persisted entries with `lifecycle_phase="handed_off"` or `finalize.status="handed_off"` normalize on read to `lifecycle_phase="finalize_ready"` and `finalize.status="ready"`; no operator action is required.
- Legacy phase strings from older versions are tolerated on read; the upcycle layer reconstructs the canonical pointer from whatever evidence the older entry carried.
- An invalid persisted `lifecycle_phase` is treated as a hard error, not a default. The platform refuses to guess a phase for a Todo whose pointer is missing or unrecognized.
