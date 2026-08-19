---
description: Singleton, lease-serialized, durable-checkpoint state machine that squash-merges
  finalize-ready todos into origin/main from an isolated integration worktree.
visibility: public
---

# Integration State Machine — Spec


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

Push rejection is classified by cause. A rejection whose output carries the pre-push
content-gate marker (`telec code lint --all` failed on the squash content) is a
content-gate rejection; it routes to the logical-conflict path (UC-WISM5), never to
rebase recovery. Every other rejection is treated as a fast-forward race, recoverable
by the rebase-and-re-push instruction above.

#### UC-WISM1: Integrator-maintenance marker emission at delivery

```gherkin
Given the push to main succeeded and the integrator best-effort sync advanced repo-root main
When the PUSH_SUCCEEDED step runs, before the per-candidate pre_merge_head is cleared at CANDIDATE_DELIVERED
Then the state machine records a session-scoped integrator-maintenance marker for the integrator session
And the marker carries the delivered merge range (pre_merge_head..advanced repo-root HEAD)
And the agent-stop checkpoint engine consumes that marker to force-fire post-merge maintenance for the integrator
```

#### UC-WISM2: Push rejection withholds delivery

```gherkin
Given a candidate is squash-merged and committed in the integration worktree
When the push to origin/main is rejected
Then no delivery record is written and the todo status stays non-delivered
And the phase is PUSH_REJECTED
```

#### UC-WISM12: The pushed commit SHA is frozen at push time

```gherkin
Given a push of the squash to origin/main succeeds
When the state machine records the push result
Then the pushed commit SHA is frozen into the durable checkpoint at push time
```

#### UC-WISM13: A confirmed frozen commit records delivery exactly once

```gherkin
Given the frozen pushed commit is confirmed present on origin/main after a re-fetch
When the PUSH_SUCCEEDED confirmation gate runs
Then the delivery record is written exactly once
And the recorded delivered commit is the frozen pushed commit
```

#### UC-WISM14: Push-rejection recovery freezes the recovered commit

```gherkin
Given the push to origin/main is rejected and the operator recovers so the worktree HEAD matches origin/main
When the recovery transition freezes local HEAD as the pushed commit and the PUSH_SUCCEEDED confirmation gate confirms it on origin/main
Then the delivery record is written exactly once
```

#### UC-WISM15: A transformed delivery still confirms

```gherkin
Given the delivery transformed content relative to the candidate branch tip — the delivered-snippet fold, or an integrator follow-up commit resolving a repo-wide invariant on the candidate's own lines
When the PUSH_SUCCEEDED confirmation gate runs
Then confirmation succeeds and the delivery record is written
And the gate performs no content re-derivation from the candidate branch tip
```

#### UC-WISM16: A failed re-fetch withholds delivery

```gherkin
Given the re-fetch of origin fails before the confirmation check
When the PUSH_SUCCEEDED confirmation gate runs
Then no delivery record is written and the candidate returns to PUSH_REJECTED
```

#### UC-WISM17: A missing frozen pushed commit withholds delivery

```gherkin
Given no frozen pushed commit is recorded in the durable checkpoint
When the PUSH_SUCCEEDED confirmation gate runs
Then no delivery record is written and the candidate returns to PUSH_REJECTED
```

#### UC-WISM18: A pushed commit absent from origin/main withholds delivery

```gherkin
Given the frozen pushed commit is not present on origin/main after the re-fetch
When the PUSH_SUCCEEDED confirmation gate runs
Then no delivery record is written and the candidate returns to PUSH_REJECTED
```

The confirmation gate verifies that the **commit the integrator actually pushed**
is present on origin/main — a ref check against the SHA frozen at push time.
Freezing the SHA at push time is what closes the false-deliver gap: a worktree
later reset to origin/main changes nothing, because the gate never consults the
worktree HEAD. Content identity with the candidate branch tip is not required —
a delivery legitimately transforms content relative to that tip (the
delivered-snippet fold, integrator conflict-resolution commits), so the gate
performs no squash-merge re-derivation. The integrator's authority ends at the
push: post-push steps confirm, record, and clean up; they exercise no content
judgment.

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

<!-- planned-change:integrator-candidate-and-gate-parking -->

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

<!-- change:integrator-candidate-and-gate-parking -->

#### UC-WISM5: A pre-push gate rejection is resolved or parked; the gate is never bypassed

```gherkin
Given a candidate's squash is pushed and the push is rejected by the pre-push gate (telec code lint --all failed on the squash content)
When the state machine classifies the rejection from the content-gate marker
Then the candidate does not enter rebase recovery
And the integrator owns the finding — no upstream owner exists once a candidate is in the integration pipeline
And a finding it can mechanically ground is resolved in the integration worktree and re-pushed
And a finding it cannot ground confidently parks the candidate with a recorded reason, emits integration.candidate.parked, and the drain continues through the remaining independent candidates
And no sentinel, flag, or integrator-authored exception permits the failed candidate to pass the gate
And no delivery record is written for the candidate until its own squash content is confirmed on origin/main
```

<!-- /planned-change:integrator-candidate-and-gate-parking -->

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

<!-- planned-change:integrator-repo-root-sync-classification -->
```
Given repo root main carries uncommitted changes that the incoming origin/main content would overwrite
When the dispatcher runs its entry-time repo-root pull
Then the pull fails without stashing anything, and the integrator returns a formatted "repo_root_diverged" instruction
And the uncommitted changes are left untouched for their authoring session to resolve
And no candidate is dequeued for this call
```
<!-- change:integrator-repo-root-sync-classification -->
#### UC-WISM28: Dirty incoming overlap blocks repo-root fast-forward without touching WIP

```gherkin
Given repo-root main is behind origin/main
And repo root carries uncommitted paths that intersect the incoming origin/main paths
When the dispatcher classifies repo-root synchronization at entry
Then it reports the exact dirty incoming overlap as a dirty-overlap outcome
And it leaves every uncommitted path untouched for its authoring session to resolve
And no candidate is dequeued for this call
```
<!-- /planned-change:integrator-repo-root-sync-classification -->

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

<!-- planned-change:integrator-candidate-and-gate-parking -->

#### UC-WISM9: Integration validates with repo-wide gate semantics

```gherkin
Given a candidate is squash-merged and the integrator commits in the integration worktree
When the integration commit runs its quality gate
Then the format-fix step still runs over the squash content before the commit
And the gating checks carry repo-wide semantics — scope-sensitive checks that are only meaningful over the whole repository (duplication percentage) never gate the integration commit
And the pre-push telec code lint --all remains the single authoritative content gate
```

<!-- change:integrator-candidate-and-gate-parking -->

#### UC-WISM9: The pre-push quality gate remains authoritative and blocking

```gherkin
Given a candidate is squash-merged and the integrator commits in the integration worktree
When the integration commit runs its format-fix and the push runs the pre-push gate
Then the format-fix step still runs over the squash content before the commit
And scope-sensitive checks meaningful only over the whole repository (duplication percentage) never gate the integration commit
And the pre-push telec code lint --all remains the single authoritative content gate
And every failure blocks delivery until the integrator resolves it in the integration worktree or parks the candidate
And the integration path provides no candidate-specific quality override
```

<!-- /planned-change:integrator-candidate-and-gate-parking -->

#### UC-WISM10: The integrator resumes only a candidate that belongs to the current project

```gherkin
Given the durable checkpoint and lease live under the current project's resolved state root at ".teleclaude/integration/"
And a non-IDLE checkpoint names a candidate whose branch and "trees/<slug>" worktree are absent in the current project — whether the candidate belongs to another project or its assets are gone
When "telec todo integrate" runs
Then the integrator neither resumes that candidate nor returns SQUASH COMMIT REQUIRED for it
And it resets the checkpoint to IDLE and re-scans the current project's own finalize-ready candidates
```

#### UC-WISM11: A new-candidate dequeue always pins the squash base to current origin/main

```gherkin
Given the persistent integration worktree carries stale squash or merge metadata left by a prior aborted or operator-recovered merge
And its HEAD is behind current origin/main
When a new finalize-ready candidate is dequeued and the integrator prepares the squash merge
Then the integrator fetches origin and resets the integration worktree to current origin/main before pinning the pre-merge base
And the candidate's squash base is current origin/main, never the stale HEAD
```


#### UC-WISM19: An ungroundable textual merge conflict parks the candidate and the drain continues

```gherkin
Given a finalize-ready candidate's squash merge produced a textual conflict the integrator cannot ground a confident resolution for
And the integrator abandons the candidate without committing a resolution
When "telec todo integrate" runs the awaiting-commit step
Then the candidate is parked with a recorded reason of an unresolvable textual merge conflict
And the candidate's finalize.status is not retracted and no delivery record is written for it
And the drain continues by dequeuing the next independent finalize-ready candidate rather than re-issuing the conflict instruction forever
```

#### UC-WISM20: A parked candidate's transitive dependents are excluded from the drain

```gherkin
Given a candidate is parked during the current drain
And another finalize-ready candidate transitively depends on the parked candidate through the todo dependency graph
When the integrator selects the next candidate — whether by FIFO scan or by explicit-slug verification
Then neither the parked candidate nor any candidate downstream of it is dequeued or delivered
And an independent finalize-ready candidate with no dependency on the parked one is still delivered
```

#### UC-WISM21: The drain ends with a loud unified report of every parked candidate

```gherkin
Given one or more candidates were parked during the drain
When the integration queue has no remaining eligible candidate and the drain ends
Then the completion report names every parked candidate and the reason each was parked
And a parked candidate is never silently omitted from the report
```

#### UC-WISM22: Parking and drain end emit projector-reconstructable taxonomy events

```gherkin
Given a candidate is parked during the drain
When the park is recorded
Then an integration.candidate.parked event is emitted carrying the slug, branch, sha, and park reason
And when the drain ends an integration.drain.completed event is emitted carrying the delivered count and every parked candidate with its reason
And the drain outcome is reconstructable from the event stream alone
```

#### UC-WISM23: The parked set is scoped to a single drain

```gherkin
Given a candidate was parked in a completed drain
When a fresh "telec todo integrate" drain later begins with the checkpoint idle
Then the parked set is cleared for the new drain
And the previously parked candidate is re-attempted as an ordinary finalize-ready candidate
```


<!-- planned-change:integrator-repo-root-sync-classification -->

#### UC-WISM24: A diverged post-delivery repo-root pull still regenerates the Blueprint

```gherkin
Given a finalize-ready candidate is confirmed contained on origin/main and its delivery is recorded
And the post-delivery repo-root "git pull --ff-only origin main" diverges and fails
When _step_push_succeeded runs
Then the Blueprint graph and manifest are regenerated at the delivered commit from the integration worktree
And the manifest baseline_sha is the delivered origin/main commit
And the delivery completes without being blocked by the divergence
```

<!-- change:integrator-repo-root-sync-classification -->

#### UC-WISM24: An unsynced post-delivery repo root still regenerates the Blueprint

```gherkin
Given a finalize-ready candidate is confirmed contained on origin/main and its delivery is recorded
And the post-delivery repo-root sync leaves repo-root main behind the delivered commit
When _step_push_succeeded runs
Then the Blueprint graph and manifest are regenerated at the delivered commit from the integration worktree
And the manifest baseline_sha is the delivered origin/main commit
And the delivery completes without being blocked by the unsynced repo root
```

<!-- /planned-change:integrator-repo-root-sync-classification -->

<!-- planned:integrator-repo-root-sync-classification -->

#### UC-WISM27: The repo-root sync classifies its state instead of probing with a pull that cannot succeed

```gherkin
Given repo-root main and origin/main are not at the same commit when a "telec todo integrate" call begins
When the integrator classifies repo-root main against origin
Then a repo root that is only behind is fast-forwarded and the call proceeds with no instruction returned
And a repo root that is only ahead proceeds without rewriting its local commits
And a repo root that is both ahead and behind is reported as the expected post-delivery condition, never as a divergence failure
And the report carries the intersection of the incoming file list with the repo-root dirty set as a fact
And the integrator owns the merge — the state machine never merges repo-root main
And no candidate is dequeued for that call until repo-root main is synced
```


<!-- /planned:integrator-repo-root-sync-classification -->

<!-- planned:integrator-candidate-and-gate-parking -->

#### UC-WISM25: A candidate whose span carries a foreign slug's commit is parked

```gherkin
Given a finalize-ready candidate whose span (origin/main..tip) contains a non-merge commit that belongs to a different in-flight slug
And the foreign commit is identified by a conventional-commit scope naming another slug present in the todo registry, or by files it touches that fall outside the candidate plan's referenced-paths contract
When the integrator prepares to integrate the candidate
Then the candidate is parked with a recorded candidate-cleanliness reason and integration.candidate.parked is emitted
And no delivery record is written for the candidate and its transitive dependents are excluded from the drain
And the drain continues through the remaining independent candidates
```

#### UC-WISM26: An ambiguous span commit is surfaced to integrator judgment, never auto-parked

```gherkin
Given a candidate span carries a non-merge commit whose ownership cannot be decided by an exact predicate — no conventional-commit scope naming another registered slug and no referenced-paths breach
When the integrator prepares to integrate the candidate
Then the ambiguous commit is surfaced to the integrator's judgment rather than classified by code
And the candidate is not parked automatically on the strength of the ambiguous signal alone
```

<!-- /planned:integrator-candidate-and-gate-parking -->

<!-- planned:fix-telec-sync-validation-blocks-on-a-stale -->
#### UC-WISM29: Repo-root pending documentation reaches its delivery fold

```gherkin
Given repo-root main is fast-forwardable with origin/main
And repo-root main contains committed pending documentation for a finalize-ready slug that origin/main does not yet contain
When the integrator begins a fresh candidate dequeue
Then it pushes repo-root main to origin/main before resetting the integration worktree
And the integration worktree resets from that updated origin/main
And the delivered-snippet fold clears that slug's pending documentation before the delivery commit is pushed

Given the pre-dequeue repo-root push is rejected
When the integrator begins a fresh candidate dequeue
Then it returns the publish failure without dequeuing a candidate
And no delivery record is written
```
<!-- /planned:fix-telec-sync-validation-blocks-on-a-stale -->

<!-- planned:telec-code-dirty-path-owners -->
#### UC-WISM31: A batch dirty-path query attributes the earliest live uncommitted claimant

```gherkin
Given a caller supplies one or more dirty project-relative paths
And zero or more open local-project sessions have touched those paths
When the caller asks for the paths' owners in one batch
Then the result is a JSON object keyed by every requested project-relative path
And the earliest live session whose claim remains uncommitted owns each claimed path
And a later session touching the same path does not transfer that ownership
And an owned path reports the TeleClaude session UUID, job role, and session title
And a path with no live claimant reports a null owner
And the query reports the count of captured sessions whose attribution signal is UNDETERMINED without exposing their identity
And the query reads one live-session snapshot without scanning closed sessions or rechecking liveness
```

#### UC-WISM30: The integrator resolves aged dirty blockers by owner group and custodianship

```gherkin
Given repo-root synchronization remains blocked after the dirty-main quiet window
And the integration instruction carries the complete set of blocking dirty paths
When the integrator resolves ownership for that complete set
Then it coordinates each live owner once with every blocking path attributed to that session
And an unchanged blocking set is not queried or coordinated again on later reminder beats
And every null-owned path transfers to the integrator for inspection
And the integrator commits discernible intentional work or reverts abandoned residue
And a positive UNDETERMINED-session count prohibits treating null-owned residue as abandoned
And an unsettled live-owned path keeps the integrator waiting without mutation, repeat contact, or human escalation
And only a path whose intent cannot be determined safely is escalated to the human
```
<!-- /planned:telec-code-dirty-path-owners -->

### Cross-context references


- `agent_runtime` — receives fire-and-forget lifecycle events: `integration.started`, `integration.candidate.dequeued`, `integration.candidate.already_merged`, `integration.merge.succeeded`, `integration.merge.conflicted`, `integration.candidate.committed`, `integration.push.succeeded`, `integration.push.rejected`, `integration.candidate.delivered`, `integration.candidate.blocked`, `integration.candidate.parked`, `integration.drain.completed`.


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
<!-- planned-change:integrator-repo-root-sync-classification -->
- After a successful push, the integrator best-effort syncs repo root and pushes any repo-root bookkeeping that is ahead. Pull failure is non-fatal — cleanup proceeds regardless, and a warning surfaces in the completed summary.
<!-- change:integrator-repo-root-sync-classification -->
- After a successful push, the integrator classifies repo root and fast-forwards it only when safe, then pushes any ahead-only repo-root bookkeeping. A non-ready classification or bookkeeping-push failure does not undo confirmed delivery: maintenance marking, Blueprint regeneration from the confirmed integration-worktree commit, and cleanup still complete, after which the call returns the sync instruction before another candidate can be dequeued.
<!-- /planned-change:integrator-repo-root-sync-classification -->
- When the idle step is called with an explicit slug, only that slug is verified as ready; the FIFO scan is bypassed but ancestry and remote-branch existence checks still apply.
- The normal enqueue path is event-triggered: `workflow.todo.phase_advanced` (with `phase=finalize_ready` in payload) invokes the integration trigger cartridge, which spawns the singleton integrator only when no integrator session is open. Open integrators are left undisturbed and consume queued candidates on their next state-machine pass. The scanner remains the recovery path for missed events.
- Legacy entries are normalized so older persisted `finalize.status="handed_off"` reads back as `finalize.status="ready"` and is picked up by the same rule.

- The loop limit exists so multi-phase advances (e.g., COMMITTED → DELIVERY_BOOKKEEPING → PUSH_SUCCEEDED → CLEANUP → CANDIDATE_DELIVERED → IDLE → next candidate) can complete in one call without forcing the agent back through `telec todo integrate` repeatedly.

- The phase enum's AWAITING_COMMIT value is reachable but typically not written; MERGE_CLEAN and MERGE_CONFLICTED are written directly and re-entry handling treats all three equivalently.

<!-- planned-change:integrator-candidate-and-gate-parking -->

- A content-gate rejection is distinguished from a fast-forward-race rejection (remote moved; rebase-recoverable) by the pre-push content-gate marker in the rejection output. A content-gate rejection is a logical merge conflict handled per UC-WISM5 — resolved by the integrator in the integration worktree when mechanically groundable, escalated to the human otherwise while the integrator stays stopped on the candidate. There is no abandon path and no upstream owner: a candidate is never retracted, skipped, or drained past on a content failure.

<!-- change:integrator-candidate-and-gate-parking -->

- A content-gate rejection is distinguished from a fast-forward-race rejection (remote moved; rebase-recoverable) by the pre-push content-gate marker in the rejection output. The pre-push gate remains authoritative and blocking. The integrator fixes a finding it can ground and re-pushes; when it cannot ground the finding, it parks the candidate and continues the drain through independent work. No candidate is delivered past the failed gate.

<!-- /planned-change:integrator-candidate-and-gate-parking -->


- A textual merge conflict the integrator cannot ground a confident resolution for is parked rather than halted: the candidate is set aside with a recorded reason, its transitive dependents are excluded, and the drain continues through the remaining independent candidates (UC-WISM19–UC-WISM21). Parking is a per-drain, in-checkpoint set-aside — `finalize.status` is not retracted, so a later drain re-attempts the candidate (UC-WISM23). This park path is distinct from the content-gate halt above, which is unchanged.


- Lifecycle event emission is fire-and-forget; event delivery failure never blocks integration progress and is only logged at debug level.
