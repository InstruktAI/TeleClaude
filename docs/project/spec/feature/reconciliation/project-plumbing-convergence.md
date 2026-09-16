---
description: Convergence of a project's installed git plumbing — the TeleClaude-owned
  hooks and the docs filter driver — to its capability declaration, performed at project
  initialization and by no synchronization path.
visibility: internal
---

# Project Plumbing Convergence — Spec

## What it is

A project's installed git plumbing is machine state: the TeleClaude-owned
`pre-commit`, `post-commit`, `post-merge` and `pre-push` hooks under the git
directory and the `teleclaude-docs` filter driver in the repository's own git
config. Neither is tracked by the project, so a clone carries neither.

Convergence is the act of comparing that observed machine state against the
project's capability declaration and performing the sanctioned actions that
close the gap. It is reconciliation's rule. The declaration it reads is
`config`'s published contract
(`project/spec/feature/config/project-capability-manifest`), consumed at the
crossing and never restated here; what the converged plumbing then does — what
the hooks check, what the docs pipeline processes — belongs to the contexts that
own those behaviors.

<!-- planned-change:home-tier-commit-maintenance -->
Convergence runs at project initialization. No synchronization path performs it:
a deploying synchronization installs, refreshes and withdraws nothing, and the
read-only gate touches nothing.
<!-- change:home-tier-commit-maintenance -->
Convergence runs at project initialization for a project, and at machine
installation for the platform home — the repository declaring the global tier,
which holds the person and company homes. No synchronization path performs
either: a deploying synchronization installs, refreshes and withdraws nothing,
and the read-only gate touches nothing.
<!-- /planned-change:home-tier-commit-maintenance -->

## Canonical fields

- **Hooks.** A project receives the TeleClaude-owned hook set when any enabled
  capability or declared binding can resolve an executable action. A hook the
  project authored itself is preserved rather than overwritten. A project with
  no executable binding receives no TeleClaude-owned hook.
- **Filter driver.** The driver is present exactly when the project subscribes
  `docs`. Convergence is two-directional: the driver is installed when `docs` is
  subscribed and removed when it is not, so the act runs regardless of the
  declaration's value.
- **Repair.** Tracked files a checkout left unexpanded, and files still carrying
  a prior filter pattern's residue, are re-checked out so the smudge filter
  applies to them. A locally modified file is left untouched. Repair resolves a
  file's filter attribute, so it runs after the filter attributes are written.
- **No tracked file is written.** Convergence writes only untracked machine
  state. The one project-tracked file TeleClaude ever writes is the
  `.gitattributes` docs-filter line, written additively at adoption by its own
  step and never touched by a later convergence.

### Use cases

#### UC-RPC1: Convergence removes the driver when docs is unsubscribed

```gherkin
Given a project whose git config carries the TeleClaude docs filter driver
And the project's declaration does not subscribe docs
When an agent runs project initialization for that project
Then the docs filter driver is removed from the project's git config
And no project-tracked file is edited
```

#### UC-RPC2: Convergence installs the driver and repairs an unexpanded checkout

```gherkin
Given a project subscribing docs whose filter attributes are written
And whose tracked documentation still holds unexpanded portable references
When an agent runs project initialization for that project
Then the docs filter driver is configured in the project's git config
And those documentation files read as absolute home paths in the working copy
And a file carrying local modifications keeps its local content
```

#### UC-RPC3: Convergence refreshes TeleClaude's hooks and preserves the project's own

```gherkin
Given a project whose enabled capabilities or declared bindings resolve an executable action
And whose installed hooks include hooks TeleClaude owns
And which also carries a hook the project authored itself
When an agent runs project initialization for that repository
Then the TeleClaude-owned hooks are refreshed from their current templates
And the project-authored hook is left in place
```

#### UC-RPC4: A project subscribing neither receives no plumbing

```gherkin
Given a repository whose declaration activates no executable action binding
And whose declaration does not subscribe docs
When an agent runs project initialization for that repository
Then no TeleClaude-owned git hook is installed for it
And no docs filter driver is configured for it
```

<!-- planned:home-tier-commit-maintenance -->
#### UC-RPC7: Machine installation converges the platform home's plumbing

```gherkin
Given the platform home repository, declaring the global tier and holding person and company documentation homes
When the machine installation target runs
Then TeleClaude's hooks and the docs filter driver are installed in the home's git directory when absent
And an installed hook is rewritten only when the content rendered from TeleClaude's hook template differs from what is installed, and is otherwise left untouched
And hooks the home carries that TeleClaude does not own are preserved
And a repeated run with nothing changed writes nothing
```
<!-- /planned:home-tier-commit-maintenance -->

#### UC-RPC6: No synchronization path converges project plumbing

```gherkin
Given a project whose git hooks and docs filter driver are both out of date
When an agent invokes a deploy-mode synchronization for that project
Then no git hook is installed or refreshed
And the docs filter driver is neither configured nor removed
```

## Known caveats

- Convergence is the initialization path's act. Between one initialization and
  the next, a project's installed plumbing can lag a changed hook template; the
  capability declaration itself needs no reinstallation to take effect, because
  the installed plumbing reads it on each invocation.
<!-- planned-change:home-tier-commit-maintenance -->
- The TeleClaude checkout's own hooks and filter driver are additionally
  installed by its machine installation target, which is not a project
  initialization path and carries its own contract.
<!-- change:home-tier-commit-maintenance -->
- The TeleClaude checkout's own hooks and filter driver, and the platform
  home's, are installed by the machine installation target, which is not a
  project initialization path; between one installation and the next the
  home's plumbing can lag a changed hook template exactly as a project's can.
<!-- /planned-change:home-tier-commit-maintenance -->
