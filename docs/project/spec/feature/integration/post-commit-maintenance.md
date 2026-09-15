---
description: Deterministic maintenance runs automatically at the commit boundary, for every committer, performing the actions a commit's changed paths owe and reporting each through the structured logging boundary.
visibility: internal
delivered_by:
  - post-commit-hook-runs-mechanical-maintenance
---

# Post-Commit Maintenance — Spec

## What it is

A commit's changed paths owe a set of deterministic maintenance actions —
installing the toolchain, reconciling dependencies, restarting the daemon,
reloading the terminal interface, and running the documentation and artifact
pipeline. Those actions carry no decision: each either ran or it did not.

Maintenance runs automatically at each boundary that advances the canonical
checkout: a commit recorded there, or an integration delivery that
fast-forwards canonical main. It is not addressed to a session and does not
depend on one existing, so a person committing by hand and an integrator
delivery receive the same maintenance.

The owed set is resolved by the checkpoint scope matcher from the merged
action registry and bindings
(`project/design/architecture/checkpoint-system`, Invariant 25). This
surface is one of that matcher's consumers; it recreates no location rule of
its own and holds no second table of paths, actions, or commands.

Which hooks a project has installed, and when they are installed, belongs to
`project/spec/feature/reconciliation/project-plumbing-convergence`. This
contract governs only what happens when maintenance runs.

## Canonical fields

- **Trigger.** A recorded commit on canonical main, or an integration delivery
  that advances canonical main. Maintenance is not conditioned on who or what
  made the commit, nor on whether a session is present.
- **Owed set.** The `main_only` maintenance actions the committed paths
  resolve to under the merged registry and bindings, performed in the
  registry's declared precedence order. An action the registry does not mark
  executable is not performed here and remains an agent obligation.
- **Location.** Maintenance performs the owed `main_only` actions only from the
  canonical checkout on the main branch. The integration worktree supplies the
  delivered range but never executes maintenance; a commit recorded anywhere
  else performs none.
- **Reporting.** Every attempt and every outcome is emitted through the
  structured logging boundary, carrying the commit, the resolved action set,
  and each action's result. The record, not an inference over a transcript, is
  what establishes whether maintenance ran.
- **Failure posture.** The commit is already recorded before maintenance
  begins. A failing action is reported and the remaining actions still run;
  no failure withdraws, amends, or blocks the commit.
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

#### UC-PCM6: An integration delivery performs maintenance from canonical main

```gherkin
Given an integration delivery advances canonical main by fast-forward
And the delivered range resolves deterministic maintenance actions
When the delivery is recorded
Then the actions execute from the canonical checkout without an agent instruction
And independent actions proceed despite another action failing
And the structured records contain a terminal outcome for every action
But the integration worktree performs no maintenance action
```

## See Also

- docs/project/adr/0087-mechanical-maintenance-executes-in-a-hook.md — the decision this contract realizes.
- docs/project/design/architecture/checkpoint-system.md — the matcher and registry this surface consumes.
- docs/project/spec/feature/reconciliation/project-plumbing-convergence.md — which hooks a project has installed, and when.
