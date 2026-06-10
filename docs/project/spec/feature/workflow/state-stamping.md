---
description: 'The `telec todo stamp` command and the validated state-write boundary it goes through — kind assignment, approvals, review verdicts, skip stamps, drift-reviewed acknowledgments, build-complete and finalize-ready handoffs.'
visibility: 'public'
---

# State Stamping — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

`telec todo stamp` is the single domain surface every caller — human operator, Worker session, or Orchestrator — uses to record a fact about a Todo: an analyzer's kind assignment, a reviewer's Verdict, a human PRD approval, an architecture skip with reason, a drift-reviewed acknowledgment, a worker's `build_complete` claim, or a worker's `finalize_ready` handoff. Every stamp routes through a single validated state-write boundary: the workflow service re-validates the full Todo state against its typed model before any commit, and the kind-assignment, approvals, and review managers are the typed owners for kind-shaped, approval-shaped, and verdict-shaped mutations. The stamp records the fact; the state machine reads the fact on its next dispatch and advances the canonical `lifecycle_phase` accordingly. There is no path that writes Todo state outside this boundary.

The same state-write boundary owns artifact-write provenance capture. On every `telec todo artifacts write` for a drift-tracked artifact (`input`, `prd`, `architecture`, `implementation-plan`), the workflow's provenance boundary records the evidence needed for every drift class applicable to that artifact. Existing persisted fields: `codebase_sha_at_write` (captured via the origin-main-sha helper — never local HEAD) and `referenced_paths`, plus `upstream_digests` (the persisted-state field, aka `upstream_artifact_digests` in spec/documentation). Added persisted fields: `owned_snippet_digests`, `referenced_snippet_digests`, `dependency_set_at_write`, and `produced_at` — pure additive defaults with no migration. See `@spec/feature/workflow/drift-detection` for the per-class semantics. Rewriting an artifact re-captures all provenance fields at the new write and clears every drift-reviewed stamp for that artifact so the next derivation starts from a fresh anchor.

## Canonical fields

### Use cases

#### UC-WSS1: Task kind assignment writes a task plan and enters prepared

```
Given a kind-less Todo whose kind is unset, whose lifecycle_phase is absent, and whose input artifact holds the raw dump
When the analyzer runs "telec todo stamp my-slug --kind-assign task '<task-plan content>'"
Then the kind-assignment handler validates the todo is still kind-less and the assigned kind is canonical
And it fixes kind="task" exactly once, writes the task-plan artifact from the supplied content
And it sets lifecycle_phase=KIND_ENTRY_PHASE["task"] ("prepared")
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

```
Given a reviewer worker has read the implementation plan
When the worker runs "telec todo stamp my-slug --verdict approve --phase plan_review"
Then the verdict-stamp validation checks the phase is in the allowed verdict-phase set and the verdict is in the allowed value set
And the review manager writes verdict + reviewed_at to both the visible review state and the matching audit entry
And when verdict == "approve" the implementation_plan artifact digest is recorded as approved_digest
And the next prepare-machine dispatch observes the verdict and advances lifecycle_phase
```

```
Given a Todo whose nature does not require architecture work
When an operator runs "telec todo stamp my-slug --architecture-skipped 'no architectural surface to design'"
Then the approvals manager records a skip stamp with the reason, timestamp, and caller_session_id
And the empty-reason variant is rejected before any write
And the prepare chain advances past the architecture phase on next dispatch
```

```
Given an approved prepare artifact whose per-class drift derivation collapses to "pending" on any class enumerated in @spec/feature/workflow/drift-detection
When the next-drift-analyze worker runs "telec todo stamp my-slug --drift-reviewed prd cosmetic 'rename-only refactor, intent preserved'"
Then the drift-reviewed handler parses the (artifact, verdict, reason) triple
And the approvals manager validates verdict is one of {substantive, cosmetic}
And persists the drift-reviewed stamp under approvals.drift_reviewed[artifact] including the evidence anchor at stamp time (head_sha_at_review, upstream_digests_at_review, snippet_digests_at_review, dep_set_at_review)
And the prepare gate stops treating the drift as blocking on next read for as long as current evidence has not moved past the anchor on any dimension
And when later evidence moves past the anchor (HEAD advances with new referenced-path overlap, OR upstream digest changes, OR snippet digest changes, OR dep-set changes), the cosmetic verdict is treated as expired-for-class and the class re-pends automatically — no manual stamp clearing required
```

```
Given the same artifact at "pending" drift status
When the next-drift-analyze worker runs "telec todo stamp my-slug --drift-reviewed architecture substantive 'upstream PRD rewrote success criteria; design must re-derive'"
Then the substantive drift-reviewed stamp is persisted with the same evidence-anchor fields recorded for audit
And the approvals manager clears the architecture review verdict and every downstream review verdict (plan in this case) as part of the same commit
And the prepare state machine routes back to architecture_drafting on next dispatch
And the substantive stamp does not need lazy expiry — re-derivation produces a fresh artifact whose write clears the drift stamps and re-captures provenance
```

```
Given a worker session whose durable working_slug matches the Todo and whose lifecycle_phase is build_started
When the worker runs "telec todo stamp my-slug --build-complete"
Then the build-complete ownership check confirms the caller session owns working_slug == my-slug (permission denied otherwise)
And the build-complete handler confirms the current phase is build_started or review_changes_requested (refused otherwise)
And the worktree-commits check confirms the worktree has commits beyond main (refused otherwise)
And build_gate_claim_at is set to the current timestamp and persisted through the state-write boundary
And the work machine runs the build-complete gates on its next dispatch
```

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

### Cross-context references

- `identity` — every stamp records the `caller_session_id`; downstream principal resolution turns that into the human or agent principal that authored the stamp, so audit trails name a responsible party.
- `agent_runtime` — worker sessions invoke `telec todo stamp` at phase boundaries (`--build-complete`, `--finalize-ready`, `--verdict … --phase build_review`); the build-complete ownership check reads the session's `working_slug` from the agent_runtime sessions table to enforce ownership.
- `workflow` — `/analyze-todo-input` assigns a kind-less Todo's kind autonomously through `--kind-assign`; there is no separate human approval stamp.

## Known caveats

- The stamp is the **natural worker-completion authority** for build and finalize phases. The state machine does not advance into review or integration until the stamp lands; conversely, the stamp does not run the gates itself — it records the claim and lets the state machine run gates on its next dispatch. This split prevents long-running stamp calls and the zombie processes a synchronous gate run would create.
- Kind assignment is **autonomous and one-shot**. `--kind-assign <kind>` fixes `kind` exactly once and moves the todo straight to that kind's `KIND_ENTRY_PHASE`; there is no proposal phase and no human approval stamp between classification and the lane. A Todo whose kind is already fixed refuses the stamp.
- `--kind-assign task` is the only kind-assignment stamp that writes `task-plan`. SDLC assignments record kind + entry phase only and let their normal lane author PRD/implementation artifacts.
- `--build-complete` is **worker-owned and locked**: the caller's session must own `working_slug == <slug>`. Operators cannot stamp build-complete from a plain shell; the stamp refuses with a permission error when the session id is missing or the working_slug does not match.
- `--build-started` is **machine-owned**: the stamp rejects this flag explicitly and instructs the caller to run `telec todo work <slug>` so the work state machine owns the transition.
- The approvals manager clears downstream approvals when an upstream artifact is re-opened. Refining the PRD invalidates the chain of architecture, plan, and finalize-ready approvals that depended on it — the state machine then re-runs the affected review and approval gates on next dispatch.
- The `--architecture-skipped` skip stamp **requires a non-empty reason**. The empty-reason variant is refused before any write.
- `--finalize-ready` requires the worktree to be in a finalize-ready state — the work-machine gates check for a clean worktree and present commits before honoring the handoff. A worker that stamps `--finalize-ready` from a dirty worktree will have the stamp recorded but the integrator dispatch will refuse to merge.
- Drift-reviewed verdicts are constrained to `{substantive, cosmetic}`. Any other verdict value is refused; the payload itself must carry well-formed `artifact`, `verdict`, and `reason` fields. The CLI signature `--drift-reviewed <artifact> <verdict> <reason>` is unchanged — the analyzer supplies the evidence anchor implicitly from current state at stamp time, not as a flag.
- Cosmetic drift-reviewed stamps are **anchor-scoped, not permanent**. The verdict expires lazily per drift class when current evidence has moved past the recorded anchor on any anchored dimension (HEAD/referenced-paths overlap, upstream digest, owned snippet digest, referenced snippet digest, dep-set). The class re-pends automatically on the next prepare or work-entry derivation; no manual stamp clearing is required. See `@spec/feature/workflow/drift-detection#stamp-scoping-the-evidence-anchor`.
- Rewriting a drift-tracked artifact (via `telec todo artifacts write`) clears all of its drift-reviewed stamps so the next derivation establishes a fresh anchor against newly captured provenance. Substantive verdicts never need explicit expiry — re-derivation is the path back to a fresh stamp.
- Bug-kind Todos still require the explicit `--build-complete` stamp before the work machine will advance past build — bypassing the stamp leaves the bug stuck in `build_started`. The build worker (`/next-build`) is responsible for issuing it as the last act of the build flow.
