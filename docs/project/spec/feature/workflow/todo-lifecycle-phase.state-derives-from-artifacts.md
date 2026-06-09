---
id: 'project/spec/feature/workflow/todo-lifecycle-phase'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Canonical lifecycle_phase pointer naming where a Todo stands in its journey, derived from artifact evidence — recomputed automatically on every artifact mutation, with no manual override surfaces.'
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
CLI render, and every routing decision the workflow makes. It is a **pure
function of the Todo's evidence** — artifacts present, review verdicts, approval
stamps, skip stamps, drift-review stamps — derived by the workflow engine
(`adopt_prepare_handoff_phase` for the prepare lane, `apply_authoritative_signal`
for the work lane). There is no operator surface that sets the pointer against
its evidence; the pointer is never authored by hand. Legacy phase strings on
older Todos auto-upcycle on read; the canonical pointer is the single source of
truth for "where is this Todo, right now."

Re-derivation is a **consequence of artifact mutation**, not a separate command.
When any prepare-lane artifact is written or removed, the workflow recomputes
**objective drift** for the mutated artifact and its downstream dependents
(`derive_lifecycle_drift` — digest, timestamp, and dependency-graph comparison;
"the PRD changed since the plan was grounded against it" is a statement of fact),
then re-derives `lifecycle_phase` from the post-mutation evidence through the same
engine the state machine uses. When drift invalidates the grounding, the pointer
derives to the re-grounding phase. Saving an artifact is therefore sufficient to
keep the pointer correct; no manual realignment step exists or is needed.

Drift **detection** is objective and lives in code; drift **materiality** — does
the change actually invalidate an approval or a downstream artifact — is a
judgment reserved for intelligence (the drift-analysis worker, reviewers), never
made by code (`general/principle/intelligence-boundaries`). A write or remove
**never** clears a human's approval or a review verdict as a side effect:
approvals stay bound to the digest they approved, drift exposes the mismatch, and
intelligence decides whether the change is material. A cosmetic change
(whitespace, a typo) flags drift but forces no rework; a substantive change is
escalated to the drift-analysis judgment, which is what may rewind downstream
work.

## Canonical fields

### Use cases

```
Given a Todo whose persisted lifecycle_phase is "prd_drafting"
When any caller (state machine, CLI, dispatcher) reads the Todo's state
Then the canonical phase coerces to PRD_DRAFTING
And every downstream routing decision uses that single pointer as the source of truth
```

```
Given a Todo with plan_approved stamped and an implementation-plan artifact present
When the operator edits and saves the implementation-plan artifact
Then objective drift is recomputed for the implementation-plan and its dependents
And lifecycle_phase is re-derived from the post-write evidence
And the plan_approved stamp is NOT cleared by the write
And whether the edit invalidates the approval is left to the drift-analysis judgment
```

```
Given a Todo with prd_approved stamped, requirements artifact present, but no architecture artifact yet
When state is read or any artifact is mutated
Then the workflow derives the highest prepare-lane phase the current evidence supports
And never advances past the evidence on disk
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

- `agent_runtime` — worker dispatch decisions read the canonical phase to decide
  which Worker command (`next-prepare`, `next-build`, `next-finalize`, etc.) to
  run for a given Todo. Workers never re-derive the phase; they trust the pointer.

## Known caveats

- The pointer never advances past the evidence on disk. If artifacts, stamps, and
  verdicts only support `prd_drafting`, the Todo is not promoted to `prd_review`
  regardless of how often state is recomputed.
- The canonical lifecycle is **strictly forward** under normal progression: draft
  → prepare-lane phases → prepared → work-lane phases → finalize_ready →
  delivered. A substantive artifact edit that drifts already-approved downstream
  work is rewound through the drift-analysis judgment that invalidates the
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
