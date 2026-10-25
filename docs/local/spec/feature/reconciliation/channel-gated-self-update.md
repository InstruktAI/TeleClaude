---
visibility: 'public'
description: 'Each installation keeps itself on the newest release for its declared channel (alpha / beta / stable), applying each target version at most once and returning to a healthy running state — without manual operator action.'
---

# Channel-Gated Self-Update — Spec

## Required reads

- @docs/local/spec/domain/reconciliation.md

## What it is

The behavioral contract for how an installation keeps its own running version current. Each installation declares a release **channel**; whenever a new release exists, the installation converges to the newest version its channel admits, applies it exactly once, and returns to a healthy running state — with no operator command. The contract is stated in behavior, independent of how releases are detected, fetched, built, or restarted; any implementation (current or future) must satisfy it.

**Business value:** a fleet of machines — the maintainer's laptop, friends' computers, an always-on appliance — stays current automatically and safely, each at the stability level its owner chose. Bleeding-edge machines track every change; cautious machines track only vetted releases within a fixed series. Nobody runs manual upgrades, and a cautious machine never receives an unvetted change.

## Canonical fields

### Channel policy

- **alpha** — converges to the newest mainline code on every change to the main line. Latest, least vetted.
- **beta** — converges on every published release. Tagged releases only.

- **stable** — converges to later published releases within the selected compatibility series: the same minor while the major is zero, and the same major from 1.0 onward. Crossing that boundary requires explicit enrollment in the next series. Configuration owns the series declaration (`local/projects/teleclaude/spec/feature/config/stable-channel-pinning-rule`); release classification owns the compatibility promise (`local/projects/teleclaude/spec/release-inspector-prompt`).

### Supported release transitions

A beta or stable source advance selects a strictly later release whose committed
history contains the installed source. Repeating the exact selected release
normalizes its checkout posture without changing source. An older announcement
already contained in the installed history leaves the installation unchanged.
Other backward, sideways or locally diverged source transitions remain
incomplete, retain the current checkout and local history, and report the unmet
condition. Channel enrollment supplies no missing data transition. Source and
data preservation follow `sdlc/policy/version-control-safety` and
`sdlc/policy/backward-compatibility-hygiene`.

A resumed transition uses its retained original source and immutable target.
Reaching the target commit does not by itself complete the handoff to maintenance.
Convergence retains its pending evidence when that handoff is refused or fails;
only an explicitly recorded owed set or an explicitly empty owed set completes
the recording step. Workflow owns those recording outcomes under
`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`.

### Use cases

#### UC-CSU-1: Alpha converges on every mainline change

```gherkin
Given an installation is enrolled on the alpha channel
When a new change lands on the main line
Then the installation converges to that newest mainline version
And applies it exactly once
And returns to a healthy running state on the new version
```

#### UC-CSU-2: Beta converges on a published release

```gherkin
Given an installation is enrolled on the beta channel
When a release is published
Then the installation converges to that release version
And mainline changes that are not published releases do NOT trigger convergence
And it returns to a healthy running state on the release
```

#### UC-CSU-3: Stable converges within its selected compatibility series

```gherkin
Scenario Outline: A stable installation admits a published release
  Given an operator's installation runs <installed> in compatibility series <series>
  When published release <candidate> becomes visible
  Then the installation's convergence decision is <decision>

  Examples:
    | installed | series | candidate | decision                           |
    | 0.8.3     | 0.8    | 0.8.4     | advance to the candidate           |
    | 0.8.3     | 0.8    | 0.9.0     | retain the installed release       |
    | 0.8.3     | 0.8    | 1.0.0     | retain the installed release       |
    | 1.8.3     | 1      | 1.9.0     | advance to the candidate           |
    | 1.8.3     | 1      | 2.0.0     | retain the installed release       |
    | 2.3.1     | 2      | 2.4.0     | advance to the candidate           |
```

#### UC-CSU-4: A target version is applied at most once

```gherkin
Given an installation has already converged to a target version
When the same release becomes visible again
Then the installation recognizes it is already at the desired version
And performs no second update
```

#### UC-CSU-5: Convergence ends healthy or reports failure

```gherkin
Given an installation begins converging to a target version
When the convergence steps run in order
Then the installation is not considered converged until it is running and healthy on the target version
And a step that fails is recorded with its reason and leaves convergence incomplete until an agent replays it
And the installation does not silently come up in a partial or unhealthy state
```

#### UC-CSU-6: No manual operator action

```gherkin
Given a release exists for an installation's channel
When the installation is running normally
Then convergence happens without any operator command
And the only operator-visible signal in the normal case is that the installation is now on the new version
```

#### UC-CSU-7: Another project's changes never update the platform

```gherkin
Given another project relays the changes and releases of its own repository to the platform
And an installation is enrolled on any channel
When a change lands on that project's main line or that project publishes a release
Then the installation does NOT converge
And only a change or release of the platform's own repository can start convergence
```

#### UC-CSU-8: Release adoption selects the exact admitted source

```gherkin
Given an operator's installation has selected an eligible published release
And the installed checkout differs from that release
When release activation completes
Then the installed source is the selected release revision
```

#### UC-CSU-9: A replayed older release cannot reverse convergence

```gherkin
Given an operator's installation has adopted a newer eligible release
When an older release announcement is replayed
Then the installed revision remains unchanged
```

#### UC-CSU-11: An unsupported source transition preserves the installation

```gherkin
Scenario Outline: Refusing unsupported release source
  Given a beta or stable installation with a retained installed source
  And a channel-eligible release would require <transition>
  When the installation attempts that release transition
  Then the current source and local branch history remain unchanged
  And convergence reports the unmet condition without claiming success
  And its pending transition remains available for recovery

  Examples:
    | transition                                            |
    | a non-ancestor release with an older version           |
    | a newer release on a separate source history          |
    | leaving attached main with unpublished divergent work |
    | a different source with a non-increasing version      |
```

#### UC-CSU-12: A refused maintenance handoff leaves convergence incomplete

```gherkin
Given an admitted release transition has reached its retained target commit
When recording its owed activation maintenance is refused or fails
Then convergence reports that failure and retains its pending transition
And it does not report the transition as complete
And a later replay uses the same original source and target identity
```

### Cross-context references

- Owned by `reconciliation` (`@docs/local/spec/domain/reconciliation.md`); the version-convergence concern of that context.
- The release/version signal is supplied by `integration` via the single-ingress relay (`@docs/local/spec/feature/integration/single-ingress-webhook-termination.md`).

- Channel and compatibility-series inputs come from `config`.

- Behaviour across a mixed-version fleet is governed by `@docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md`.

## Known caveats

- A deliberate enrollment into older source needs a supported data transition;
  unsupported transitions leave the current installation intact and report the
  unmet condition. Selecting a channel alone supplies no backward data migration.
  Installed/development source selection follows
  `local/projects/teleclaude/spec/feature/reconciliation/release-checkout`.

- **Version-agnostic by construction.** This spec names no transport, language, or build tool. Detection (webhook vs poll), fetch (pull vs download), build, and restart mechanics live in the domain spec and the delivering implementation, not here. The swap test applies: every scenario must hold if the entire implementation is replaced.
- **Exactly-once is per target version, not per signal.** Duplicate or replayed signals are expected and must be absorbed idempotently.
- **"Healthy" is observed from the running daemon.** Convergence completes when the supervised daemon is restored and running on the target version; the contract does not pin the specific probe mechanism.
