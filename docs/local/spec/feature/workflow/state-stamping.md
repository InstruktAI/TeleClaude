---
description: 'The `telec todo stamp` command and the validated state-write boundary it goes through — approvals, review verdicts, skip stamps, drift-reviewed acknowledgments, build-complete and finalize-ready handoffs.'
visibility: 'public'
---

# State Stamping — Spec

## What it is

`telec todo stamp` is the single domain surface every caller — human operator, Worker session, or Orchestrator — uses to record a fact about a Todo: a reviewer's Verdict, a human PRD approval, an architecture skip with reason, a drift-reviewed acknowledgment, a worker's `build_complete` claim, or a worker's `finalize_ready` handoff. Every stamp routes through a single validated state-write boundary: the workflow service re-validates the full Todo state against its typed model before any commit, and the approvals and review managers are the typed owners for approval-shaped and verdict-shaped mutations. When full-state validation fails, the caller receives the underlying validation text, and no partial mutation is persisted. The stamp records the fact; the state machine reads the fact on its next dispatch and advances the canonical `lifecycle_phase` accordingly. There is no path that writes Todo state outside this boundary.

A one-shot task-outcome success reconciles lifecycle markers only in the task's own project; it does not read or change another project's documentation. A code-review record retains the reviewed commit, verdict, reviewer identity, and supplied reason. It is also recorded on the Todo claimed by the stamping session, or by its initiating session when the reviewer has no claim; if neither has a claim, no Todo review state is written.

The same state-write boundary owns artifact-write provenance capture. On every `telec todo artifacts write` for a drift-tracked artifact (`input`, `prd`, `architecture`, `implementation-plan`), the workflow's provenance boundary records the evidence needed for every drift class applicable to that artifact. Existing persisted fields: `codebase_sha_at_write` (captured via the origin-main-sha helper — never local HEAD) and `referenced_paths`, plus `upstream_digests` (the persisted-state field, aka `upstream_artifact_digests` in spec/documentation). Added persisted fields: `owned_snippet_digests`, `referenced_snippet_digests`, `produced_at`, and, for the `implementation-plan` only, `dependency_artifact_digests` — pure additive defaults with no migration. See `@spec/feature/workflow/drift-detection` for the per-class semantics. Rewriting an artifact re-captures all provenance fields at the new write and clears every drift-reviewed stamp for that artifact so the next derivation starts from a fresh anchor.

## Canonical fields

### Use cases

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

#### UC-WSS20: Retired requirements review cannot create a live verdict

```gherkin
Given historical requirements and requirements-review-findings artifacts remain readable but retired from writes
When a caller attempts to stamp a verdict with phase requirements_review
Then the verdict surface refuses the phase before any state mutation
And legacy import never synthesizes requirements_review or plan_review approval from artifact presence
And delivered historical records remain unchanged and readable
```

```
Given a Todo whose nature does not require architecture work
When an operator runs "telec todo stamp my-slug --architecture-skipped 'no architectural surface to design'"
Then the approvals manager records a skip stamp with the reason, timestamp, and caller_session_id
And the empty-reason variant is rejected before any write
And the prepare chain advances past the architecture phase on next dispatch
```

#### UC-WSS10: Accepted human approval resumes preparation through one workflow path

```gherkin
Given a Todo is parked at a human-approval gate
And the human approves through an interaction surface, or the agent the human addressed records the approval
And only the human's approval carries human-approval authority
When workflow accepts the approval command
Then it records the approval and initiates continuation as one domain outcome
And preparation continues from the approved fact without another human action
And conversation, user-interface controls, the command line, and future adapters produce that same outcome
And every receiving agent trusts the recorded approval without provenance investigation
And the involvement record keeps the recording session auditable rather than verified at runtime
But an agent's own judgment cannot enter this human-approval command
And an approval carrying only agent judgment delivers no notification into any session
And the agent never messages itself about an approval it recorded
```

#### UC-WSS9: Human task authorization stamps execution approval

```gherkin
Given a Todo has kind="task", lifecycle_phase="prepared", and a current `task-plan` artifact
When a human authorizes the task from the TUI or runs `telec todo stamp my-slug --task-approved`
Then workflow records a task authorization stamp with caller_session_id, approved_at, and approved_digest set to the current `task-plan` digest
And the state-write boundary re-validates the full Todo state before commit
And workflow emits the todo-updated event so the lifecycle runner re-evaluates task eligibility
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
Then the lifecycle runner treats the task as unauthorized and does not dispatch `sdlc/procedure/lifecycle/task/run-task`
And the task stays unauthorized until a fresh `task_approved` stamp re-binds `approved_digest` to the current `task-plan`
```

```
Given an approved prepare artifact whose per-class drift derivation collapses to "pending" on any class enumerated in @spec/feature/workflow/drift-detection
When the sdlc/procedure/lifecycle/prepare/drift-analyze worker runs "telec todo stamp my-slug --drift-reviewed prd cosmetic 'rename-only refactor, intent preserved'"
Then the drift-reviewed handler parses the (artifact, verdict, reason) triple
And the approvals manager validates verdict is one of {substantive, cosmetic}
And persists the drift-reviewed stamp under approvals.drift_reviewed[artifact] including the evidence anchor at stamp time (head_sha_at_review, upstream_digests_at_review, snippet_digests_at_review)
And the prepare gate stops treating the drift as blocking on next read for as long as current evidence has not moved past the anchor on any dimension
And when later evidence moves past the anchor (HEAD advances with new referenced-path overlap, OR upstream digest changes, OR snippet digest changes), the cosmetic verdict is treated as expired-for-class and the class re-pends automatically — no manual stamp clearing required
```

```
Given the same artifact at "pending" drift status
When the sdlc/procedure/lifecycle/prepare/drift-analyze worker runs "telec todo stamp my-slug --drift-reviewed architecture substantive 'upstream PRD rewrote success criteria; design must re-derive'"
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
And the worktree-commits check confirms the worktree has commits beyond main that change files (refused otherwise; a commit that changes no file does not count)
And build_gate_claim_at is set to the current timestamp and persisted through the state-write boundary
And the work machine runs the build-complete gates on its next dispatch
```

#### UC-WSS11: Work orchestrator kicks an unbuildable todo back to plan drafting and the lifecycle runner re-prepares it

```gherkin
Given a Todo at a work phase whose implementation-plan cannot be executed as written
And a work-orchestrator session bound to that Todo
When the orchestrator runs "telec todo stamp my-slug --kickback --reason '<why the plan cannot be built>'"
Then the kickback ownership check accepts the caller because it is a work-orchestrator session whose claim binds the slug
And a worker session, a plain operator shell, a missing session id, or an orchestrator bound to a different slug is refused before any write
And the stamp creates the input artifact when the Todo has none or appends a delimited kickback block carrying the reason to the existing input
And the stamp clears the implementation-plan review verdict and marks it cleared-by-substantive-drift, the same invalidation a substantive plan drift verdict produces
And the stamp clears any outstanding build-complete gate claim and resets a ready finalize handoff to pending
And the Todo's worktree, branches, workspace directory, and build commits are left untouched
And the state-write boundary re-validates the full state and persists atomically
And once the reason is durable the stamp releases the Todo's lifecycle claim
And the platform ends every session the stamping orchestrator started, then the stamping orchestrator itself, only after the stamp has answered its call and without any agent ending them
And the lifecycle runner dispatches a fresh prepare orchestrator, whose planner reads the input kickback block as authoritative re-derivation context
And no human is notified
```

```
Given a worker has produced a clean worktree ready for integration
When the worker runs "telec todo stamp my-slug --finalize-ready"
Then the finalize-ready handler records the finalize stamp with status="ready", the worktree HEAD as candidate sha, and caller_session_id
And the integrator dispatch consumes the finalize-ready handoff to merge the candidate into main
```

#### UC-WSS12: One-shot task success outcome delivers the todo

#### UC-WSS13: Recurring task success outcome clears an error-hold and stays live

#### UC-WSS14: Task error outcome holds the todo with its reason

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

#### UC-WSS23: Task success delivers within the todo's own project

#### UC-WSS24: A commit-review stamp lands on the todo its session chain claims

### Cross-context references

- `identity` — every stamp records the `caller_session_id`; downstream principal resolution turns that into the human or agent principal that authored the stamp, so audit trails name a responsible party.

- `agent_runtime` — worker sessions and work-orchestrator sessions invoke `telec todo stamp` at phase boundaries (`--build-complete`, `--finalize-ready`, `--verdict … --phase build_review`); the build-complete ownership check reads the caller's `working_slug` and `system_role` from the agent_runtime sessions table to accept either the owning worker or the work orchestrator.

## Known caveats

- The stamp is the **natural worker-completion authority** for build and finalize phases. The state machine does not advance into review or integration until the stamp lands; conversely, the stamp does not run the gates itself — it records the claim and lets the state machine run gates on its next dispatch. This split prevents long-running stamp calls and the zombie processes a synchronous gate run would create.
- `--build-complete` is **worker- or orchestrator-owned and locked**: the caller must be either the owning worker (`working_slug == <slug>`) or a work orchestrator (`system_role == orchestrator`). Operators still cannot stamp build-complete from a plain shell; the stamp refuses with a permission error when the session id is missing or the caller is neither accepted shape.

- `--build-started` is **machine-owned**: the stamp rejects this flag explicitly and instructs the caller to run `telec todo work <slug>` so the work state machine owns the transition.

- The approvals manager clears downstream approvals when an upstream artifact is re-opened. Refining the PRD invalidates the chain of architecture, plan, and finalize-ready approvals that depended on it — the state machine then re-runs the affected review and approval gates on next dispatch.
- The `--architecture-skipped` skip stamp **requires a non-empty reason**. The empty-reason variant is refused before any write.
- `--finalize-ready` requires the worktree to be in a finalize-ready state — the work-machine gates check for a clean worktree and present commits before honoring the handoff. A worker that stamps `--finalize-ready` from a dirty worktree will have the stamp recorded but the integrator dispatch will refuse to merge.
- Drift-reviewed verdicts are constrained to `{substantive, cosmetic}`. Any other verdict value is refused; the payload itself must carry well-formed `artifact`, `verdict`, and `reason` fields. The CLI signature `--drift-reviewed <artifact> <verdict> <reason>` is unchanged — the analyzer supplies the evidence anchor implicitly from current state at stamp time, not as a flag.
- Cosmetic drift-reviewed stamps are **anchor-scoped, not permanent**. The verdict expires lazily per drift class when current evidence has moved past the recorded anchor on any anchored dimension (HEAD/referenced-paths overlap, upstream digest, owned snippet digest, referenced snippet digest, dep-set). The class re-pends automatically on the next prepare or work-entry derivation; no manual stamp clearing is required. See `@spec/feature/workflow/drift-detection#stamp-scoping-the-evidence-anchor`.
- Rewriting a drift-tracked artifact (via `telec todo artifacts write`) clears all of its drift-reviewed stamps so the next derivation establishes a fresh anchor against newly captured provenance. Substantive verdicts never need explicit expiry — re-derivation is the path back to a fresh stamp.
- Bug-kind Todos still require the explicit `--build-complete` stamp before the work machine will advance past build — bypassing the stamp leaves the bug stuck in `build_started`. The build worker (`/sdlc/build`) is responsible for issuing it as the last act of the build flow.
- `--kickback --reason <reason>` is **work-orchestrator-owned and locked**: only a work-orchestrator session whose claim binds the slug may stamp it; a worker session, a plain operator shell, or an orchestrator bound to a different slug is refused before any write. It is the authored counterpart to a substantive plan drift verdict — it appends the reason to `input` (creating `input` when the Todo has none, e.g. a `--plan` Todo), invalidates the implementation-plan so the prepare machine re-derives from `plan_drafting`, clears any outstanding build-complete gate claim, and resets a ready finalize handoff to pending. The worktree, local and remote branch, workspace directory, and build commits are preserved. Once the reason is durable, the stamp releases the Todo's lifecycle claim and the platform ends the slug's work-lane sessions — every session the stamping orchestrator started, then the orchestrator itself, only after the stamp has answered its call; no agent ends them and no human is notified. The lifecycle runner dispatches a fresh prepare orchestrator; after the plan is re-derived and re-approved, that orchestrator ends and the lifecycle runner dispatches a fresh work orchestrator, which re-enters the preserved build and hands the builder machine-derived reconcile instructions naming the old and new implementation-plan digests.

- `--task-outcome <success|error>` is the **durable firing-outcome** stamp for a
  `kind="task"` Todo, reconciled by the lifecycle runner into a terminal state. A
  one-shot `success` delivers the Todo; a recurring `success` clears only a task-error
  hold and leaves any other hold, including a human-pause hold, intact while keeping
  the Todo live; `error` holds the Todo with the task-error hold source and
  the reason. The stamp transitions terminal state synchronously and adds no new state
  field. `error` **requires a non-empty reason**, and a task-outcome stamp on a non-task
  Todo is refused before any write. A task-error hold has **no bare-unhold recovery**:
  `telec todo update --release` refuses to clear it, so recovery is `--task-outcome
success` (which delivers) or a deliberate manual start; a firing that ends without a
  stamp leaves the Todo re-runnable.

<!-- planned:task-firing-timestamp-line -->

- `--task-firing-started` is the **firing-start** stamp for a `kind="task"` Todo,
  stamped by the session running the firing before it reads the Todo's `log`. The
  stamp boundary takes the instant from the system clock, appends that firing's
  line to the end of the `log`
  (`local/projects/teleclaude/spec/feature/workflow/work-state-machine`), and
  records a firing-start audit event naming the stamping session. A session that
  already stamped a firing start on the Todo is answered with the current state
  and nothing is appended. The stamp requires a TeleClaude session that owns the
  Todo's claim or binding, and a firing-start stamp on a non-task Todo is refused
  before any write. A failed stamp writes no event and reports its error to the
  caller.

<!-- /planned:task-firing-timestamp-line -->
