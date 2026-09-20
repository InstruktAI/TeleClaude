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

#### UC-PCM6: An integration merge or fast-forward performs maintenance

```gherkin
Given integration advances canonical main by merge or fast-forward
And the advanced range resolves deterministic maintenance actions
When the canonical-root advancement completes
Then the actions execute from the canonical checkout without an agent instruction
And the structured records contain a terminal outcome for every action
But the integration worktree performs no maintenance action
```

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
And every action command and outcome carries that same normalized activation range
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

## See Also

- docs/project/adr/0087-mechanical-maintenance-executes-in-a-hook.md — the decision this contract realizes.
- docs/project/design/architecture/checkpoint-system.md — the matcher and registry this surface consumes.
- docs/project/spec/feature/reconciliation/project-plumbing-convergence.md — which hooks a project has installed, and when.
