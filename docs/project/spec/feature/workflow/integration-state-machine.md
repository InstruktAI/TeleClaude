---
description: 'Singleton, lease-serialized, durable-checkpoint state machine that squash-merges finalize-ready todos into origin/main from an isolated integration worktree.'
visibility: 'public'
---

# Integration State Machine — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The integration state machine is Phase C of the todo lifecycle — the only authorized writer of canonical `origin/main`. It runs as a singleton (one active integrator per project, enforced by a lease keyed on `integration/main`) and consumes finalize-ready Todos in FIFO order. Each call resumes from a durable checkpoint, executes the next deterministic step, and either loops internally or returns a structured instruction block that asks the calling agent to do the one thing only intelligence can do: compose a squash commit message, resolve a merge conflict, or recover from a rejected push. All git mutations happen inside an isolated integration worktree at `trees/_integration/`, never on repo root, so a dirty or diverged repo root never blocks delivery. When the queue drains, the integrator emits `workflow.todo.delivered` per slug, removes per-slug worktrees and branches, archives binary artifacts, and ends.

## Canonical fields

### Use cases

```
Given the integrator is idle with no active candidate
And one or more worktrees report finalize.status of "ready"
When the operator runs "telec todo integrate"
Then the integrator sweeps already-delivered worktrees, acquires the singleton lease,
And dequeues the FIFO-earliest candidate by (ready_at, slug)
And ensures the persistent integration worktree at "trees/_integration/" is synced to origin/main
And performs a squash merge of the candidate branch
And emits integration.started, integration.candidate.dequeued, and integration.merge.succeeded
```

```
Given the squash merge applied cleanly in the integration worktree
When the state machine writes the clean-merge phase to its checkpoint
Then it returns an AWAITING_COMMIT instruction containing diff stats, branch log, requirements and implementation plan
And the calling agent composes the squash commit message and creates the commit inside the integration worktree
And the next "telec todo integrate" call detects HEAD advanced past the pre-merge head
And the checkpoint advances to COMMITTED, then to delivery bookkeeping in the same loop iteration
```

```
Given the squash merge produced conflicts
When the state machine writes MERGE_CONFLICTED with the list of conflicted files
Then it returns a structured conflict-resolution instruction listing those files
And the calling agent resolves the conflicts and commits inside the integration worktree
And the next call observes the merge state cleared and HEAD advanced and advances to COMMITTED
And emits integration.merge.conflicted at the original conflict and integration.candidate.committed on resolution
```

```
Given the candidate SHA is already an ancestor of HEAD on origin/main (stale re-queue after restart)
Or the squash merge produced an empty staged diff (squash of already-integrated commits)
When the merge step runs
Then the candidate skips merge and commit entirely
And the checkpoint advances to CANDIDATE_DELIVERED
And integration.candidate.already_merged is emitted
And any leftover squash-merge bookkeeping is cleaned up
```

```
Given the squash commit is committed in the integration worktree
When the push to main is rejected because the remote moved (a non-fast-forward race)
Then the state machine writes PUSH_REJECTED with the rejection reason classified as a fast-forward race
And returns an instruction asking the agent to rebase onto origin/main and push from the integration worktree, each command directory-qualified to that worktree
And the next call computes local HEAD vs remote main; if they match, recovery is detected and phase advances to PUSH_SUCCEEDED
And integration.push.rejected is emitted at rejection and integration.push.succeeded on recovery
```

<!-- planned-change:integration-gate-scope-and-conflict-path -->

Push rejection is classified by cause. A rejection whose output carries the pre-push
content-gate marker (`telec code lint --all` failed on the squash content) is a
content-gate rejection, which a rebase cannot resolve because the squash content is
unchanged by rebasing; it routes to the abandon path (UC-WISM5), not to rebase
recovery. Every other rejection is treated as a fast-forward race, recoverable by the
rebase-and-re-push instruction above.
<!-- change:integration-gate-scope-and-conflict-path -->

Push rejection is classified by cause. A rejection whose output carries the pre-push
content-gate marker (`telec code lint --all` failed on the squash content) is a
content-gate rejection; it routes to the logical-conflict path (UC-WISM5), never to
rebase recovery. Every other rejection is treated as a fast-forward race, recoverable
by the rebase-and-re-push instruction above.
<!-- /planned-change:integration-gate-scope-and-conflict-path -->

#### UC-WISM1: Integrator-maintenance marker emission at delivery

```gherkin
Given the push to main succeeded and the integrator best-effort sync advanced repo-root main
When the PUSH_SUCCEEDED step runs, before the per-candidate pre_merge_head is cleared at CANDIDATE_DELIVERED
Then the state machine records a session-scoped integrator-maintenance marker for the integrator session
And the marker carries the delivered merge range (pre_merge_head..advanced repo-root HEAD)
And the agent-stop checkpoint engine consumes that marker to force-fire post-merge maintenance for the integrator
```

#### UC-WISM2: Delivery recorded only on confirmed push

```gherkin
Given a candidate is squash-merged and committed in the integration worktree
When the push to origin/main is rejected
Then no delivery record is written and the todo status stays non-delivered
And the phase is PUSH_REJECTED

Given the push to origin/main is rejected and the operator recovers so the worktree HEAD matches origin/main
When the PUSH_SUCCEEDED step confirms the candidate's own squash content is present on origin/main
Then the delivery record is written exactly once
And the recorded delivered commit is the integration-worktree HEAD that landed on origin/main

Given the push reports success but the candidate's squash content is not present on origin/main
When the PUSH_SUCCEEDED confirmation gate runs its containment check
Then no delivery record is written and the candidate returns to PUSH_REJECTED

Given the integration worktree HEAD was reset to origin/main so no squash commit carrying the candidate's content remains
When the PUSH_SUCCEEDED confirmation gate runs its containment check
Then the candidate's content is absent from origin/main and no delivery record is written
And a candidate is never recorded delivered against an origin/main HEAD that does not contain its content
```

The confirmation gate verifies **candidate-content containment** — that the candidate's
own squash content reached origin/main — not merely that the integration-worktree HEAD is
an ancestor of origin/main. A worktree reset to origin/main makes the worktree HEAD
trivially an ancestor of origin/main while dropping the candidate's squash, so an
ancestry-only check would false-deliver; the containment check closes that gap.

#### UC-WISM3: Delivered-snippet fold re-asserted across every delivery path

```gherkin
Given a candidate is committed in the integration worktree via any path — clean merge, conflict resolution, or crash-resume
When the state machine reaches delivery bookkeeping before pushing to origin/main
Then it runs the idempotent delivered-snippet fold for the candidate slug
And the fold is a no-op when an earlier path already folded the slug's snippets
And any companion swap, planned-marker strip, or delivered_by clearance the fold produces is staged and committed into the delivery before the push

Given the delivered-snippet fold staged changes but staging or the cleanup commit carrying them into the delivery fails
When the delivery-bookkeeping step checks the staging and commit results before the push
Then the push to origin/main does not happen
And the candidate stays at delivery bookkeeping with an error naming the slug
And no delivery record is written
```

#### UC-WISM4: Pre-push residual-marker gate fails closed

```gherkin
Given the delivered slug's snippets would still carry a planned-change or planned marker for that slug after the fold
When the delivery-bookkeeping residual-marker gate runs before the push
Then the push to origin/main does not happen
And the candidate stays at delivery bookkeeping with a residual-marker error naming the file, line, and slug
And a delivered slug never reaches origin/main carrying its own live markers
```

<!-- planned-change:integration-gate-scope-and-conflict-path -->

#### UC-WISM5: Content-gate rejection abandons the candidate without freezing the queue

```gherkin
Given a candidate's squash is pushed and the push is rejected by the pre-push content gate (telec code lint --all failed on the squash content)
When the state machine classifies the rejection as a content-gate rejection
Then the candidate is abandoned rather than parked in a rebase-recovery loop
And the integration worktree is reset to origin/main so the bad squash is dropped
And the candidate is retracted from the integration pool so it is not re-dequeued
And integration.candidate.blocked is emitted carrying the slug and the content-gate reason
And the blocked-candidate counter is incremented
And the checkpoint returns to IDLE and the integrator continues draining the remaining finalize-ready candidates
And no delivery record is written for the abandoned candidate
```

<!-- change:integration-gate-scope-and-conflict-path -->

#### UC-WISM5: Content-gate rejection is a logical merge conflict — resolved by the integrator, never abandoned

```gherkin
Given a candidate's squash is pushed and the push is rejected by the pre-push content gate (telec code lint --all failed on the squash content)
When the state machine classifies the rejection from the content-gate marker
Then the candidate does not enter rebase recovery
And the integrator owns the conflict — no upstream owner exists once a candidate is in the integration pipeline
And the integrator treats the rejection as a logical merge conflict on a repo-wide invariant, in the same class as a textual merge conflict
And a mechanically groundable conflict is resolved by the integrator in the integration worktree — for a double-bound scenario it reads both tests and drops the redundant binding when they observe the same behavior, or authors the distinct scenario and retags when they are genuinely distinct — writing into live contract body only, never inside a pending planned-change region
And a conflict the integrator cannot ground confidently leaves it stopped on the candidate, escalated to the human as a beacon
And integration.candidate.blocked is emitted carrying the slug and the content-gate reason
And no later candidate is dequeued while the conflict stands unresolved
And no delivery record is written for the candidate until its own squash content is confirmed on origin/main
```

<!-- /planned-change:integration-gate-scope-and-conflict-path -->

#### UC-WISM6: Held or kicked-back candidates are excluded from the integration pool

```gherkin
Given a finalize-ready candidate is held or its plan review was cleared by a kickback
When the idle step scans for finalize-ready candidates
Then that candidate is excluded from the integration pool despite finalize.status being "ready"
And a human kickback or hold pulls a candidate out of integration without waiting for it to be dequeued
```

```
Given another integrator session holds the integration/main lease and the TTL has not elapsed
When the operator runs "telec todo integrate"
Then the idle step reports lease busy with the holder session id and returns immediately without touching git
And no integration lifecycle events are emitted for this call
```

```
Given the integrator was killed mid-flight at any phase
When a fresh "telec todo integrate" is invoked
Then the durable checkpoint is read on entry
And the dispatcher resumes from the same phase the prior run was in
And idempotency guards (ancestry check, empty-squash check, head-advanced check, HEAD-vs-remote check) prevent double-merge or double-commit
```

```
Given repo root main is dirty when the dispatcher runs the autostash-aware pull
And the autostash pop fails after the pull, leaving an orphaned stash entry
When the integrator detects the stash count increased between entry and post-pull
Then it returns a formatted "repo_root_diverged" or "autostash_orphaned" instruction
And no candidate is dequeued for this call
```

#### UC-WISM7: Explicit-slug integration excludes a held or kicked-back candidate

```gherkin
Given a held or kicked-back candidate whose finalize.status is "ready"
When "telec todo integrate" is invoked with that candidate's explicit slug
Then the candidate is excluded from integration — no candidate is dequeued, the checkpoint stays IDLE with items_processed zero, and its branch is never squash-merged
```

#### UC-WISM8: Integrator-maintenance marker accumulates ranges across multiple deliveries

```gherkin
Given several candidates are delivered in a single integration drain
When each PUSH_SUCCEEDED step records its delivered merge range into the session-scoped integrator-maintenance marker
Then the marker accumulates the union of the delivered ranges across candidates rather than overwriting the prior range
```

<!-- planned:integration-gate-scope-and-conflict-path -->

#### UC-WISM9: Integration validates with repo-wide gate semantics

```gherkin
Given a candidate is squash-merged and the integrator commits in the integration worktree
When the integration commit runs its quality gate
Then the format-fix step still runs over the squash content before the commit
And the gating checks carry repo-wide semantics — scope-sensitive checks that are only meaningful over the whole repository (duplication percentage) never gate the integration commit
And the pre-push telec code lint --all remains the single authoritative content gate
```

<!-- /planned:integration-gate-scope-and-conflict-path -->

<!-- planned:runner-not-project-aware -->

#### UC-WISM10: Checkpoint and lease are per-project; a foreign candidate never resumes

```gherkin
Given the durable checkpoint and lease live under the current project's resolved state root at ".teleclaude/integration/"
And project A's integrator has left a non-IDLE checkpoint naming candidate A
When "telec todo integrate" runs in project B
Then project B reads its own project-scoped checkpoint rather than project A's
And project B neither resumes candidate A nor squash-merges A's branch in project B's integration worktree
```

#### UC-WISM11: A checkpoint candidate absent from the current project resets to idle instead of wedging

```gherkin
Given a durable checkpoint is non-IDLE and names a candidate whose branch and "trees/<slug>" worktree are both absent in the current project
When the dispatcher reads that checkpoint on entry
Then the checkpoint is reset to IDLE with the candidate identity cleared
And the idle step re-scans this project's finalize-ready candidates instead of returning SQUASH COMMIT REQUIRED for the absent candidate
```

<!-- /planned:runner-not-project-aware -->

### Cross-context references

- `agent_runtime` — receives fire-and-forget lifecycle events: `integration.started`, `integration.candidate.dequeued`, `integration.candidate.already_merged`, `integration.merge.succeeded`, `integration.merge.conflicted`, `integration.candidate.committed`, `integration.push.succeeded`, `integration.push.rejected`, `integration.candidate.delivered`, `integration.candidate.blocked`.
- `workflow` — delivery bookkeeping records the delivery commit; `workflow.todo.delivered` is emitted by the workflow context after push succeeds.
- `operations` — `telec todo integrate` returns an operation receipt; the integrator runs inside the operation runner so failures surface through operation status.

- `workflow.lifecycle_runner` — observes workflow wake-up events only to
  re-evaluate prepare/work candidates and downstream dependencies. It does not
  spawn or inline the integrator for `finalize_ready`; the
  `workflow.todo.phase_advanced` finalize-ready handoff remains owned by
  `IntegrationTriggerCartridge` plus the integrator singleton lease. When
  `workflow.todo.delivered` fires, the runner may re-evaluate dependents whose
  work gates are now satisfied.

## Known caveats

- The integrator is the only writer authorized to push `origin/main`. Worker sessions on per-slug branches push their feature branches only; main is reachable solely through this state machine.
- Two already-merged guards exist because squash merges do **not** create ancestry edges between the source branch and the merge commit. The ancestry check catches non-squash re-queues; the empty-staged-diff check catches squash re-queues. Both are required.
- Delivery bookkeeping runs inside `trees/_integration/`, not on repo root. The squash commit is pushed; the todo delivery stamp and dependency-reference cleanup are `todos.db` writes — untracked local state, never staged — applied only after the push is confirmed on `origin/main`.
- After a successful push, the integrator best-effort syncs repo root and pushes any repo-root bookkeeping that is ahead. Pull failure is non-fatal — cleanup proceeds regardless, and a warning surfaces in the completed summary.
- When the idle step is called with an explicit slug, only that slug is verified as ready; the FIFO scan is bypassed but ancestry and remote-branch existence checks still apply.
- The normal enqueue path is event-triggered: `workflow.todo.phase_advanced` (with `phase=finalize_ready` in payload) invokes the integration trigger cartridge, which spawns the singleton integrator only when no integrator session is open. Open integrators are left undisturbed and consume queued candidates on their next state-machine pass. The scanner remains the recovery path for missed events.
- Legacy entries are normalized so older persisted `finalize.status="handed_off"` reads back as `finalize.status="ready"` and is picked up by the same rule.
- The loop limit exists so multi-phase advances (e.g., COMMITTED → DELIVERY_BOOKKEEPING → PUSH_SUCCEEDED → CLEANUP → CANDIDATE_DELIVERED → IDLE → next candidate) can complete in one call without forcing the agent back through `telec todo integrate` repeatedly.
- The phase enum's AWAITING_COMMIT value is reachable but typically not written; MERGE_CLEAN and MERGE_CONFLICTED are written directly and re-entry handling treats all three equivalently.

<!-- planned-change:integration-gate-scope-and-conflict-path -->

- A content-gate rejection routes through the CANDIDATE_ABANDONED phase, which resets the integration worktree to origin/main, retracts the candidate from the pool, emits `integration.candidate.blocked`, and returns to IDLE so the queue keeps draining. It is the abandon counterpart of CANDIDATE_DELIVERED — same return-to-IDLE convergence, no delivery record. The distinction between a content-gate rejection (candidate content is bad; abandon and return to its owner) and a fast-forward-race rejection (remote moved; rebase-recoverable) is made from the pre-push content-gate marker in the rejection output.

<!-- change:integration-gate-scope-and-conflict-path -->

- A content-gate rejection is distinguished from a fast-forward-race rejection (remote moved; rebase-recoverable) by the pre-push content-gate marker in the rejection output. A content-gate rejection is a logical merge conflict handled per UC-WISM5 — resolved by the integrator in the integration worktree when mechanically groundable, escalated to the human otherwise while the integrator stays stopped on the candidate. There is no abandon path and no upstream owner: a candidate is never retracted, skipped, or drained past on a content failure.

<!-- /planned-change:integration-gate-scope-and-conflict-path -->

- Lifecycle event emission is fire-and-forget; event delivery failure never blocks integration progress and is only logged at debug level.
