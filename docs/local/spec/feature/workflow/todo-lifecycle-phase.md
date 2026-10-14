---
description: 'Canonical lifecycle_phase pointer naming where a Todo stands in its journey, derived from artifact evidence by the workflow engine. No operator override or manual realignment surfaces.'
visibility: 'public'
---

# Todo Lifecycle Phase — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

`lifecycle_phase` is the canonical pointer a Todo carries to name exactly where
it stands in its journey from draft to delivered. It is one validated enum value
per Todo, owned by the workflow context, and read by every state machine, every
CLI render, and every routing decision the workflow makes. It is **derived from
the Todo's evidence** — artifacts present, review verdicts, approval stamps, skip
stamps, drift-review stamps — by the workflow engine (`adopt_prepare_handoff_phase`
for the prepare lane, `apply_authoritative_signal` for the work lane), and is
re-derived each time the prepare/work state machine is dispatched. There is no
general operator surface that sets the pointer against its evidence and no manual
realignment command; the pointer is never authored by hand. The bounded
code-conformance return below is the only exception. Legacy phase strings
on older Todos auto-upcycle on read; the canonical pointer is the single source of
truth for "where is this Todo, right now."

The canonical enum includes `task_plan_drafting` and `task_running` — task-lane phases owned by the task lane, not by the SDLC prepare or work state machines. `task_plan_drafting` holds a kind=`task` Todo from kind assignment or task creation until `sdlc/procedure/lifecycle/task/prepare-task` writes a `task-plan`; the phase then advances to `prepared` (awaiting human authorization). `task_running` is the non-SDLC live execution marker while `sdlc/procedure/lifecycle/task/run-task` is dispatched by the lifecycle runner; it is not a build/review/finalize phase and does not satisfy SDLC work gates.

Drift between an upstream artifact and the downstream artifacts grounded against
it is detected objectively (`derive_lifecycle_drift`) and assessed for
**materiality** only by intelligence — the `sdlc/procedure/lifecycle/prepare/drift-analyze` worker stamps
`drift_reviewed` as `substantive` or `cosmetic`, and only a `substantive` verdict
cascades to clear the affected downstream review verdicts. No code path clears a
human's approval as a mechanical side effect of editing an artifact.

The only explicit work-phase return is `telec todo return-to-work`. It recovers a
held, unclaimed, undelivered Todo at `finalize_ready` when independently
established code-conformance evidence requires another implementation cycle.
The operation returns the phase to `build_started`, clears only the stale
finalize-ready and build-review eligibility fields, and records its reason and
evidence in the Todo's event history in the same state write. Preparation
approvals, plan and artifacts, worktree, branch, commits, candidate refs, review
round history, and hold remain intact. This is a bounded recovery operation,
not a general phase override.

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
And whether the change is material is left to the sdlc/procedure/lifecycle/prepare/drift-analyze judgment
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

```
Given a Todo of kind bug whose diagnosis artifact is present
When the workflow engine derives the canonical phase
Then the phase stays DIAGNOSE until a settled stamp is current for that artifact's digest
And a revision of the artifact invalidates the stamp and returns the phase to DIAGNOSE
And the phase advances to PLAN_DRAFTING only on a current settled stamp
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

#### UC-TLP2: Delivery evidence derives the terminal lifecycle phase

```gherkin
Given an active Todo has completed its implementation lifecycle
When a lifecycle caller persists that Todo's delivered status and delivery evidence
Then the workflow service derives lifecycle_phase as DELIVERED through its validated state-write boundary
And every later reader observes DELIVERED as the canonical phase
And no caller bypasses derivation by manually overriding the pointer
```

#### UC-TLP3: Stored artifact evidence decides whether a review's remediation has landed

```gherkin
Given a Todo whose plan review requested changes
And the implementation-plan artifact has since been stored again, so its stored revision is newer than that review
When the prepare state machine re-derives the Todo's lifecycle phase
Then the derived phase returns the Todo to plan review
And no blocker reports the remediation write as absent
```

#### UC-TLP4: A code-conformance finding returns a held candidate to the work cycle

```gherkin
Given an agent has an active todo held after finalization
And its code-conformance review found an addressable issue
And no work session is active in this project's candidate worktree
And no integration attempt owns the candidate
When the agent returns the candidate with a reason and evidence address
Then the reason, evidence address, agent, and candidate revision are recorded together
And the prior finalization and independent approval no longer authorize integration
And preparation approvals, plan, branch, worktree, commits, review-round history, and hold remain unchanged
And a later manual work invocation starts the ordinary build, independent review, fix, and finalization cycle
```

#### UC-TLP5: A return without its finding is refused with the invocation

```gherkin
Given an agent has a held candidate after finalization
When it requests a return without a reason or evidence address
Then the platform refuses before changing the candidate
And prints usage showing that the command requires both values
```

#### UC-TLP6: A candidate without a completed finalization cannot return to work

```gherkin
Given an active todo is held but has not completed finalization
When an agent requests a code-conformance return
Then the platform refuses without changing the todo
And directs the agent to continue through the ordinary work cycle
```

#### UC-TLP7: An unheld candidate cannot return to work

```gherkin
Given an active todo has completed finalization but is not held
When an agent requests a code-conformance return
Then the platform refuses without changing the todo
And names the hold command needed to park the candidate first
```

#### UC-TLP8: A live work session keeps ownership of its candidate

```gherkin
Given an active todo has completed finalization and a live work session owns its candidate
When another agent requests a code-conformance return
Then the platform refuses without changing the todo
And directs the requester to let the owning work session finish and release its claim
```

#### UC-TLP9: An active integration attempt keeps ownership of its candidate

```gherkin
Given an integration attempt is active or awaiting recovery
When an agent requests a code-conformance return for its candidate
Then the platform refuses without changing the todo
And directs the agent to let integration settle or recover through the integration lifecycle
```

#### UC-TLP10: A delivered candidate uses the post-delivery correction path

```gherkin
Given a candidate has already been committed to the shared branch or delivered
When an agent requests a code-conformance return
Then the platform refuses without changing the todo
And directs the agent to the ordinary post-delivery defect or change path
```

#### UC-TLP11: A same-named session in another project does not own this candidate

```gherkin
Given two projects each have an active todo with the same slug
And only the other project has a live worktree session for that slug
And this project's held candidate has no active work or integration owner
When an agent returns this project's candidate after a code-conformance finding
Then the other project's session does not block the return
```

### Cross-context references

- `agent_runtime` — worker dispatch decisions read the canonical phase to decide
  which entry procedure (the prepare overview, the build procedure, the finalize
  procedure, etc.) to run for a given Todo. Workers never re-derive the phase;
  they trust the pointer.

## Known caveats

- The pointer never advances past the evidence on disk. If artifacts, stamps, and
  verdicts only support `prd_drafting`, the Todo is not promoted to `prd_review`
  regardless of how often state is read.
- Re-derivation happens on state-machine dispatch (`telec todo prepare`/`work`).
  Editing an artifact between dispatches changes the evidence; the pointer reflects
  it at the next dispatch. There is no general manual realignment command; the
  removed `telec todo reconcile` and `telec todo mark-phase` surfaces remain
  retired. The held-candidate code-conformance return is the sole bounded recovery
  exception described above.
- The canonical lifecycle is **strictly forward** under normal progression: draft
  → prepare-lane phases → prepared → work-lane phases → finalize_ready →
  delivered. A substantive artifact edit that drifts already-approved downstream
  work is rewound through the `sdlc/procedure/lifecycle/prepare/drift-analyze` judgment that invalidates the
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

- docs/local/adr/0021-remove-reconcile-and-mark-phase.md — why the manual
  realignment/override surfaces were removed.
