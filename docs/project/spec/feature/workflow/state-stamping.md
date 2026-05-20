---
id: 'project/spec/feature/workflow/state-stamping'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'The `telec todo stamp` command and the validated state-write boundary it goes through — approvals, review verdicts, skip stamps, drift-reviewed acknowledgments, build-complete and finalize-ready handoffs.'
---

# State Stamping — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`telec todo stamp` is the single domain surface every caller — human operator, Worker session, or Orchestrator — uses to record a fact about a Todo: a reviewer's Verdict, a human PRD approval, an architecture skip with reason, a drift-reviewed acknowledgment, a worker's `build_complete` claim, or a worker's `finalize_ready` handoff. Every stamp routes through a single validated state-write boundary: `StateWriter` re-validates the full `TodoState` against the Pydantic model before any DB write, and `ApprovalsManager` / `ReviewManager` are the typed owners for approval-shaped and verdict-shaped mutations. The stamp records the fact; the state machine reads the fact on its next dispatch and advances the canonical `lifecycle_phase` accordingly. There is no path that writes Todo state outside this boundary in the migrated flows.

## Canonical fields

### Use cases

```
Given a Todo with a written PRD artifact and an existing prd-review verdict of "approve"
When a human runs `telec todo stamp my-slug --prd-approved`
Then _apply_approval_stamp confirms the PRD artifact exists, hydrates digest/produced_at/upstream_digests
And ApprovalsManager.approve records prd_approved with caller_session_id and now() timestamp
And StateWriter.commit re-validates the full state and persists in one transaction
And the next prepare-machine dispatch observes the approval and advances lifecycle_phase
```

```
Given a reviewer worker has read the implementation plan
When the worker runs `telec todo stamp my-slug --verdict approve --phase plan_review`
Then _validate_verdict_stamp checks the phase is in the allowed verdict-phase set and the verdict is in the allowed value set
Then ReviewManager.stamp_verdict writes verdict + reviewed_at to both the visible review state and the matching audit entry
And when verdict == "approve" the implementation_plan artifact digest is recorded as approved_digest
And the next prepare-machine dispatch observes the verdict and advances lifecycle_phase
```

```
Given a Todo whose nature does not require architecture work
When an operator runs `telec todo stamp my-slug --architecture-skipped "no architectural surface to design"`
Then ApprovalsManager.skip records a SkipStamp with the reason, timestamp, and caller_session_id
And the empty-reason variant is rejected with StateMutationError before any write
And the prepare chain advances past the architecture phase on next dispatch
```

```
Given an approved prepare artifact whose recorded sha drifts from the worktree HEAD with status "pending"
When a reviewer runs `telec todo stamp my-slug --drift-reviewed prd substantive "PRD refined for new scope"`
Then _apply_drift_reviewed_stamp parses the JSON-packed (artifact, verdict, reason) triple
And ApprovalsManager.drift_reviewed validates verdict is one of {substantive, cosmetic}
And persists the DriftReviewedStamp under approvals.drift_reviewed[artifact]
And the prepare gate stops treating the drift as blocking on next read
```

```
Given a worker session whose durable working_slug matches the Todo and whose lifecycle_phase is build_started
When the worker runs `telec todo stamp my-slug --build-complete`
Then _validate_build_complete_owner confirms the caller session owns working_slug == my-slug (PermissionError otherwise)
And _apply_build_complete_stamp confirms the current phase is build_started or review_changes_requested (StateMutationError otherwise)
And has_build_commits_beyond_main confirms the worktree has commits beyond main (StateMutationError otherwise)
And build_gate_claim_at is set to now() and persisted through StateWriter
And the work machine runs the build-complete gates on its next dispatch
```

```
Given a worker has produced a clean worktree ready for integration
When the worker runs `telec todo stamp my-slug --finalize-ready`
Then stamp_finalize_ready records the FinalizeModel with status="ready", the worktree HEAD as candidate sha, and caller_session_id
And the integrator dispatch consumes the finalize-ready handoff to merge the candidate into main
```

```
Given a caller submits state that does not validate against TodoState
When StateWriter.__init__ runs _validate_full_state
Then a StateMutationError is raised with the underlying ValidationError text
And no DB write happens — the stamp call exits with status 1 before any partial mutation lands
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py:648-711` — `_handle_todo_stamp` parses argv, validates required flag combinations, and runs `apply_todo_stamp` in an asyncio context
- `teleclaude/cli/telec/handlers/todo.py:714-729` — `_STAMP_BOOLEAN_FLAGS` and `_STAMP_REASON_FLAGS` define the operator surface: `--prd-approved`, `--plan-ready`, `--deferrals-processed`, `--build-complete`, `--architecture-skipped <reason>`
- `teleclaude/cli/telec/handlers/todo.py:732-771` — `_parse_todo_stamp_args` routes `--verdict <v> --phase <p>`, `--drift-reviewed <artifact> <verdict> <reason>`, and `--finalize-ready` into the unified `(slug, stamp_type, value, phase)` tuple
- `teleclaude/core/next_machine/stamps.py:76-133` — `apply_todo_stamp` is the domain entry point that picks the per-stamp-type handler and commits through `StateWriter`
- `teleclaude/core/next_machine/stamps.py:146-188` — `_apply_readiness_stamp` and `_apply_approval_stamp` validate the required artifact exists and hydrate digest / produced_at / upstream_digests provenance
- `teleclaude/core/next_machine/stamps.py:203-220` — `_apply_drift_reviewed_stamp` parses the JSON-packed (artifact, verdict, reason) triple and dispatches to `ApprovalsManager.drift_reviewed`
- `teleclaude/core/next_machine/stamps.py:223-266` — `_apply_build_complete_stamp` and `_validate_build_complete_owner` enforce worker ownership (`working_slug` match), valid current phase, and build commits beyond main
- `teleclaude/core/next_machine/state_io.py:357-432` — `stamp_verdict` is the typed verdict writer (prepare review phases via `ReviewManager`, build_review via direct typed mutation)
- `teleclaude/core/next_machine/state_io.py:435` — `stamp_finalize_ready` records the FinalizeModel with ready status, candidate sha, and caller session
- `teleclaude/core/next_machine/state_mutation.py:46-59` — `StateMutationError` and `_validate_full_state` reject malformed state with the Pydantic error text before any DB write
- `teleclaude/core/next_machine/state_mutation.py:67-158` — `StateWriter` is the single validated persistence boundary: load once, mutate typed model, re-validate, commit (async or sync)
- `teleclaude/core/next_machine/state_mutation.py:161-219` — `ApprovalsManager` owns approval / skip / drift-reviewed stamps and rejects empty-reason skip stamps
- `teleclaude/core/next_machine/state_mutation.py:221-239` — `ReviewManager` writes verdict to both the visible review state and the matching audit entry so they cannot diverge

### Cross-context references

- `identity` — every stamp records the `caller_session_id`; downstream `_session_principal` resolution turns that into the human or agent principal that authored the stamp, so audit trails name a responsible party.
- `agent_runtime` — worker sessions invoke `telec todo stamp` at phase boundaries (`--build-complete`, `--finalize-ready`, `--verdict … --phase build_review`); `_validate_build_complete_owner` reads the session's `working_slug` from the agent_runtime sessions table to enforce ownership.

## Known caveats

- The stamp is the **natural worker-completion authority** for build and finalize phases. `next-machine` does not advance into review or integration until the stamp lands; conversely, the stamp does not run the gates itself — it records the claim and lets the state machine run gates on its next dispatch. This split prevents minute-long stamp calls and the zombie processes a synchronous gate run would create.
- `--build-complete` is **worker-owned and locked**: the caller's TeleClaude session must own `working_slug == <slug>`. Operators cannot stamp build-complete from a plain shell; the stamp raises `PermissionError` when the session id is missing or the working_slug does not match.
- `--build-started` is **machine-owned**: the stamp rejects this flag explicitly and instructs the caller to run `telec todo work <slug>` so the work state machine owns the transition.
- `ApprovalsManager` clears downstream approvals when an upstream artifact is re-opened. Refining the PRD invalidates the chain of architecture, plan, and finalize-ready approvals that depended on it — the state machine then re-runs the affected review and approval gates on next dispatch.
- The `--architecture-skipped` skip stamp **requires a non-empty reason**. `ApprovalsManager._require_reason` raises `StateMutationError` if the reason is empty or whitespace-only; the skip is rejected before any write.
- `--finalize-ready` requires the worktree to be in a finalize-ready state — the work-machine gates check for a clean worktree and present commits before honoring the handoff. A worker that stamps `--finalize-ready` from a dirty worktree will have the stamp recorded but the integrator dispatch will refuse to merge.
- Drift-reviewed verdicts are constrained to `{substantive, cosmetic}`. Any other verdict value is rejected by `ApprovalsManager.drift_reviewed` with `StateMutationError`; the JSON payload itself must be a well-formed object with string `artifact`, `verdict`, and `reason` fields.
- Bug-kind Todos still require the explicit `--build-complete` stamp before the work machine will advance past build — bypassing the stamp leaves the bug stuck in `build_started`. The bug-fix worker is responsible for issuing it as the last act of the fix flow.
