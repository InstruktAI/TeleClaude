---
description: Singleton, lease-serialized, durable-checkpoint state machine that squash-merges
  finalize-ready todos into origin/main from an isolated integration worktree.
visibility: public
---

# Integration State Machine — Spec

## What it is

The integration state machine is Phase C of the todo lifecycle — the only authorized writer of canonical `origin/main`. It runs as a singleton and consumes finalize-ready Todos in FIFO order under the `integration/main` lease. The integration worktree prepares and publishes each candidate commit without reconciling documentation. After confirming that candidate push, the machine synchronizes repository-root main, folds the candidate slug there, runs the final gates, publishes the resulting root head, and records delivery only after confirming that final push. When repository-root main is unsafe to mutate, delivery waits with the blocking evidence. When the queue drains, the integrator emits the todo-delivered event per slug, removes per-slug worktrees and branches, archives binary artifacts, and ends.

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
Or the squash merge succeeded and produced an empty staged diff (squash of already-integrated commits)
When the merge step runs
Then the candidate skips merge and commit entirely
And the checkpoint advances to CANDIDATE_DELIVERED
And integration.candidate.already_merged is emitted
And any leftover squash-merge bookkeeping is cleaned up
```

```gherkin
Given the squash merge failed and staged nothing
And no conflicted paths explain the failure
When the merge step runs
Then no delivery is inferred and the checkpoint does not advance
And the step returns a MERGE_FAILED_WITHOUT_CONFLICTS error carrying git's stderr and the integration worktree path
```

```
Given either the integration-worktree candidate push or the later folded repository-root push is rejected
When the state machine records the rejected push
Then it preserves the candidate as non-delivered and identifies the rejected stage
And candidate-push recovery remains scoped to the integration worktree
And finalization-push recovery synchronizes and retries repository-root main without overwriting uncommitted work
And delivery remains withheld until the folded repository-root head is confirmed on origin/main
```

Push rejection is classified by cause. A rejection whose output carries the pre-push
content-gate marker (`telec code lint --all` failed on the squash content) is a
content-gate rejection; it routes to the logical-conflict path (UC-WISM5), never to
rebase recovery. Every other rejection is treated as a fast-forward race, recoverable
by the rebase-and-re-push instruction above.

#### UC-WISM1: Integrator-maintenance marker emission at delivery

```gherkin
Given integration advances repository-root main through a fast-forward or finalization commit
When that canonical-root advancement completes
Then the owed deterministic maintenance is recorded from the canonical checkout and begins independently
And integration does not wait for every maintenance action to finish
And the canonical-main commit boundary records a checkout-scoped marker only when the range owes a live-runtime log check
And the marker carries the advanced range and activation time but no mechanical action id
And the standing integrator retains the marker until every owed maintenance action succeeds and the latest maintenance-ready time is recorded
And its runtime log judgment discharges the marker only from evidence read after that time, covering the earliest activation through completed maintenance
```

#### UC-WISM2: Push rejection withholds delivery

```gherkin
Given either candidate publication or folded-root publication is rejected
When the corresponding push to origin/main fails
Then no delivery record is written and the todo stays non-delivered
And the phase records which publication requires recovery
```

#### UC-WISM12: The pushed commit SHA is frozen at push time

```gherkin
Given the prepared candidate is pushed from the integration worktree
When the state machine records that result
Then the candidate SHA is frozen for confirmation and repository-root synchronization
And when the folded repository-root head is later pushed, its SHA replaces the candidate SHA as the final delivery evidence
```

#### UC-WISM13: A confirmed frozen commit records delivery exactly once

```gherkin
Given the folded repository-root SHA is frozen and confirmed present on origin/main
When the final confirmation gate records delivery
Then the delivery record is written exactly once
And the recorded delivered commit is that final repository-root SHA
```

#### UC-WISM14: Push-rejection recovery freezes the recovered commit

```gherkin
Given either publication stage was rejected and the integrator completed its stage-specific recovery
When the candidate push is confirmed and the folded repository-root push is subsequently confirmed
Then the final repository-root SHA is frozen as delivery evidence
And the delivery record is written exactly once
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

The first confirmation gate verifies that the prepared integration-worktree
candidate reached origin/main before repository-root finalization begins. The
machine then synchronizes and folds repository-root main. The second confirmation
gate verifies that folded root head and replaces the intermediate candidate SHA
with the final delivery SHA. All documentation mutation finishes before the
second push; after its confirmation the machine only records delivery and cleans
up.

#### UC-WISM3: Delivered-snippet fold re-asserted across every delivery path

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

#### UC-WISM4: Pre-push residual-marker gate fails closed

```gherkin
Given repository-root main would still carry pending documentation material for the candidate slug after reconciliation
When the final residual-marker gate runs against repository-root main
Then the push to origin/main does not happen
And the candidate remains pending with an error naming the file, line, slug, and carrier
And no delivered slug reaches origin/main while its authoritative documentation remains pending
```

#### UC-WISM5: A pre-push gate rejection is resolved or parked; the gate is never bypassed

```gherkin
Given either the integration-worktree candidate head or the folded repository-root head fails its content gate
When the state machine classifies the rejection
Then a candidate-stage failure may be resolved or parked before that candidate reaches origin/main
And once the candidate push is confirmed, a final-stage failure keeps that candidate current and blocks the drain until the repository-root state passes
And the integrator owns the finding because the candidate is already in the integration pipeline
And no exception permits the failed candidate to bypass the gate
And no delivery record is written until the folded repository-root head is confirmed on origin/main
```

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
Given several canonical-root advancements owe log judgment before that judgment completes
When each advancement records its committed change
Then the checkout-scoped marker accumulates the ranges rather than overwriting an earlier range
And each advancement retains its own owed maintenance until every action reaches a terminal outcome
```

#### UC-WISM9: The pre-push quality gate remains authoritative and blocking

```gherkin
Given the integration worktree has prepared a candidate or repository-root main has prepared its folded finalization
When the corresponding content gate runs before either push
Then the candidate-stage gate evaluates the isolated candidate head
And the final-stage gate evaluates the full repository-root head through the same native quality implementation
And a final-stage failure after candidate-push confirmation blocks the drain until it is resolved
And the integration path provides no candidate-specific quality override
```

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

```gherkin
Given repository-root main contains the prepared candidate and its folded documentation
When the integrator confirms that final head on origin/main and records delivery
Then the Blueprint graph and manifest are regenerated at that confirmed commit
And the manifest baseline_sha is the delivered origin/main commit
```

#### UC-WISM32: Delivery reconciles the candidate's pending documentation exactly once

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

```gherkin
Given the integration-worktree candidate push is confirmed on origin/main
When the integrator synchronizes repository-root main for documentation finalization
Then a repository root that is only behind is fast-forwarded when its dirty paths permit it
And a repository root that is only ahead or split preserves its committed documentation while incorporating the confirmed candidate
And a dirty state or conflict that prevents safe synchronization blocks delivery with the exact paths and graph state
And no marker fold or final push runs until repository-root synchronization is complete
```

#### UC-WISM36: The integrator asks only a quiet path's writers, then commits it when nobody claims it

```gherkin
Given repo-root synchronization is blocked by a dirty path on main
And no live session has declared the path
And the path was not modified within the current clearance interval
And its uncommitted diff names no todo slug in a pending-doc marker
When the integrator's clearance beat resolves that path
Then it searches this project's session history for the sessions that touched the path
And it sends one message listing the path only to the live sessions that search found
And the message tells each recipient to arm halt-to-respond first when it was in the middle of work, then to commit a path of its own that is ready and released for commit or reply that it is still working on it, and otherwise to end its turn with NOOP
And no other session receives it
And the path is never sent again to the same recipient
And when the path is still dirty, still unmodified within the interval, and claimed by no one on a later beat, the integrator commits it as-is under a message naming it as stranded work
And it reverts the path instead only when session history clearly shows the work was abandoned
And the integrator never stashes, overwrites, or rebases across the path
```

#### UC-WISM37: A dirty path carrying a pending-doc marker is resolved through its todo's prepare orchestrator

```gherkin
Given a dirty path on main whose uncommitted diff adds a pending-doc marker naming a todo slug
When the integrator's clearance beat resolves that path
Then it identifies the todo's prepare orchestrator from the todo's state
And when that session is live it receives the path under the same message as every asked writer
And when that session is gone the integrator reads its transcript and the todo's state and resolves the path from that evidence
And it commits the path as-is unless the named todo is removed or delivered and the transcript shows the work was abandoned, in which case it reverts the path
```

#### UC-WISM38: Only a claimed path left uncommitted or an unintelligible diff reaches the human

```gherkin
Given a dirty path on main that blocks synchronization
When an owner or claimant leaves the path uncommitted for three consecutive clearance beats after it was messaged or claimed
Or the path's diff cannot be interpreted
Then the integrator escalates that path to the human once
And it leaves the path untouched and holds as its blocker beacon
And other dirty paths continue through their own resolution
And the clearance reminder is cancelled only when every remaining dirty path has been escalated
```

#### UC-WISM40: A declared dirty path is routed to its owner alone

```gherkin
Given repo-root synchronization is blocked by a dirty path on main
And a live session has declared that path
When the integrator's clearance beat resolves that path
Then it identifies the owner from the ownership query without searching session history
And it sends that owner one message listing all of its blocking paths
And no other session receives a message about the path
And the owner is never sent the same path again
```

#### UC-WISM29: A drained singleton parks on its queue watcher

```gherkin
Given the singleton integrator completes a drain with no eligible candidate remaining
When the state machine returns its queue-empty outcome
Then the outcome instructs the integrator to inspect canonical local main for direct commits ahead of origin/main
And any such head is published after its owed maintenance and any live-runtime log judgment are complete
And other sessions' review state and unrelated uncommitted paths do not delay that push
And the integrator verifies origin/main contains the committed head before parking
And the outcome instructs the integrator to arm recurring `integrator-queue-watch`
And the profile checks the queue every 15 minutes by default while parked
And it does not reuse dirty-main clearance or candidate-settledness for that wait
And a firing that finds a candidate cancels the queue watcher before continuing the drain
And an empty queue leaves the watcher live until an explicit lifecycle condition cancels it
```

#### UC-WISM39: The integration worktree cannot delete origin/main

```gherkin
Given an agent session working in the integration worktree, where candidate-commit publication to origin/main is admitted
When the session pushes a deletion of the main branch to origin
Then the push is refused, and the refusal is never reported as a content-gate failure
And origin/main is unchanged
```

#### UC-WISM41: Park a held clean uncommitted attempt

Actor: Integrator agent

```gherkin
Given the current attempt has a clean squash and a held todo
And integration HEAD equals its recorded pre-merge SHA
When the integrator explicitly invokes integrate with --abandon
Then the machine restores only its integration worktree to that frozen SHA
And records the candidate as parked for held uncommitted recovery
And preserves the candidate branch, todo and hold without delivery
And continues the drain while the held todo remains excluded
```

The same request refuses an unheld, conflicted or committed attempt without
discarding its stage. Parking does not reset finalize or review state: an
authentic work orchestrator owns the subsequent grounded kickback before hold
release. The bounded recovery is agent-owned under `general/policy/human-contract`.

### Cross-context references

- `agent_runtime` — receives fire-and-forget lifecycle events: `integration.started`, `integration.candidate.dequeued`, `integration.candidate.already_merged`, `integration.merge.succeeded`, `integration.merge.conflicted`, `integration.candidate.committed`, `integration.push.succeeded`, `integration.push.rejected`, `integration.candidate.delivered`, `integration.candidate.blocked`, `integration.candidate.parked`, `integration.drain.completed`.

- `workflow` — delivery bookkeeping records the delivery commit; the todo-delivered event is emitted by the workflow context after push succeeds.
- `operations` — `telec todo integrate` returns an operation receipt; the integrator runs inside the operation runner so failures surface through operation status.

- `workflow.lifecycle_runner` — observes workflow wake-up events only to
  re-evaluate prepare/work candidates and downstream dependencies. It does not
  spawn or inline the integrator for `finalize_ready`; the
  phase-advanced finalize-ready handoff remains owned by
  the integration trigger consumer plus the integrator singleton lease. When
  the todo-delivered event fires, the runner may re-evaluate dependents whose
  work gates are now satisfied.

<!-- planned:reviewed-pr-contributions -->

### Contribution delivery boundary

The mainline state machine described above serves upstream-authoring delivery.
A contributor checkout's finalize-ready handoff is consumed by
`local/projects/teleclaude/spec/feature/workflow/contribution-export`, which
records a PR proposal rather than entering the candidate-push/root-fold path.
PR creation neither records upstream delivery nor releases its sole recoverable
source. An upstream-adopted contribution reaches this state machine only with
its local lifecycle evidence and owned documentation reconciled under
`local/projects/teleclaude/spec/feature/workflow/contribution-adoption`.
<!-- /planned:reviewed-pr-contributions -->

## Known caveats

- The integrator is the only writer authorized to push `origin/main`. Worker sessions on per-slug branches push their feature branches only; main is reachable solely through this state machine.
- Two already-merged guards exist because squash merges do **not** create ancestry edges between the source branch and the merge commit. The ancestry check catches non-squash re-queues; the empty-staged-diff check catches squash re-queues. Both are required.
- The integration worktree prepares and publishes the candidate commit. That confirmed push is intermediate evidence and does not release dependencies. Repository-root main owns the sole documentation fold, the final content gate, the final push, and the recorded delivery SHA.
- Repository-root main may contain committed work ahead of the intermediate candidate push. That committed state remains part of finalization. Any graph, conflict, or dirty-path condition that prevents safe synchronization or reconciliation blocks delivery and leaves uncommitted work untouched.
- When the idle step is called with an explicit slug, only that slug is verified as ready; the FIFO scan is bypassed but ancestry and remote-branch existence checks still apply.
- The normal enqueue path is event-triggered: the phase-advanced event (with `phase=finalize_ready` in its data) invokes the integration trigger cartridge, which spawns the singleton integrator only when no integrator session is open. Open integrators are left undisturbed and consume queued candidates on their next state-machine pass. The scanner remains the recovery path for missed events.
- Legacy entries are normalized so older persisted `finalize.status="handed_off"` reads back as `finalize.status="ready"` and is picked up by the same rule.

- The loop limit exists so multi-phase advances (e.g., COMMITTED → DELIVERY_BOOKKEEPING → PUSH_SUCCEEDED → CLEANUP → CANDIDATE_DELIVERED → IDLE → next candidate) can complete in one call without forcing the agent back through `telec todo integrate` repeatedly.

- The phase enum's AWAITING_COMMIT value is reachable but typically not written; MERGE_CLEAN and MERGE_CONFLICTED are written directly and re-entry handling treats all three equivalently.

- A content-gate rejection is distinguished from a fast-forward-race rejection (remote moved; rebase-recoverable) by the pre-push content-gate marker in the rejection output. The pre-push gate remains authoritative and blocking. The integrator fixes a finding it can ground and re-pushes; when it cannot ground the finding, it parks the candidate and continues the drain through independent work. No candidate is delivered past the failed gate.

- A textual merge conflict the integrator cannot ground a confident resolution for is parked rather than halted: the candidate is set aside with a recorded reason, its transitive dependents are excluded, and the drain continues through the remaining independent candidates (UC-WISM19–UC-WISM21). Parking is a per-drain, in-checkpoint set-aside — `finalize.status` is not retracted, so a later drain re-attempts the candidate (UC-WISM23). This park path is distinct from the content-gate halt above, which is unchanged.

- Lifecycle event emission is fire-and-forget; event delivery failure never blocks integration progress and is only logged at debug level.

## See Also

- docs/local/adr/0090-root-fold-finalizes-a-pushed-candidate.md — why a confirmed candidate push precedes repository-root folding and the final delivery push.
- docs/local/adr/0091-published-candidate-finalization-blocks-the-drain.md — why parking ends once candidate publication is confirmed.
- docs/local/adr/0082-candidate-span-ownership-inspection-is-withdrawn.md — why span-ownership inspection was removed rather than corrected.
- docs/local/adr/0076-integrator-parks-blockers-and-keeps-quality-gating.md — the park-and-drain decision, whose conflict and content-gate paths are unchanged.
- docs/local/adr/0100-commit-maintenance-drains-after-hook-return.md — why the integrator records owed maintenance without waiting for every action.
