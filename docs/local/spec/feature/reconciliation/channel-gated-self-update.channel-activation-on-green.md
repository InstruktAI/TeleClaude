---
visibility: 'public'
description: 'Each installation follows the repository and channel it is configured with (edge / stable), activates every admitted revision that breaks nothing exactly once without operator action, and hands a breaking release to its integrator.'
---

# Channel-Gated Self-Update — Spec

## Required reads

- @docs/local/spec/domain/reconciliation.md

## What it is

The behavioral contract for how an installation keeps its own running version current. Each installation follows a **source** — a repository, upstream or a fork — on a **channel**; whenever the source offers a newer revision the channel admits, the installation converges to the newest one, applies it exactly once, and returns to a healthy running state, with no operator command. A release that breaks compatibility is not applied automatically: it goes to the installation's integrator. The contract is stated in behavior, independent of how revisions are detected, fetched, built, or restarted; any implementation (current or future) must satisfy it.

**Business value:** a fleet of machines — the maintainer's laptop, friends' computers, an always-on appliance — stays current automatically and safely, each at the stability level its owner chose. A machine following main only ever runs code that passed CI; a machine following releases takes every compatible release by itself and has a breaking one carried out for it. Nobody runs manual upgrades, a contributor's fork works the same way as upstream, and no machine receives a revision its channel has not admitted.

## Canonical fields

### Source and channel

An installation follows one source and one channel. Both are the installation's own setting, and neither is a property of a particular machine or of the upstream repository: the source is the repository the installation was installed from (`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`), and the channel is declared in its configuration (`local/projects/teleclaude/spec/feature/config/stable-channel-pinning-rule`). Only the followed source's changes and releases can start convergence.

- **edge** — follows the source's main line and converges only to a revision announced green: every required check of the source has passed on it (`local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`). It always converges to the newest green revision: activation begins when the install stops the daemon, and a green revision that a newer one overtakes before its activation begins is never activated. A revision with a red or missing required check is never selected. Edge revisions carry no release classification, so every selected edge revision converges automatically. While no green revision newer than the active release is known, the installation stays on its active release and its status names why it is not advancing. An installation learns its source's green revisions and releases whether or not it is in the cluster that receives the source's webhooks.
- **stable** — follows the source's published releases. A release within the active release's compatibility series — the same minor while the major is zero, and the same major from 1.0 onward — converges automatically. Release classification owns the compatibility promise (`local/projects/teleclaude/spec/release-inspector-prompt`).

### Breaking releases

A published release that crosses the active release's compatibility series never converges automatically. Reconciliation hands it to the installation's integrator, which carries out the release's upgrade instructions and then installs it through the same install act (`sdlc/procedure/maintenance/breaking-release-upgrade`); a person is involved only for what only a person can supply (`general/policy/human-contract`). The installation keeps its active release until that install completes. Every installation has an integrator for this, including one with no development checkout beside it.

### Installing the selected revision

Convergence installs its selected revision into the installation through the
install act of
`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`; it
never moves a project checkout. An edge target is installed as a release in
the same way as a published release. The reaction to the followed source's
changes, releases and green announcements is the installation's own, served by
its running daemon, whether or not a project checkout of the platform is
registered on the machine.

### Supported release transitions

A source advance selects a strictly later revision whose committed history
contains the active release's source; for a published release its committed
version is also later. Repeating the exact active revision changes nothing. An
older announcement already contained in the active release's history leaves
the installation unchanged. Other backward or sideways transitions remain
incomplete, keep the active release, and report the unmet condition. Channel
enrollment supplies no missing data transition. Data preservation follows
`sdlc/policy/backward-compatibility-hygiene`.

A resumed transition uses its retained original source and immutable target.
Convergence is complete only when the install of its target completes; it
retains its pending evidence when that install is refused or fails, and the
install's outcomes are owned by
`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`.

### Release identity

A release is adopted at exactly the revision its tag names.

### Use cases

#### UC-CSU-1: Edge converges to the newest green mainline revision

```gherkin
Scenario Outline: An edge installation follows its source's main line
  Given an operator's installation is enrolled on the edge channel
  When <announcement>
  Then the installation's convergence decision is <decision>

  Examples:
    | announcement                                                          | decision                       |
    | a newer mainline revision is announced green                          | converge to that revision once |
    | two revisions are announced green before the first one is activated   | activate the newer one only    |
    | a newer mainline revision has a red or missing required check         | keep the active release        |
```

#### UC-CSU-2: Beta converges on a published release

#### UC-CSU-3: Stable converges within its compatibility series

```gherkin
Scenario Outline: A stable installation meets a published release
  Given an operator's installation on the stable channel runs <installed>
  When published release <candidate> becomes visible
  Then the installation's convergence decision is <decision>

  Examples:
    | installed | candidate | decision                 |
    | 0.8.3     | 0.8.4     | advance to the candidate |
    | 1.8.3     | 1.9.0     | advance to the candidate |
    | 2.3.1     | 2.4.0     | advance to the candidate |
```

#### UC-CSU-4: A target version is applied at most once

#### UC-CSU-5: Convergence ends healthy or reports failure

#### UC-CSU-6: No manual operator action

```gherkin
Given a release exists for an installation's channel
When the installation is running normally
Then convergence happens without any operator command
And the only operator-visible signal in the normal case is that the installation is now on the new version
```

#### UC-CSU-7: Only the followed source moves an installation

```gherkin
Scenario Outline: An installation meets a change of some repository
  Given an operator's installation follows <source>
  When a change or release lands on <repository>
  Then the installation <reaction>

  Examples:
    | source                  | repository                   | reaction                       |
    | the upstream repository | the upstream repository      | considers it under its channel |
    | the operator's fork     | the operator's fork          | considers it under its channel |
    | the operator's fork     | the upstream repository      | does NOT converge              |
    | the upstream repository | another project's repository | does NOT converge              |
```

#### UC-CSU-8: Release adoption selects the exact admitted source

#### UC-CSU-9: A replayed older release cannot reverse convergence

#### UC-CSU-11: An unsupported source transition preserves the installation

#### UC-CSU-12: A failed install leaves convergence incomplete

#### UC-CSU-13: A breaking release reaches the operator's installation through its integrator

```gherkin
Given an operator's installation on the stable channel runs a release
When a release crossing its compatibility series is published by its source
Then the installation does not install that release on its own
And the release is handed to the installation's integrator
And the installation keeps running its active release until that release's install completes
```

### Cross-context references

- Owned by `reconciliation` (`local/projects/teleclaude/spec/domain/reconciliation`); the version-convergence concern of that context.
- The source's changes, releases and green announcements are supplied by `integration` (`local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`, `local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`).
- The channel input, and the migration of earlier enrollments, come from `config`; the source is the installation's own kept repository.
- Behaviour across a mixed-version fleet is governed by `local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`.

## Known caveats

- A deliberate enrollment into older source is refused: the install act only
  moves forward, and selecting a channel supplies no backward data migration.
  A release's source posture follows
  `local/projects/teleclaude/spec/feature/reconciliation/release-checkout`.

- **Version-agnostic by construction.** This spec names no transport, language, or build tool. Detection (webhook vs poll), fetch (pull vs download), build, and restart mechanics live in the domain spec and the delivering implementation, not here. The swap test applies: every scenario must hold if the entire implementation is replaced.
- **Exactly-once is per target version, not per signal.** Duplicate or replayed signals are expected and must be absorbed idempotently.
- **"Healthy" is observed from the running daemon.** Convergence completes when the supervised daemon is restored and running on the target version; the contract does not pin the specific probe mechanism.
