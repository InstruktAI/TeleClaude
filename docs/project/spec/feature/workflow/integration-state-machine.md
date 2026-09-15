---
description: Singleton, lease-serialized, durable-checkpoint state machine that squash-merges
  finalize-ready todos into origin/main from an isolated integration worktree.
visibility: public
---

# Integration State Machine — Spec

## What it is

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
The integration state machine is Phase C of the todo lifecycle — the only authorized writer of canonical `origin/main`. It runs as a singleton (one active integrator per project, enforced by a lease keyed on `integration/main`) and consumes finalize-ready Todos in FIFO order. Each call resumes from a durable checkpoint, executes the next deterministic step, and either loops internally or returns a structured instruction block that asks the calling agent to do the one thing only intelligence can do: compose a squash commit message, resolve a merge conflict, or recover from a rejected push. Candidate git mutations happen inside an isolated integration worktree at `trees/_integration/`. Repo-root mutation is limited to publishing already-committed ahead-only state before candidate selection, fast-forward synchronization after delivery, and slug-scoped settled-marker recovery after a maintenance fault. When the queue drains, the integrator emits `workflow.todo.delivered` per slug, removes per-slug worktrees and branches, archives binary artifacts, and ends.
<!-- change:fix-delivered-todos-attribution-by-declarati -->
The integration state machine is Phase C of the todo lifecycle — the only authorized writer of canonical `origin/main`. It runs as a singleton and consumes finalize-ready Todos in FIFO order under the `integration/main` lease. The integration worktree prepares and publishes each candidate commit without reconciling documentation. After confirming that candidate push, the machine synchronizes repository-root main, folds the candidate slug there, runs the final gates, publishes the resulting root head, and records delivery only after confirming that final push. When repository-root main is unsafe to mutate, delivery waits with the blocking evidence. When the queue drains, the integrator emits `workflow.todo.delivered` per slug, removes per-slug worktrees and branches, archives binary artifacts, and ends.
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

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

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```
Given the squash commit is committed in the integration worktree
When the push to main is rejected because the remote moved (a non-fast-forward race)
Then the state machine writes PUSH_REJECTED with the rejection reason classified as a fast-forward race
And returns an instruction asking the agent to rebase onto origin/main and push from the integration worktree, each command directory-qualified to that worktree
And the next call computes local HEAD vs remote main; if they match, recovery is detected and phase advances to PUSH_SUCCEEDED
And integration.push.rejected is emitted at rejection and integration.push.succeeded on recovery
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```
Given either the integration-worktree candidate push or the later folded repository-root push is rejected
When the state machine records the rejected push
Then it preserves the candidate as non-delivered and identifies the rejected stage
And candidate-push recovery remains scoped to the integration worktree
And finalization-push recovery synchronizes and retries repository-root main without overwriting uncommitted work
And delivery remains withheld until the folded repository-root head is confirmed on origin/main
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

Push rejection is classified by cause. A rejection whose output carries the pre-push
content-gate marker (`telec code lint --all` failed on the squash content) is a
content-gate rejection; it routes to the logical-conflict path (UC-WISM5), never to
rebase recovery. Every other rejection is treated as a fast-forward race, recoverable
by the rebase-and-re-push instruction above.

#### UC-WISM1: Integrator-maintenance marker emission at delivery

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the push to main succeeded and the integrator best-effort sync advanced repo-root main
When the PUSH_SUCCEEDED step runs, before the per-candidate pre_merge_head is cleared at CANDIDATE_DELIVERED
Then the state machine records a session-scoped integrator-maintenance marker for the integrator session
And the marker carries the delivered merge range (pre_merge_head..advanced repo-root HEAD)
And the agent-stop checkpoint engine consumes that marker to force-fire post-merge maintenance for the integrator
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the integrator has confirmed the final repository-root head on origin/main
When the PUSH_SUCCEEDED step runs before the candidate checkpoint is cleared
Then the state machine records an integrator-maintenance marker for the integrator session
And the marker carries the delivered range ending at the confirmed repository-root head
And the agent-stop checkpoint engine consumes that marker to force-fire post-merge maintenance for the integrator
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM2: Push rejection withholds delivery

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given a candidate is squash-merged and committed in the integration worktree
When the push to origin/main is rejected
Then no delivery record is written and the todo status stays non-delivered
And the phase is PUSH_REJECTED
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given either candidate publication or folded-root publication is rejected
When the corresponding push to origin/main fails
Then no delivery record is written and the todo stays non-delivered
And the phase records which publication requires recovery
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM12: The pushed commit SHA is frozen at push time

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given a push of the squash to origin/main succeeds
When the state machine records the push result
Then the pushed commit SHA is frozen into the durable checkpoint at push time
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the prepared candidate is pushed from the integration worktree
When the state machine records that result
Then the candidate SHA is frozen for confirmation and repository-root synchronization
And when the folded repository-root head is later pushed, its SHA replaces the candidate SHA as the final delivery evidence
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM13: A confirmed frozen commit records delivery exactly once

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the frozen pushed commit is confirmed present on origin/main after a re-fetch
When the PUSH_SUCCEEDED confirmation gate runs
Then the delivery record is written exactly once
And the recorded delivered commit is the frozen pushed commit
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the folded repository-root SHA is frozen and confirmed present on origin/main
When the final confirmation gate records delivery
Then the delivery record is written exactly once
And the recorded delivered commit is that final repository-root SHA
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM14: Push-rejection recovery freezes the recovered commit

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the push to origin/main is rejected and the operator recovers so the worktree HEAD matches origin/main
When the recovery transition freezes local HEAD as the pushed commit and the PUSH_SUCCEEDED confirmation gate confirms it on origin/main
Then the delivery record is written exactly once
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given either publication stage was rejected and the integrator completed its stage-specific recovery
When the candidate push is confirmed and the folded repository-root push is subsequently confirmed
Then the final repository-root SHA is frozen as delivery evidence
And the delivery record is written exactly once
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

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

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
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
<!-- change:fix-delivered-todos-attribution-by-declarati -->
The first confirmation gate verifies that the prepared integration-worktree
candidate reached origin/main before repository-root finalization begins. The
machine then synchronizes and folds repository-root main. The second confirmation
gate verifies that folded root head and replaces the intermediate candidate SHA
with the final delivery SHA. All documentation mutation finishes before the
second push; after its confirmation the machine only records delivery and cleans
up.
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM3: Delivered-snippet fold re-asserted across every delivery path

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
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
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given a candidate commit is prepared in the integration worktree through a clean merge, conflict resolution, or crash recovery
When the state machine reaches delivery finalization
Then it publishes and confirms that candidate commit on origin/main without folding documentation
And it synchronizes repository-root main with the confirmed candidate without including uncommitted work
And it runs one applied delivered-snippet fold for the candidate slug on repository-root main
And it runs the residual and content gates against repository-root main
And it publishes and confirms the folded repository-root head before recording delivery

Given candidate publication, repository-root synchronization, marker reconciliation, staging, commit, or the final content gate fails
When delivery finalization handles that failure
Then no delivery record is produced
And the candidate remains pending with the blocking evidence
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM4: Pre-push residual-marker gate fails closed

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the delivered slug's snippets would still carry a planned-change or planned marker for that slug after the fold
When the delivery-bookkeeping residual-marker gate runs before the push
Then the push to origin/main does not happen
And the candidate stays at delivery bookkeeping with a residual-marker error naming the file, line, and slug
And a delivered slug never reaches origin/main carrying its own live markers
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given repository-root main would still carry pending documentation material for the candidate slug after reconciliation
When the final residual-marker gate runs against repository-root main
Then the push to origin/main does not happen
And the candidate remains pending with an error naming the file, line, slug, and carrier
And no delivered slug reaches origin/main while its authoritative documentation remains pending
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM5: A pre-push gate rejection is resolved or parked; the gate is never bypassed

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
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
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given either the integration-worktree candidate head or the folded repository-root head fails its content gate
When the state machine classifies the rejection
Then a candidate-stage failure may be resolved or parked before that candidate reaches origin/main
And once the candidate push is confirmed, a final-stage failure keeps that candidate current and blocks the drain until the repository-root state passes
And the integrator owns the finding because the candidate is already in the integration pipeline
And no exception permits the failed candidate to bypass the gate
And no delivery record is written until the folded repository-root head is confirmed on origin/main
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

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

#### UC-WISM28: Dirty incoming overlap blocks repo-root fast-forward without touching WIP

```gherkin
Given repo-root main is behind origin/main
And repo root carries uncommitted paths that intersect the incoming origin/main paths
When the dispatcher classifies repo-root synchronization at entry
Then it reports the exact dirty incoming overlap as a dirty-overlap outcome
And it leaves every uncommitted path untouched for its authoring session to resolve
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

#### UC-WISM9: The pre-push quality gate remains authoritative and blocking

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given a candidate is squash-merged and the integrator commits in the integration worktree
When the integration commit runs its format-fix and the push runs the pre-push gate
Then the format-fix step still runs over the squash content before the commit
And scope-sensitive checks meaningful only over the whole repository (duplication percentage) never gate the integration commit
And the pre-push telec code lint --all remains the single authoritative content gate
And every failure blocks delivery until the integrator resolves it in the integration worktree or parks the candidate
And the integration path provides no candidate-specific quality override
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the integration worktree has prepared a candidate or repository-root main has prepared its folded finalization
When the corresponding content gate runs before either push
Then the candidate-stage gate evaluates the isolated candidate head
And the final-stage gate evaluates the full repository-root head through the same native quality implementation
And a final-stage failure after candidate-push confirmation blocks the drain until it is resolved
And the integration path provides no candidate-specific quality override
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

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

#### UC-WISM24: An unsynced post-delivery repo root still regenerates the Blueprint

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given a finalize-ready candidate is confirmed contained on origin/main and its delivery is recorded
And the post-delivery repo-root sync leaves repo-root main behind the delivered commit
When _step_push_succeeded runs
Then the Blueprint graph and manifest are regenerated at the delivered commit from the integration worktree
And the manifest baseline_sha is the delivered origin/main commit
And the delivery completes without being blocked by the unsynced repo root
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given repository-root main contains the prepared candidate and its folded documentation
When the integrator confirms that final head on origin/main and records delivery
Then the Blueprint graph and manifest are regenerated at that confirmed commit
And the manifest baseline_sha is the delivered origin/main commit
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM32: Delivery reconciles the candidate's pending documentation exactly once

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given a candidate's delivered-snippet fold has been committed into the delivery and pushed to origin/main
When the confirmation gate records the delivery
Then the reconciliation the delivery record rests on is the one already applied in the integration worktree
And no second reconciliation of that slug is applied against the repo root as part of candidate delivery
And the delivery leaves repo-root main with no commit the delivery itself authored there
And the repo root reaches the delivered content by publishing committed ahead-only state before candidate selection and synchronizing with origin/main after delivery
And the recorded delivered commit is the frozen pushed commit
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the integration worktree has published a candidate commit without reconciling documentation
When the integrator confirms that candidate and finalizes it
Then it synchronizes repository-root main with the candidate
And it applies candidate-delivery reconciliation only against repository-root main
And it runs no candidate-delivery reconciliation in the integration worktree
And crash recovery may repeat a completed reconciliation only as an idempotent no-op
And it publishes the folded repository-root head
And the recorded delivered commit is that final confirmed SHA
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
#### UC-WISM33: Idle integration publishes ahead-only repo-root state before candidate selection

```gherkin
Given the integration checkpoint is idle
And repo-root main contains committed work ahead of origin/main and is not behind it
When the integrator classifies repository-root synchronization at entry
Then it publishes repo-root main to origin/main through the integrator's canonical-main writer path
And it confirms the published commit on origin/main before selecting a candidate
And the integration worktree is based on that updated origin/main
And a publication or confirmation failure prevents candidate dequeue without rewriting the local commits
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

#### UC-WISM34: Settled marker divergence is repaired outside candidate delivery

```gherkin
Given lifecycle maintenance faults pending documentation material owned by an already-delivered slug
And no active integration candidate can reconcile that material
When the integrator begins recovery with repository-root main synchronized and safe to mutate
Then it performs one idempotent slug-scoped delivery reconciliation against the repository root
And it commits and publishes the reconciliation through the canonical-main writer path
And it leaves the original delivery record and recorded delivering commit unchanged
And the recovery is not counted as a second reconciliation in the original candidate delivery
And unrelated pending documentation remains byte-identical
```

#### UC-WISM27: The repo-root sync classifies its state instead of probing with a pull that cannot succeed

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given repo-root main and origin/main are not at the same commit when a "telec todo integrate" call begins
When the integrator classifies repo-root main against origin
Then a repo root that is only behind is fast-forwarded and the call proceeds with no instruction returned
And an idle integrator publishes a repo root that is only ahead before candidate selection without rewriting its local commits
And a repo root that is both ahead and behind is reported as the expected post-delivery condition, never as a divergence failure
And the report carries the intersection of the incoming file list with the repo-root dirty set as a fact
And the integrator owns the merge — the state machine never merges repo-root main
And no candidate is dequeued for that call until repo-root main is synced
```
<!-- change:fix-delivered-todos-attribution-by-declarati -->
```gherkin
Given the integration-worktree candidate push is confirmed on origin/main
When the integrator synchronizes repository-root main for documentation finalization
Then a repository root that is only behind is fast-forwarded when its dirty paths permit it
And a repository root that is only ahead or split preserves its committed documentation while incorporating the confirmed candidate
And a dirty state or conflict that prevents safe synchronization blocks delivery with the exact paths and graph state
And no marker fold or final push runs until repository-root synchronization is complete
```
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->

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
And an unchanged blocking set is queried again on later reminder beats against a fresh open-session snapshot
And an owner already coordinated for that blocking set is never contacted again
And a newly observed live owner is coordinated once with its complete attributed subset
And every null-owned path transfers to the integrator for inspection
And the integrator commits discernible intentional work or reverts abandoned residue
And a positive UNDETERMINED-session count prohibits treating null-owned residue as abandoned for that result
And revert authority returns only after a later result reports zero undetermined sessions and no live owner for the path
And an unsettled live-owned path or positive undetermined count initially keeps the integrator waiting without mutation or repeat contact
And an unchanged live owner-path group or positive undetermined count that survives three consecutive later reminder beats after first observation causes one escalation carrying the complete current owner groups, paths, and privacy-safe count
And the integrator then remains the single non-mutating blocker beacon without repeating the owner message or escalation for that blocking set
And the reminder is cancelled at that escalation
And apart from the bounded protection-condition stall, only a path whose intent cannot be determined safely is escalated to the human
```

#### UC-WISM29: A drained singleton parks on its queue watcher

```gherkin
Given the singleton integrator completes a drain with no eligible candidate remaining
When the state machine returns its queue-empty outcome
Then the outcome instructs the integrator to arm recurring `integrator-queue-watch`
And the profile checks the queue every 15 minutes by default while parked
And it does not reuse dirty-main clearance or candidate-settledness for that wait
And a firing that finds a candidate cancels the queue watcher before continuing the drain
And an empty queue leaves the watcher live until an explicit lifecycle condition cancels it
```

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
<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
- Delivery bookkeeping runs inside `trees/_integration/`, not on repo root. The squash commit is pushed; the todo delivery stamp and dependency-reference cleanup are `todos.db` writes — untracked local state, never staged — applied only after the push is confirmed on `origin/main`.
- After a successful push, the integrator classifies repo root and fast-forwards it only when safe, then pushes any ahead-only repo-root bookkeeping. A non-ready classification or bookkeeping-push failure does not undo confirmed delivery: maintenance marking, Blueprint regeneration from the confirmed integration-worktree commit, and cleanup still complete, after which the call returns the sync instruction before another candidate can be dequeued.
<!-- change:fix-delivered-todos-attribution-by-declarati -->
- The integration worktree prepares and publishes the candidate commit. That confirmed push is intermediate evidence and does not release dependencies. Repository-root main owns the sole documentation fold, the final content gate, the final push, and the recorded delivery SHA.
- Repository-root main may contain committed work ahead of the intermediate candidate push. That committed state remains part of finalization. Any graph, conflict, or dirty-path condition that prevents safe synchronization or reconciliation blocks delivery and leaves uncommitted work untouched.
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->
- When the idle step is called with an explicit slug, only that slug is verified as ready; the FIFO scan is bypassed but ancestry and remote-branch existence checks still apply.
- The normal enqueue path is event-triggered: `workflow.todo.phase_advanced` (with `phase=finalize_ready` in payload) invokes the integration trigger cartridge, which spawns the singleton integrator only when no integrator session is open. Open integrators are left undisturbed and consume queued candidates on their next state-machine pass. The scanner remains the recovery path for missed events.
- Legacy entries are normalized so older persisted `finalize.status="handed_off"` reads back as `finalize.status="ready"` and is picked up by the same rule.

- The loop limit exists so multi-phase advances (e.g., COMMITTED → DELIVERY_BOOKKEEPING → PUSH_SUCCEEDED → CLEANUP → CANDIDATE_DELIVERED → IDLE → next candidate) can complete in one call without forcing the agent back through `telec todo integrate` repeatedly.

- The phase enum's AWAITING_COMMIT value is reachable but typically not written; MERGE_CLEAN and MERGE_CONFLICTED are written directly and re-entry handling treats all three equivalently.

- A content-gate rejection is distinguished from a fast-forward-race rejection (remote moved; rebase-recoverable) by the pre-push content-gate marker in the rejection output. The pre-push gate remains authoritative and blocking. The integrator fixes a finding it can ground and re-pushes; when it cannot ground the finding, it parks the candidate and continues the drain through independent work. No candidate is delivered past the failed gate.

- A textual merge conflict the integrator cannot ground a confident resolution for is parked rather than halted: the candidate is set aside with a recorded reason, its transitive dependents are excluded, and the drain continues through the remaining independent candidates (UC-WISM19–UC-WISM21). Parking is a per-drain, in-checkpoint set-aside — `finalize.status` is not retracted, so a later drain re-attempts the candidate (UC-WISM23). This park path is distinct from the content-gate halt above, which is unchanged.

- Lifecycle event emission is fire-and-forget; event delivery failure never blocks integration progress and is only logged at debug level.

## See Also

<!-- planned-change:fix-delivered-todos-attribution-by-declarati -->
- docs/project/adr/0085-canonical-doc-state-before-delivery.md — why repo-root documentation is published before candidate selection and terminal divergence repair is a separate operation.
<!-- change:fix-delivered-todos-attribution-by-declarati -->
- docs/project/adr/0090-root-fold-finalizes-a-pushed-candidate.md — why a confirmed candidate push precedes repository-root folding and the final delivery push.
- docs/project/adr/0091-published-candidate-finalization-blocks-the-drain.md — why parking ends once candidate publication is confirmed.
<!-- /planned-change:fix-delivered-todos-attribution-by-declarati -->
- docs/project/adr/0082-candidate-span-ownership-inspection-is-withdrawn.md — why span-ownership inspection was removed rather than corrected.
- docs/project/adr/0076-integrator-parks-blockers-and-keeps-quality-gating.md — the park-and-drain decision, whose conflict and content-gate paths are unchanged.
