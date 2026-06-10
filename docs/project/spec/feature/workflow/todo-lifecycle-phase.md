---
description: 'Canonical lifecycle_phase pointer naming where a Todo stands in its journey, derived from artifact evidence by the workflow engine. No operator override or manual realignment surfaces.'
visibility: 'public'
---

# Todo Lifecycle Phase — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`lifecycle_phase` is the canonical pointer a Todo carries to name exactly where
it stands in its journey from draft to delivered. It is one validated enum value
per Todo, owned by the workflow context, and read by every state machine, every
CLI render, and every routing decision the workflow makes. It is **derived from
the Todo's evidence** — artifacts present, review verdicts, approval stamps, skip
stamps, drift-review stamps — by the workflow engine (`adopt_prepare_handoff_phase`
for the prepare lane, `apply_authoritative_signal` for the work lane), and is
re-derived each time the prepare/work state machine is dispatched. There is no
operator surface that sets the pointer against its evidence and no manual
realignment command; the pointer is never authored by hand. Legacy phase strings
on older Todos auto-upcycle on read; the canonical pointer is the single source of
truth for "where is this Todo, right now."

Drift between an upstream artifact and the downstream artifacts grounded against
it is detected objectively (`derive_lifecycle_drift`) and assessed for
**materiality** only by intelligence — the `/next-drift-analyze` worker stamps
`drift_reviewed` as `substantive` or `cosmetic`, and only a `substantive` verdict
cascades to clear the affected downstream review verdicts. No code path clears a
human's approval as a mechanical side effect of editing an artifact.

## Canonical fields

### Use cases

```
Given a Todo whose persisted lifecycle_phase is "prd_drafting"
When any caller (state machine, CLI, dispatcher) reads the Todo's state
Then the canonical phase coerces to PRD_DRAFTING
And every downstream routing decision uses that single pointer as the source of truth
```

```
Given a Todo whose evidence has changed (an artifact added, a verdict stamped)
When the prepare or work state machine is next dispatched for that Todo
Then the workflow engine re-derives lifecycle_phase from the current evidence
And never advances past the evidence on disk
```

```
Given a Todo with plan_approved stamped and an implementation-plan artifact present
When an operator edits and saves the implementation-plan artifact
Then the plan_approved stamp is NOT cleared by the write
And whether the change is material is left to the /next-drift-analyze judgment
And only a substantive drift-review verdict clears the affected downstream review
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

#### UC-TLP1: Kind update re-routes lifecycle_phase before build

```gherkin
Given an active Todo whose build has not started
When the operator runs "telec todo update my-todo --kind bug --force"
Then the workflow service validates the target kind
And resolves the target entry point through KIND_ENTRY_PHASE
And persists lifecycle_phase to that target entry phase through the validated state-write boundary
And any invalid old-kind artifacts are warned about or handled according to the force artifact-migration contract
```

```gherkin
Given an active Todo whose build has started
When the operator runs "telec todo update my-todo --kind task"
Then the workflow service refuses before changing lifecycle_phase or kind
And the current lifecycle_phase remains unchanged
```

### Cross-context references

- `agent_runtime` — worker dispatch decisions read the canonical phase to decide
  which Worker command (`next-prepare`, `next-build`, `next-finalize`, etc.) to
  run for a given Todo. Workers never re-derive the phase; they trust the pointer.

## Known caveats

- The pointer never advances past the evidence on disk. If artifacts, stamps, and
  verdicts only support `prd_drafting`, the Todo is not promoted to `prd_review`
  regardless of how often state is read.
- Re-derivation happens on state-machine dispatch (`telec todo prepare`/`work`).
  Editing an artifact between dispatches changes the evidence; the pointer reflects
  it at the next dispatch. There is no manual realignment command — the removed
  `telec todo reconcile` and `telec todo mark-phase` surfaces no longer exist.
- The canonical lifecycle is **strictly forward** under normal progression: draft
  → prepare-lane phases → prepared → work-lane phases → finalize_ready →
  delivered. A substantive artifact edit that drifts already-approved downstream
  work is rewound through the `/next-drift-analyze` judgment that invalidates the
  affected approvals — not by a code path that clears them unconditionally.
- Legacy persisted entries with `lifecycle_phase="handed_off"` or
  `finalize.status="handed_off"` normalize on read to
  `lifecycle_phase="finalize_ready"` and `finalize.status="ready"`; no operator
  action is required.
- Legacy phase strings from older versions are tolerated on read; the upcycle
  layer reconstructs the canonical pointer from whatever evidence the older entry
  carried.
- An invalid persisted `lifecycle_phase` is treated as a hard error, not a
  default. The platform refuses to guess a phase for a Todo whose pointer is
  missing or unrecognized.

## See Also

- docs/project/adr/0021-remove-reconcile-and-mark-phase.md — why the manual
  realignment/override surfaces were removed.
