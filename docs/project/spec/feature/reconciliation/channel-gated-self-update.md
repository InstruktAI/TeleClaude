---
visibility: public
delivered_by:
  - reconciliation-self-update
description: Each installation keeps itself on the newest release for its declared
  channel (alpha / beta / stable), applying each target version at most once and
  returning to a healthy running state — without manual operator action.
---

# Channel-Gated Self-Update — Spec

## Required reads

- @docs/project/spec/domain/reconciliation.md

## What it is

The behavioral contract for how an installation keeps its own running version current. Each installation declares a release **channel**; whenever a new release exists, the installation converges to the newest version its channel admits, applies it exactly once, and returns to a healthy running state — with no operator command. The contract is stated in behavior, independent of how releases are detected, fetched, built, or restarted; any implementation (current or future) must satisfy it.

**Business value:** a fleet of machines — the maintainer's laptop, friends' computers, an always-on appliance — stays current automatically and safely, each at the stability level its owner chose. Bleeding-edge machines track every change; cautious machines track only vetted releases within a fixed series. Nobody runs manual upgrades, and a cautious machine never receives an unvetted change.

## Canonical fields

### Channel policy

- **alpha** — converges to the newest mainline code on every change to the main line. Latest, least vetted.
- **beta** — converges on every published release. Tagged releases only.
- **stable** — converges only to releases within its declared pinned minor series (`major.minor`). Releases outside that series are ignored until the owner re-pins.

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

#### UC-CSU-3: Stable converges only within its pinned minor

```gherkin
Given an installation is enrolled on the stable channel with pinned minor 1.2
When release 1.2.5 is published
Then the installation converges to 1.2.5
But when release 1.3.0 is published
Then the installation does NOT converge to it
And remains on its current 1.2.x version until the owner re-pins
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
And if any step fails, convergence halts with a recorded reason
And the installation does not silently come up in a partial or unhealthy state
```

#### UC-CSU-6: No manual operator action

```gherkin
Given a release exists for an installation's channel
When the installation is running normally
Then convergence happens without any operator command
And the only operator-visible signal in the normal case is that the installation is now on the new version
```

### Cross-context references

- Owned by `reconciliation` (`@docs/project/spec/domain/reconciliation.md`); the version-convergence concern of that context.
- The release/version signal is supplied by `integration` via the single-ingress relay (`@docs/project/spec/feature/integration/single-ingress-webhook-termination.md`).
- Channel and pinned-minor inputs come from `config`.
- Behaviour across a mixed-version fleet is governed by `@docs/project/spec/feature/reconciliation/fleet-cross-version-interop.md`.

## Known caveats

- **Version-agnostic by construction.** This spec names no transport, language, or build tool. Detection (webhook vs poll), fetch (pull vs download), build, and restart mechanics live in the domain spec and the delivering implementation, not here. The swap test applies: every scenario must hold if the entire implementation is replaced.
- **Exactly-once is per target version, not per signal.** Duplicate or replayed signals are expected and must be absorbed idempotently.
- **"Healthy" is a desired-state condition, not hardcoded here.** What counts as a healthy running state is observed from the running installation; the contract does not pin the probe.
