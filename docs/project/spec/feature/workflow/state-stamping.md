---
description: 'The `telec todo stamp` command and the validated state-write boundary it goes through — kind assignment, approvals, review verdicts, skip stamps, drift-reviewed acknowledgments, build-complete and finalize-ready handoffs.'
visibility: 'public'
---

# State Stamping — Spec


## What it is

`telec todo stamp` is the single domain surface every caller — human operator, Worker session, or Orchestrator — uses to record a fact about a Todo: an analyzer's kind assignment, a reviewer's Verdict, a human PRD approval, an architecture skip with reason, a drift-reviewed acknowledgment, a worker's `build_complete` claim, or a worker's `finalize_ready` handoff. Every stamp routes through a single validated state-write boundary: the workflow service re-validates the full Todo state against its typed model before any commit, and the kind-assignment, approvals, and review managers are the typed owners for kind-shaped, approval-shaped, and verdict-shaped mutations. The stamp records the fact; the state machine reads the fact on its next dispatch and advances the canonical `lifecycle_phase` accordingly. There is no path that writes Todo state outside this boundary.

The same state-write boundary owns artifact-write provenance capture. On every `telec todo artifacts write` for a drift-tracked artifact (`input`, `prd`, `architecture`, `implementation-plan`), the workflow's provenance boundary records the evidence needed for every drift class applicable to that artifact. Existing persisted fields: `codebase_sha_at_write` (captured via the origin-main-sha helper — never local HEAD) and `referenced_paths`, plus `upstream_digests` (the persisted-state field, aka `upstream_artifact_digests` in spec/documentation). Added persisted fields: `owned_snippet_digests`, `referenced_snippet_digests`, and `produced_at` — pure additive defaults with no migration. See `@spec/feature/workflow/drift-detection` for the per-class semantics. Rewriting an artifact re-captures all provenance fields at the new write and clears every drift-reviewed stamp for that artifact so the next derivation starts from a fresh anchor.

## Canonical fields

### Use cases

#### UC-WSS1: Task kind assignment routes to task-plan drafting

```
Given a kind-less Todo whose kind is unset, whose lifecycle_phase is absent, and whose input artifact holds the raw dump
When the analyzer runs "telec todo stamp my-slug --kind-assign task"
Then the kind-assignment handler validates the todo is still kind-less and the assigned kind is canonical
And it fixes kind="task" exactly once and writes no task-plan artifact
And it sets lifecycle_phase=KIND_ENTRY_PHASE["task"] ("task_plan_drafting")
And `/next-prepare-task` owns converting the input into a task-plan
And the state-write boundary re-validates the full state and persists atomically
```

#### UC-WSS2: SDLC kind assignment fixes kind and enters its lane

```
Given a kind-less Todo whose kind is unset and whose lifecycle_phase is absent
When the analyzer runs "telec todo stamp my-slug --kind-assign change"
Then the kind-assignment handler fixes kind="change", writes no task-plan artifact
And it sets lifecycle_phase=KIND_ENTRY_PHASE["change"] ("plan_drafting")
And the state-write boundary re-validates the full state and persists atomically
```

#### UC-WSS3: Already-kinded todo refuses kind assignment

```
Given a Todo whose kind is already fixed
When a caller runs "telec todo stamp my-slug --kind-assign <kind>"
Then the stamp is refused before any write because kind is assigned exactly once
And no partial kind, task-plan, or phase mutation lands
```

```
Given a Todo with a written PRD artifact and an existing prd-review verdict of "approve"
When a human runs "telec todo stamp my-slug --prd-approved"
Then the approval handler confirms the PRD artifact exists and hydrates digest/produced_at/upstream_digests
And the approvals manager records prd_approved with caller_session_id and the current timestamp
And the state-write boundary re-validates the full state and persists atomically
And the next prepare-machine dispatch observes the approval and advances lifecycle_phase
```

#### UC-WSS5: Human PRD approval records the current PRD digest

```gherkin
Given a Todo with a written PRD artifact
When a human runs "telec todo stamp my-slug --prd-approved"
Then the stamp hydrates the current PRD artifact provenance before recording the approval
And the recorded prd_approved Stamp includes caller_session_id, approved_at, and approved_digest
And approved_digest equals the current PRD artifact digest
And the state-write boundary re-validates the full state and persists atomically
```

#### UC-WSS18: Prepare claimant records an owner-directed literal correction

<!-- planned-change:review-verdicts-bind-evidence -->
```gherkin
Given the human owner explicitly supplies an exact literal PRD replacement in a live conversation
And the active prepare claimant applies only that bounded replacement
And the human directs the claimant to approve the corrected digest
When the claimant runs `telec todo stamp my-slug --verdict approve --phase prd_review`
Then the review manager records approve against the current PRD digest
And no independent PRD reviewer is required for that correction
And the session transcript remains the authority record without the claimant impersonating the human
And any correction requiring synthesis or judgment remains subject to normal independent review
```
<!-- change:review-verdicts-bind-evidence -->
```gherkin
Given the human owner explicitly supplies an exact literal PRD replacement in a live conversation
And the active prepare claimant applies only that bounded replacement
And the human directs the claimant to approve the corrected digest
When the claimant writes the complete `prd-review-findings` report recording the bounded replacement, closure rationale, and authenticated authority transcript
And the claimant runs `telec todo stamp my-slug --verdict approve --phase prd_review`
Then the review manager records approve against the current PRD and report digests
And no independent PRD reviewer is required for that correction
And the report states the exceptional closure path without impersonating an independent reviewer
And the session transcript remains the authority record without the claimant impersonating the human
And any correction requiring synthesis or judgment remains subject to normal independent review
```
<!-- /planned-change:review-verdicts-bind-evidence -->

<!-- planned-change:review-verdicts-bind-evidence -->
```
Given a reviewer worker has read the implementation plan
When the worker runs "telec todo stamp my-slug --verdict approve --phase plan_review"
Then the verdict-stamp validation checks the phase is in the allowed verdict-phase set and the verdict is in the allowed value set
And the review manager writes verdict + reviewed_at to both the visible review state and the matching audit entry
And when verdict == "approve" the implementation_plan artifact digest is recorded as approved_digest
And the next prepare-machine dispatch observes the verdict and advances lifecycle_phase
```
<!-- change:review-verdicts-bind-evidence -->
#### UC-WSS19: Every live review verdict binds current target and report evidence

```gherkin
Given a reviewer has written the complete report artifact for a PRD, architecture, plan, or build review pass
And the reviewed target and report each have a current digest
When an authorized reviewer or orchestrator stamps an allowed verdict for that live review phase
Then the review manager records the verdict, reviewed target digest, report digest, caller session id, and timestamp together
And a prepare review mirrors the verdict and timestamp to its matching audit entry
And the full typed state is validated before the state and evidence binding commit atomically
And the stamp is refused before mutation when the report is absent, either current digest cannot be resolved, or the caller identity is absent
And reviewer authority remains the normal path while orchestrator recovery authority remains unchanged
```
<!-- /planned-change:review-verdicts-bind-evidence -->

<!-- planned:review-verdicts-bind-evidence -->
#### UC-WSS20: Retired requirements review cannot create a live verdict

```gherkin
Given historical requirements and requirements-review-findings artifacts remain readable but retired from writes
When a caller attempts to stamp a verdict with phase requirements_review
Then the verdict surface refuses the phase before any state mutation
And legacy import never synthesizes requirements_review or plan_review approval from artifact presence
And delivered historical records remain unchanged and readable
```
<!-- /planned:review-verdicts-bind-evidence -->

```
Given a Todo whose nature does not require architecture work
When an operator runs "telec todo stamp my-slug --architecture-skipped 'no architectural surface to design'"
Then the approvals manager records a skip stamp with the reason, timestamp, and caller_session_id
And the empty-reason variant is rejected before any write
And the prepare chain advances past the architecture phase on next dispatch
```

#### UC-WSS10: Operator gate approval wakes the parked runner session

```gherkin
Given a Todo parked at a human-approval gate whose active_runner is a live, open session
When the operator approves the gate from the TUI control (the approve request carries the operator marker)
Then the gate is stamped approved through the normal state-write boundary
And a [TeleClaude Notification] is delivered into the active_runner session telling it the human approved and to proceed
And delivery is best-effort: a missing, closed, or undeliverable session is logged and never turns the approval into a failure
```

```gherkin
Given an agent clears its own gate via the CLI stamp (no operator marker)
When the gate is stamped approved
Then no notification is delivered into any session
And an agent never messages itself about an approval it just recorded
```

#### UC-WSS9: Human task authorization stamps execution approval

```gherkin
Given a Todo has kind="task", lifecycle_phase="prepared", and a current `task-plan` artifact
When a human authorizes the task from the TUI or runs `telec todo stamp my-slug --task-approved`
Then workflow records a task authorization stamp with caller_session_id, approved_at, and approved_digest set to the current `task-plan` digest
And the state-write boundary re-validates the full Todo state before commit
And workflow emits `workflow.todo.updated` so the lifecycle runner re-evaluates task eligibility
```

```gherkin
Given a Todo is not kind="task", is not prepared, or lacks a `task-plan`
When a caller attempts the task authorization stamp
Then workflow refuses before mutating state
And no runner wake-up is emitted
```

```gherkin
Given a task has a `task_approved` stamp whose `approved_digest` was recorded against an earlier `task-plan`
When the `task-plan` is edited so its current digest no longer equals the stamped `approved_digest`
Then the lifecycle runner treats the task as unauthorized and does not dispatch `/next-run-task`
And the task stays unauthorized until a fresh `task_approved` stamp re-binds `approved_digest` to the current `task-plan`
```

```
Given an approved prepare artifact whose per-class drift derivation collapses to "pending" on any class enumerated in @spec/feature/workflow/drift-detection
When the next-drift-analyze worker runs "telec todo stamp my-slug --drift-reviewed prd cosmetic 'rename-only refactor, intent preserved'"
Then the drift-reviewed handler parses the (artifact, verdict, reason) triple
And the approvals manager validates verdict is one of {substantive, cosmetic}
And persists the drift-reviewed stamp under approvals.drift_reviewed[artifact] including the evidence anchor at stamp time (head_sha_at_review, upstream_digests_at_review, snippet_digests_at_review)
And the prepare gate stops treating the drift as blocking on next read for as long as current evidence has not moved past the anchor on any dimension
And when later evidence moves past the anchor (HEAD advances with new referenced-path overlap, OR upstream digest changes, OR snippet digest changes), the cosmetic verdict is treated as expired-for-class and the class re-pends automatically — no manual stamp clearing required
```

```
Given the same artifact at "pending" drift status
When the next-drift-analyze worker runs "telec todo stamp my-slug --drift-reviewed architecture substantive 'upstream PRD rewrote success criteria; design must re-derive'"
Then the substantive drift-reviewed stamp is persisted with the same evidence-anchor fields recorded for audit
And the approvals manager clears the architecture review verdict and every downstream review verdict (plan in this case) as part of the same commit
And the prepare state machine routes back to architecture_drafting on next dispatch
And the substantive stamp does not need lazy expiry — re-derivation produces a fresh artifact whose write clears the drift stamps and re-captures provenance
```

#### UC-WSS4: Build-complete accepts the owning worker or work orchestrator

```gherkin
Given a worker session whose durable working_slug matches the Todo, or a work-orchestrator session whose durable system_role is "orchestrator"
And the Todo lifecycle_phase is build_started
When the trusted session runs "telec todo stamp my-slug --build-complete"
Then the build-complete ownership check accepts the caller because working_slug == my-slug or system_role == orchestrator
And a missing session id, a plain operator shell, or a foreign worker session is refused before any write
And the build-complete handler confirms the current phase is build_started or review_changes_requested (refused otherwise)
And the worktree-commits check confirms the worktree has commits beyond main (refused otherwise)
And build_gate_claim_at is set to the current timestamp and persisted through the state-write boundary
And the work machine runs the build-complete gates on its next dispatch
```

<!-- planned-change:kickback-fully-retracts-work-state -->
#### UC-WSS11: Work orchestrator kicks an unbuildable todo back to plan drafting

```gherkin
Given a Todo at a work phase whose implementation-plan cannot be executed as written
And a work-orchestrator session whose durable system_role is "orchestrator"
When the orchestrator runs "telec todo stamp my-slug --kickback --reason '<why the plan cannot be built>'"
Then the kickback ownership check accepts the caller because system_role == orchestrator
And a worker session, a plain operator shell, or a missing session id is refused before any write
And the stamp creates the input artifact when the Todo has none or appends a delimited kickback block carrying the reason to the existing input
And the stamp clears the implementation-plan review verdict and marks it cleared-by-substantive-drift, the same invalidation a substantive plan drift verdict produces
And the state-write boundary re-validates the full state and persists atomically
And the next prepare-machine dispatch derives lifecycle_phase plan_drafting and dispatches the planner, which reads the input kickback block as authoritative re-derivation context
```
<!-- change:kickback-fully-retracts-work-state -->
#### UC-WSS11: A kickback fully retracts the work phase in one transition

```gherkin
Given a Todo at any work phase — build_started through finalize_ready — whose implementation-plan cannot be executed as written
And a work-orchestrator session whose durable system_role is "orchestrator"
When the orchestrator runs "telec todo stamp my-slug --kickback --reason '<why the plan cannot be built>'"
Then the kickback ownership check accepts the caller because system_role == orchestrator
And a worker session, a plain operator shell, or a missing session id is refused before any write
And the stamp creates the input artifact when the Todo has none or appends a delimited kickback block carrying the reason to the existing input
And the stamp clears the implementation-plan review verdict and marks it cleared-by-substantive-drift, the same invalidation a substantive plan drift verdict produces
And the stamp ends the slug's live worker sessions and waits for each to reach a terminal state before any destructive step, refusing the retraction when a worker cannot be drained
And the stamp releases the slug's working resources (worktree, local and remote branch, workspace directory) only after the workers are drained, keeping the durable todo and its artifacts
And the stamp clears the work-phase state — the build-started base sha, the build-complete claim, the build-review state, and the finalize handoff — and re-derives lifecycle_phase so the Todo lands at plan_drafting
And the stamp releases the runner claim — active_runner and the claiming session's working_slug binding — as the final step, so no fresh dispatch races the cleanup
And the state-write boundary re-validates the full state and persists atomically
And the stamp response carries the orchestrator's remaining wind-down instruction: end self, and do not call telec todo work again
And a subsequent prepare dispatch for the slug succeeds with no manual unclaim and no manual session ending, slug and kind mutation are no longer refused on build-started grounds, and a dependent todo no longer counts the Todo as having cleared preparation
```
<!-- /planned-change:kickback-fully-retracts-work-state -->

```
Given a worker has produced a clean worktree ready for integration
When the worker runs "telec todo stamp my-slug --finalize-ready"
Then the finalize-ready handler records the finalize stamp with status="ready", the worktree HEAD as candidate sha, and caller_session_id
And the integrator dispatch consumes the finalize-ready handoff to merge the candidate into main
```

```
Given a caller submits state that does not validate against the Todo state model
When the state-write boundary runs its full-state validation
Then a state-mutation error is raised with the underlying validation text
And no commit happens — the stamp call exits before any partial mutation lands
```

#### UC-WSS12: One-shot task success outcome delivers the todo

```gherkin
Given a Todo has kind="task", a one-shot schedule (no cron recurrence), and a live run session as its active_runner
When the run session runs "telec todo stamp my-slug --task-outcome success"
Then the stamp confirms the todo is kind="task" and resolves the schedule as one-shot
And the todo is delivered through the existing delivery path, satisfying its dependents
And the lifecycle runner skips the delivered todo and does not re-dispatch /next-run-task after the run session closes
```

#### UC-WSS13: Recurring task success outcome clears an error-hold and stays live

```gherkin
Given a Todo has kind="task", a recurring cron schedule, and a hold whose hold_audit source is the task-error source
When the run session runs "telec todo stamp my-slug --task-outcome success"
Then the stamp resolves the schedule as recurring and clears the task-error hold
And the todo is not delivered and stays live for its next scheduled instant
And a hold whose source is a human pause is left untouched by the same success outcome
```

#### UC-WSS14: Task error outcome holds the todo with its reason

```gherkin
Given a Todo has kind="task" and a live run session as its active_runner
When the run session runs "telec todo stamp my-slug --task-outcome error --reason '<why a human is needed>'"
Then the stamp records hold=true and hold_audit with the task-error source, the reason, and the caller session id
And the held todo is not auto-re-dispatched and the run session stays alive as the beacon for human resolution
And an error outcome with an empty or missing reason is refused before any write
And a task-outcome stamp on a Todo that is not kind="task" is refused before any write
```

<!-- planned:fix-work-verdict-stamp-silent-noop -->

#### UC-WSS15: A build_review verdict stamped off the build_complete phase is refused, not silently recorded

```gherkin
Given a Todo at lifecycle_phase="review_changes_requested" (not "build_complete")
When a caller runs "telec todo stamp my-slug --verdict approve --phase build_review" without --force
Then the stamp is refused before any write, because the work machine consumes a build_review verdict only at lifecycle_phase="build_complete"
And the refusal reports that the verdict was NOT applied, names the phase mismatch, and states the preferred path of reaching build_complete first (a builder stamps "telec todo stamp my-slug --build-complete") before stamping the verdict
And build_review.verdict and lifecycle_phase are left unchanged
And running the same stamp with --force records the verdict, sets lifecycle_phase="build_complete" so the next "telec todo work" dispatch consumes it, and reports that build-complete-first sequencing was bypassed
And --force passed with any stamp other than a "--verdict ... --phase build_review" stamp is refused before any write
And a build_review verdict stamped while already at lifecycle_phase="build_complete" is recorded unchanged, whether or not --force is present
```

<!-- /planned:fix-work-verdict-stamp-silent-noop -->

#### UC-WSS16: A settled diagnosis stamp binds to the artifact digest that earned it

```gherkin
Given a Todo has kind="bug" and a diagnosis artifact written by its dispatched peer
When the driving prepare session runs "telec todo stamp my-slug --diagnosis-settled"
Then the stamp records the diagnosis artifact's current digest as the settled cause
And the prepare machine derives PLAN_DRAFTING on the next dispatch
And a later revision of the diagnosis leaves the stamp no longer current for the new digest
And the prepare machine derives DIAGNOSE again until the revised cause is settled
And a diagnosis-settled stamp on a Todo whose kind is not "bug" is refused before any write
And a diagnosis-settled stamp with no diagnosis artifact present is refused before any write
```

#### UC-WSS17: An unresolved diagnosis holds the todo and settles nothing

```gherkin
Given a Todo has kind="bug" whose diagnosis either grounds no causal mechanism, or leaves a causal transition unevidenced or the strongest rival still explaining the observations
When the driving prepare session runs "telec todo stamp my-slug --diagnosis-unresolved --reason '<why>'"
Then the stamp records hold=true and hold_audit with the diagnosis-unresolved source, the reason, and the caller session id
And no settled stamp is recorded, so the diagnosis is never consumed as a conclusion
And the held todo is not auto-re-dispatched to another diagnosis peer
And an unresolved stamp with an empty or missing reason is refused before any write
```

### Cross-context references

- `identity` — every stamp records the `caller_session_id`; downstream principal resolution turns that into the human or agent principal that authored the stamp, so audit trails name a responsible party.
- `agent_runtime` — worker sessions and work-orchestrator sessions invoke `telec todo stamp` at phase boundaries (`--build-complete`, `--finalize-ready`, `--verdict … --phase build_review`); the build-complete ownership check reads the caller's `working_slug` and `system_role` from the agent_runtime sessions table to accept either the owning worker or the work orchestrator.
- `workflow` — `/analyze-todo-input` assigns a kind-less Todo's kind autonomously through `--kind-assign`; there is no separate human approval stamp.

## Known caveats

- The stamp is the **natural worker-completion authority** for build and finalize phases. The state machine does not advance into review or integration until the stamp lands; conversely, the stamp does not run the gates itself — it records the claim and lets the state machine run gates on its next dispatch. This split prevents long-running stamp calls and the zombie processes a synchronous gate run would create.
- Kind assignment is **autonomous and one-shot**. `--kind-assign <kind>` fixes `kind` exactly once and moves the todo straight to that kind's `KIND_ENTRY_PHASE`; there is no proposal phase and no human approval stamp between classification and the lane. A Todo whose kind is already fixed refuses the stamp.
- No kind-assignment stamp writes a plan artifact. `--kind-assign task` records kind + entry phase only (routing to `task_plan_drafting`); `/next-prepare-task` authors the `task-plan`. SDLC assignments likewise record kind + entry phase only and let their normal lane author PRD/implementation artifacts.
- `--build-complete` is **worker- or orchestrator-owned and locked**: the caller must be either the owning worker (`working_slug == <slug>`) or a work orchestrator (`system_role == orchestrator`). Operators still cannot stamp build-complete from a plain shell; the stamp refuses with a permission error when the session id is missing or the caller is neither accepted shape.
- `--build-started` is **machine-owned**: the stamp rejects this flag explicitly and instructs the caller to run `telec todo work <slug>` so the work state machine owns the transition.

<!-- planned:fix-work-verdict-stamp-silent-noop -->

- A `--verdict ... --phase build_review` stamp is **phase-gated**: the work machine consumes a `build_review` verdict only at `lifecycle_phase == build_complete`, so a verdict stamped at any other phase is refused before any write rather than recorded to no effect — the refusal names the mismatch and points at reaching `build_complete` first. `--force` is the deliberate operator override: it records the verdict and sets `lifecycle_phase = build_complete` so the next `telec todo work` dispatch consumes it, and the command reports that the normal build-complete-first sequencing was bypassed. `--force` is meaningful only on this exact stamp shape; passed with any other stamp it is refused before any write. Prepare verdicts (`requirements_review`, `architecture_review`, `plan_review`) are unaffected — they are consumed by stateless re-derivation, not this one-shot phase-gated signal.

<!-- /planned:fix-work-verdict-stamp-silent-noop -->

- The approvals manager clears downstream approvals when an upstream artifact is re-opened. Refining the PRD invalidates the chain of architecture, plan, and finalize-ready approvals that depended on it — the state machine then re-runs the affected review and approval gates on next dispatch.
- The `--architecture-skipped` skip stamp **requires a non-empty reason**. The empty-reason variant is refused before any write.
- `--finalize-ready` requires the worktree to be in a finalize-ready state — the work-machine gates check for a clean worktree and present commits before honoring the handoff. A worker that stamps `--finalize-ready` from a dirty worktree will have the stamp recorded but the integrator dispatch will refuse to merge.
- Drift-reviewed verdicts are constrained to `{substantive, cosmetic}`. Any other verdict value is refused; the payload itself must carry well-formed `artifact`, `verdict`, and `reason` fields. The CLI signature `--drift-reviewed <artifact> <verdict> <reason>` is unchanged — the analyzer supplies the evidence anchor implicitly from current state at stamp time, not as a flag.
- Cosmetic drift-reviewed stamps are **anchor-scoped, not permanent**. The verdict expires lazily per drift class when current evidence has moved past the recorded anchor on any anchored dimension (HEAD/referenced-paths overlap, upstream digest, owned snippet digest, referenced snippet digest, dep-set). The class re-pends automatically on the next prepare or work-entry derivation; no manual stamp clearing is required. See `@spec/feature/workflow/drift-detection#stamp-scoping-the-evidence-anchor`.
- Rewriting a drift-tracked artifact (via `telec todo artifacts write`) clears all of its drift-reviewed stamps so the next derivation establishes a fresh anchor against newly captured provenance. Substantive verdicts never need explicit expiry — re-derivation is the path back to a fresh stamp.
- Bug-kind Todos still require the explicit `--build-complete` stamp before the work machine will advance past build — bypassing the stamp leaves the bug stuck in `build_started`. The build worker (`/next-build`) is responsible for issuing it as the last act of the build flow.
<!-- planned-change:kickback-fully-retracts-work-state -->
- `--kickback --reason <reason>` is **work-orchestrator-owned and locked**: only a session whose `system_role == orchestrator` may stamp it; a worker session or a plain operator shell is refused before any write. It is the authored counterpart to a substantive plan drift verdict — it appends the reason to `input` (creating `input` when the Todo has none, e.g. a `--plan` Todo) and invalidates the implementation-plan so the prepare machine re-derives from `plan_drafting`. The stamp mutates state only; on the orchestrator's next `telec todo work` re-entry the work machine releases the slug's working resources (worktree + local/remote branch + workspace dir, keeping the durable todo and artifacts) and emits the session-cleanup script (end workers, end self) — neither is done by the stamp.
<!-- change:kickback-fully-retracts-work-state -->
- `--kickback --reason <reason>` is **work-orchestrator-owned and locked**: only a session whose `system_role == orchestrator` may stamp it; a worker session or a plain operator shell is refused before any write. It is the authored counterpart to a substantive plan drift verdict, and it is the **complete, machine-owned retraction transition**, quiescence-first: it appends the reason to `input` (creating `input` when the Todo has none, e.g. a `--plan` Todo), ends the slug's live worker sessions and waits for them to drain (refusing before any destructive step when a worker cannot be drained), releases the slug's working resources (worktree + local/remote branch + workspace dir, keeping the durable todo and artifacts), then invalidates the implementation-plan, clears the work-phase state (build-started base sha, build-complete claim, build-review state, finalize handoff) so the Todo lands at `plan_drafting`, and releases the runner claim (`active_runner` plus the claiming session's `working_slug` binding) as the final step — the held claim is what keeps a fresh dispatch from racing the cleanup. The stamp response carries the caller's remaining wind-down instruction (end self, no `telec todo work` re-entry). A kickback stamped at `finalize_ready` retracts the finalize handoff with the rest of the work state; the integration candidate scan's held-or-kicked-back gate remains as the backstop for a candidate already scanned. The work machine's kickback branch remains as a backstop that emits the wind-down script and repairs residue from kickbacks stamped before the retraction moved into the stamp.
<!-- /planned-change:kickback-fully-retracts-work-state -->

- `--task-outcome <success|error>` is the **durable firing-outcome** stamp for a
  `kind="task"` Todo, reconciled by the lifecycle runner into a terminal state. A
  one-shot `success` delivers the Todo; a recurring `success` clears a task-error hold
  and leaves the Todo live; `error` holds the Todo with the task-error hold source and
  the reason. The stamp transitions terminal state synchronously and adds no new state
  field. `error` **requires a non-empty reason**, and a task-outcome stamp on a non-task
  Todo is refused before any write. A task-error hold has **no bare-unhold recovery**:
  `telec todo update --release` refuses to clear it, so recovery is `--task-outcome
success` (which delivers) or a deliberate manual start; a firing that ends without a
  stamp leaves the Todo re-runnable.
