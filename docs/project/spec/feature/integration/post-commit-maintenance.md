---
description: Deterministic maintenance runs automatically at the commit boundary,
  for every committer, performing the actions a commit's changed paths owe and reporting
  each through the structured logging boundary.
visibility: internal
---

# Post-Commit Maintenance — Spec

## What it is

A canonical-main activation range's changed paths owe a set of deterministic maintenance actions —
installing the toolchain, reconciling dependencies, restarting the daemon,
reloading the terminal interface, and running the documentation and artifact
pipeline. Those actions carry no decision: each either ran or it did not.

Maintenance runs automatically whenever the canonical checkout advances: the
post-commit hook carries a commit recorded there, while the post-merge hook
carries the complete `ORIG_HEAD..HEAD` range activated by either a merge commit
or a fast-forward. It is not addressed to a session and does not depend on one
existing, so a person committing by hand and an integrator delivery receive the
same maintenance.

The owed set is resolved by the shared scope matcher from the merged registry
pair and bindings (`project/design/architecture/checkpoint-system`, Invariant
25). This surface consumes the maintenance registry and recreates no location
rule or second table of paths, actions, or commands.

Which hooks a project has installed, and when they are installed, belongs to
`project/spec/feature/reconciliation/project-plumbing-convergence`. This
contract governs only what happens when maintenance runs.

## Canonical fields

- **Trigger.** A recorded commit on canonical main, or a successful canonical-main
  merge operation, including a fast-forward. Maintenance is not conditioned on
  who or what advanced main, nor on whether a session is present.
<!-- planned:retire-docs-watcher -->
- **Immutable activation range.** Hook ingress resolves symbolic Git names to
  object ids before action selection or logging. An ordinary commit records its
  parent and committed tip; a root commit records an absent parent and its tip;
  a merge or fast-forward records the resolved pre-activation and post-activation
  tips. Changed-file resolution, command expansion, outcomes, and replay all use
  those immutable fields.
<!-- /planned:retire-docs-watcher -->
- **Owed set.** The `main_only` actions the committed paths resolve from the
  maintenance registry and shared bindings. Actions in the same precedence
  wave run concurrently; the next precedence wave starts after every action in
  the prior wave reaches a terminal outcome. A failed action never cancels a
  later wave. Judgment actions live in the checkpoint registry and never enter
  this executor.
- **Location.** Maintenance performs the owed `main_only` actions only from the
  canonical checkout on the main branch. The integration worktree may create the
  delivered commit, but only canonical main's activation range executes
  maintenance; a commit or merge elsewhere performs none.
- **Reporting.** Every attempt and every outcome is emitted through the
  structured logging boundary, carrying the commit, the resolved action set,
  and each action's result. The record, not an inference over a transcript, is
  what establishes whether maintenance ran.
- **Failure posture.** The commit is already recorded before maintenance
  begins. A failing action is reported and the remaining actions still run;
  no failure withdraws, amends, or blocks the commit.
<!-- planned:retire-docs-watcher -->
- **Committed source.** A publication action receives the recorded range that
  selected it and advances only that repository contribution to the range tip.
  Every other repository remains at its previously activated revision until its
  own commit or merge maintenance runs. Working-tree files are never inputs.
- **Recovery.** A failed action is replayed through this executor for its
  original recorded range and action id. Recovery emits the same attempt and
  outcome records as the first run and never substitutes the current working
  tree or a newer head.
<!-- /planned:retire-docs-watcher -->
- **Absence.** A commit made where the hook is not installed performs no
  maintenance and raises no signal. Nothing detects that absence here:
  installed plumbing is machine state whose comparison against the project's
  declaration is already owned by project plumbing convergence, and a second
  detector would make this contract a second owner of that state.

<!-- planned:nonblocking-commit-maintenance -->
- **Quick-return activation.** After resolving an immutable activation and its
  owed action set, the hook records each owed action durably, starts a one-shot
  drain contender, and returns without waiting for action completion. A later
  commit adds its own owed records while an earlier drain is running.
- **Per-action state.** Each gitignored record is keyed by the activated tip
  and action id and retains the pre-activation revision and queued time. A
  confirmed success removes its record. A terminal failure remains marked
  failed for structured-log and anomaly review, without an automatic retry loop.
  An interrupted attempt remains eligible for retry; each action converges
  safely when repeated after its effect preceded record removal.
- **One-shot drain.** Every hook that records owed work starts a contender. One OS-owned file lock
  admits a single active drain; contenders wait for that lock, process pending
  activations in Git ancestry order and actions by declared precedence, then
  exit when no pending work remains. Lock-file presence never means ownership.
- **Observation.** Every attempt and terminal outcome retains the immutable
  activation and action identity in structured records. Operational anomaly
  detection observes failed or stale actions. The existing post-commit
  checkpoint directs the committing or integrating agent to defer its one log
  read until two minutes after the advancement. That read closes the agent's
  log judgment without waiting for restart completion. Maintenance completion
  sends no notification to the committer; anomalies after the read belong to
  the log bug hunter.
<!-- /planned:nonblocking-commit-maintenance -->

### Use cases

#### UC-PCM1: A commit performs the maintenance its changed paths owe

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a commit on the canonical checkout's main branch changing paths that owe deterministic maintenance
When the commit is recorded
Then each owed maintenance action is performed in the registry's precedence order
And an agent reading the structured records observes the commit, the resolved action set, and each action's outcome
```

#### UC-PCM2: A person's own commit receives the same maintenance as a session's

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a person commits the same paths by hand, with no agent session involved
When the commit is recorded
Then the same maintenance actions are performed as when a session commits those paths
And the person is not asked to perform any of them
```

#### UC-PCM3: A commit owing no deterministic maintenance performs none

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a commit changing only paths that owe no deterministic maintenance
When the commit is recorded
Then no maintenance action is performed
And an agent reading the structured records observes that the resolved action set was empty
```

#### UC-PCM4: A failing maintenance action leaves the commit standing

```gherkin
Given a commit that owes more than one deterministic maintenance action
When one of those actions fails
Then the commit remains recorded exactly as it was made
And the remaining owed actions are still performed
And an agent reading the structured records observes which action failed
```

#### UC-PCM5: A commit outside the canonical main checkout performs no main-only maintenance

```gherkin
Given a project whose installed plumbing includes the maintenance hook
And a commit recorded in a todo worktree rather than the canonical checkout's main branch
When the commit is recorded
Then no main-only maintenance action is performed
And the documentation and artifact pipeline is not run from that worktree
And an agent reading the structured records observes that maintenance was skipped, and the location that made it ineligible
```

<!-- planned-change:nonblocking-commit-maintenance -->
#### UC-PCM6: An integration merge or fast-forward performs maintenance

```gherkin
Given integration advances canonical main by merge or fast-forward
And the advanced range resolves deterministic maintenance actions
When the canonical-root advancement completes
Then the actions execute from the canonical checkout without an agent instruction
And the structured records contain a terminal outcome for every action
But the integration worktree performs no maintenance action
```
<!-- change:nonblocking-commit-maintenance -->
#### UC-PCM6: An integration merge or fast-forward performs maintenance

```gherkin
Given integration advances canonical main by merge or fast-forward
And the advanced committed change owes deterministic maintenance
When the canonical-root advancement completes
Then its maintenance is recorded and starts without an agent instruction
And the Git operation returns before long-running maintenance finishes
And each action eventually has a structured terminal outcome
But the integration worktree performs no maintenance action
```
<!-- /planned-change:nonblocking-commit-maintenance -->

<!-- planned:retire-docs-watcher -->
#### UC-PCM7: Publication uses the recorded commit, not later working-tree state

```gherkin
Given a canonical-main commit whose changed paths owe publication
And another registered repository carries source that has not run its own publication action
When commit-boundary maintenance performs the publication action for that recorded range
Then the triggering repository contribution advances to the recorded range tip
And every other repository contribution remains at its previously activated revision
And no unactivated source appears in the generation
```

#### UC-PCM8: Recovery replays the failed action for its original range

```gherkin
Given a recorded commit range whose publication action failed
And repository heads or working trees have changed since that failure
When an agent retries that recorded maintenance action
Then the executor performs publication for the original range and action id
And its structured records identify the replayed range and terminal outcome
And no current working-tree state replaces the original input
```

#### UC-PCM9: A root commit has an immutable activation range

```gherkin
Given a repository whose canonical main has no parent commit
When its first qualifying commit invokes post-commit maintenance
Then maintenance records an absent before revision and the immutable committed tip
And changed-file resolution includes the complete root-commit tree
And an agent reading the structured records observes that same normalized activation range on every action command and outcome
```
<!-- /planned:retire-docs-watcher -->

<!-- planned:home-tier-commit-maintenance -->
#### UC-PCM10: A tier-documentation commit in the platform home owes publication

```gherkin
Given the platform home carries the installed maintenance hook
And a person or company documentation source inside it participates in the documentation surface
When a commit on the platform home's canonical main records a change to that source
Then committed-state publication is included in the maintenance owed by that activation range
And an agent reading the structured records observes the immutable range and the publication action's terminal outcome
But the same path shape in an ordinary project does not acquire a home-only maintenance binding
```
<!-- /planned:home-tier-commit-maintenance -->

<!-- planned:nonblocking-commit-maintenance -->
#### UC-PCM11: A commit returns while maintenance continues

```gherkin
Given a canonical-main commit owes an action that takes longer than the commit itself
When the commit is recorded
Then the Git command returns after handing off the owed action
And the action runs to a separately observable terminal outcome
And the committer receives no maintenance-completion notification
```

#### UC-PCM12: A commit arriving during a drain is not stranded

```gherkin
Given maintenance for one canonical-main advancement is still running
When another advancement records its own owed actions
Then the later actions are processed after the earlier activated state
And neither advancement needs a resident worker or a later commit to trigger processing
```

#### UC-PCM13: An interrupted action is safe to retry

```gherkin
Given one owed action had its effect but was interrupted before success was recorded
And another action for the same activated state already recorded success
When a later maintenance invocation resumes outstanding work
Then the interrupted action converges to its intended state
And the confirmed successful action does not run again
```

#### UC-PCM14: Terminal failure remains visible without a retry loop

```gherkin
Given an owed maintenance action ends in failure
When the drain continues with other owed actions
Then the failed action remains identifiable by its activated state and action identity
And operational anomaly detection can report it
But the drain does not retry that terminal failure indefinitely
```

#### UC-PCM15: The post-commit log judgment is delayed once

```gherkin
Given a canonical-main change owes both daemon restart and live-runtime log judgment
When Git returns before the restart finishes
Then the committing or integrating agent defers its checkpoint log read for two minutes
And that read closes the agent's log judgment without waiting for restart success
And later anomalies remain discoverable by the log bug hunter
But maintenance completion sends no further prompt to the agent
```
<!-- /planned:nonblocking-commit-maintenance -->

## See Also

- docs/project/adr/0087-mechanical-maintenance-executes-in-a-hook.md — the decision this contract realizes.
<!-- planned:nonblocking-commit-maintenance -->
- docs/project/adr/0100-commit-maintenance-drains-after-hook-return.md — why maintenance execution no longer holds Git open.
<!-- /planned:nonblocking-commit-maintenance -->
- docs/project/design/architecture/checkpoint-system.md — the matcher and registry this surface consumes.
- docs/project/spec/feature/reconciliation/project-plumbing-convergence.md — which hooks a project has installed, and when.
