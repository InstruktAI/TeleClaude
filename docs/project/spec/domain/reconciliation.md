---
id: project/spec/domain/reconciliation
type: spec
domain: software-development
scope: project
visibility: public
delivered_by:
  - reconciliation-self-update
  - feature-id-registry
description: Reconciliation bounded context — the control loop that drives each
  installation's actual state toward its desired state (version per channel, schema,
  health, upkeep) and guards interoperability across a deliberately multi-version fleet.
---

# Reconciliation Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `reconciliation` bounded context owns *desired-state convergence* for the fleet of installations. Its single invariant is **actual → desired**: every responsibility is a step that drives a divergent installation back to the state its configuration declares. It owns version convergence (self-update to the newest release on the installation's channel), installation-level structural migration, process health, scheduled upkeep, and the fleet capability map that makes a deliberately multi-version fleet interoperate safely.

Reconciliation is a control loop, the shape Kubernetes calls a reconciler. It is *not* `integration` — integration owns foreign-protocol boundaries (what external systems we do not control send us); reconciliation owns what *we* do to keep *our* fleet current, on a different change axis.

This context does NOT own: foreign-protocol ingress or transport (`integration`); per-aggregate data schema evolution (each domain owns its own upcasters on the shared engine); agent-artifact authoring or distribution (`agent_artifacts`); product/work lifecycle (`workflow`).

## Canonical fields

### Ubiquitous language

**Desired state**
:  The state an installation's configuration declares it should be in — the newest release on its channel, the current schema, a healthy daemon, completed upkeep. The target of the control loop.

**Actual state**
:  The installation's current observed state. Convergence closes the gap between actual and desired.

**Drift**
:  A non-zero gap between actual and desired state. Drift triggers a convergence run.

**Convergence / reconcile**
:  The act of driving actual state to desired state. Continuous, idempotent, and channel-scoped.

**Channel**
:  The desired-state selector for version: `alpha` (newest code, every push to main), `beta` (every published release), `stable` (releases within a pinned minor series). The fleet runs all three at once, by design.

**Pinned minor**
:  The `major.minor` series a `stable` installation tracks; releases outside it are ignored.

**Convergence step**
:  One ordered action in a version convergence: checkout/build the target, run installation migrations, restart healthy.

**Installation migration**
:  An eager, ordered, once-per-host structural migration between releases (DDL, on-disk layout). Distinct from per-aggregate data upcasting, which each domain owns.

**Health**
:  The desired condition of the running daemon. Reconciliation converges a crashed or unhealthy daemon by restart.

**Maintenance / upkeep**
:  Scheduled convergence tasks (cleanup, rotation, routine checks). Absorbs the `next-maintain` lifecycle phase, which becomes the orchestration entry point handing off to this context.

**Fleet**
:  The set of installations across machines and channels that participate in the same cluster.

**Feature-ID**
:  A stable, spec-like identifier for a new cross-node behavior — the named "expand" step in cross-version evolution. A node either carries a feature-ID (it implements the behavior) or it does not. A cross-node behavior carries its feature-ID so an unaware node can gate on it.

**Feature-ID registry**
:  The authoritative catalog of every declared feature-ID and its `ignorable` / `must_negotiate` mark. It is the source of truth for what a feature-ID means and whether bypassing it when unaware is safe.

**Capability set**
:  The set of feature-IDs an installation advertises it supports, plus its version.

**Fleet capability map**
:  The cluster-wide aggregation of every node's capability set. The authoritative answer to "has the slowest channel caught up enough to require, or to remove, capability F?"

**Exactly-once convergence**
:  An installation applies a given target version at most once; re-receiving the same signal is a no-op. The control loop is idempotent.

### Aggregates

#### Installation (aggregate)

- **Root:** `InstallationState`
- **Contains:** `computer` (identity), `channel`, `pinned_minor` (when stable), `current_version`, `desired_version`, `health_status`, `applied_installation_migrations`, `advertised_capability_set`.
- **Invariants:**
  - Converges toward `desired_version` for its channel; never updates outside its channel's policy (stable ignores releases outside `pinned_minor`).
  - A target version is applied at most once (exactly-once).
  - A convergence is not complete until the daemon is restarted and healthy on the target version.
- **Identifier:** `computer` (the installation's computer name).
- **Lifecycle:** Exists while the installation's daemon runs; updated on every reconcile.

#### Convergence Run (aggregate)

- **Root:** `ConvergenceRun`
- **Contains:** `run_id`, `from_version`, `to_version`, ordered `steps` (checkout/build → migrate → restart) with per-step status, `outcome` (`converged` | `failed`), `failure_context`.
- **Invariants:**
  - Steps execute in order; a failed step halts the run and records context (no partial silent success).
  - Idempotent: re-running a completed convergence for the same `to_version` is a no-op.
- **Identifier:** `run_id`.
- **Lifecycle:** Created when drift is detected; ends `converged` or `failed`. Retained for operator inspection.

#### Fleet Capability Map (aggregate)

- **Root:** `FleetCapabilityMap`
- **Contains:** per-node entries of `computer`, `version`, `channel`, `capability_set`, `last_advertised_at`.
- **Invariants:**
  - Each entry is self-reported by its node via the cluster heartbeat; no node writes another's entry, and no node reads a peer's config to learn its identity, version, or capabilities — the heartbeat is the only source.
  - "Safe to require / contract feature F" is true only when every live entry on every channel — including the slowest — carries F.
  - Entries age out when a node stops advertising (presumed absent).
- **Identifier:** singleton per cluster view.
- **Lifecycle:** Materialized from the heartbeat stream; entries expire on heartbeat timeout.

#### Feature-ID Registry (aggregate)

- **Root:** `FeatureIDRegistry`
- **Contains:** the declared feature-ID entries, each with its identifier, `mark` (`ignorable` | `must_negotiate`), and the version range it is live in.
- **Invariants:**
  - A feature-ID is stable once declared; its identifier never changes.
  - Every declared feature-ID carries exactly one mark. An `ignorable` feature is safe to bypass when unaware; a `must_negotiate` feature is not.
  - Graceful-ignore is the default: a node that receives a behavior tagged with an `ignorable` feature-ID it does not carry drops it cleanly — fail-safe ignore, never fail-crash — enforced at the cluster event-bus dispatch.
  - A `must_negotiate` feature is never silently bypassed: when a node does not carry it, the interaction holds to the previously agreed safe behavior rather than degrading, so no split-brain occurs.
  - A feature-ID is retired — its registry entry and gated path removed — only once the fleet capability map shows every live node on every channel, including the slowest, carries it.
- **Identifier:** singleton — the platform's declared catalog.
- **Lifecycle:** An entry is added when a new cross-node behavior ships behind a feature-ID, and removed when the capability map confirms universal carriage on the slowest channel.

### Domain events emitted

#### `reconciliation.installation.drift_detected`

- **Producer:** `reconciliation`
- **Emitted when:** actual version/health diverges from desired.
- **Payload:** `computer`, `channel`, `current_version`, `desired_version`, `reason`.
- **Visibility:** CLUSTER
- **Known consumers:** operator dashboards; the local convergence runner.

#### `reconciliation.installation.converged`

- **Producer:** `reconciliation`
- **Emitted when:** an installation reaches desired state and is healthy on the target version.
- **Payload:** `computer`, `channel`, `from_version`, `to_version`, `converged_at`.
- **Visibility:** CLUSTER
- **Known consumers:** operator dashboards; the fleet capability map (version refresh).

#### `reconciliation.convergence.failed`

- **Producer:** `reconciliation`
- **Emitted when:** a convergence run halts on a failed step.
- **Payload:** `computer`, `run_id`, `from_version`, `to_version`, `failed_step`, `failure_context`.
- **Visibility:** CLUSTER
- **Known consumers:** operator alerting.

#### `reconciliation.capability.advertised`

- **Producer:** `reconciliation`
- **Emitted when:** an installation publishes its capability set (on startup and on change).
- **Payload:** `computer`, `version`, `channel`, `capability_set`.
- **Visibility:** CLUSTER
- **Known consumers:** every node's fleet capability map.
- **Transport:** rides the existing cluster heartbeat mechanism, which already advertises per-node identity over Redis. Version and `capability_set` extend that self-reported heartbeat payload rather than introducing a separate distribution path; a node never learns a peer's identity, version, or capabilities by reading the peer's config.

### Domain events consumed

#### `integration.inbox.received` (release/version subset)

- **Producer:** `integration`
- **Reaction:** when the inbound event is a release/version-available signal, evaluate it against this installation's channel policy; on a match, start a convergence run. The event is relayed unconditionally by the ingress; each node decides independently.
- **Failure handling:** evaluation failures are logged; the installation retries on the next signal or periodic self-check.

#### `config.effective.updated`

- **Producer:** `config`
- **Reaction:** re-read desired-state inputs (channel, `pinned_minor`, health definitions); re-evaluate drift.
- **Failure handling:** logged; last-known config remains in force.

### Use cases

#### UC-REC-1: Release on channel triggers convergence

```gherkin
Given installation B is enrolled on the beta channel
And the ingress relays a release-published event onto the cluster bus
When reconciliation on B evaluates the event against its channel policy
Then beta matches any published release
And a ConvergenceRun is created from B's current version to the release version
And the steps run in order: checkout/build the target, run installation migrations, restart
And on a healthy restart reconciliation.installation.converged is emitted
```

#### UC-REC-2: Pure ingress relays; each node reconciles by its own channel

```gherkin
Given the Raspberry Pi is the ingress and is enrolled on stable with pinned_minor 1.2
And it relays a release 1.3.0 onto the cluster bus unconditionally
When the stable Pi evaluates 1.3.0 against its own policy
Then 1.3.0 is outside pinned_minor 1.2 and the Pi does NOT converge to it
And the alpha laptop, consuming the same event, evaluates by its own policy
And no node's decision depends on the ingress's channel
```

#### UC-REC-3: Exactly-once convergence

```gherkin
Given installation A has already converged to version 1.3.0
When A receives the same release-available signal again
Then drift evaluation finds actual == desired
And no second ConvergenceRun is created
And the duplicate signal is a no-op
```

#### UC-REC-4: Health convergence by restart

```gherkin
Given the daemon on installation C exits or becomes unhealthy
When the service manager relaunches it (desired = running healthy)
Then reconciliation re-evaluates actual against desired on startup
And advertises its capability set
And resumes the loop with no manual operator action
```

#### UC-REC-5: Capability map answers "safe to contract"

```gherkin
Given a feature-ID F was introduced on alpha and is being phased toward removal
When reconciliation is asked whether F may be contracted
Then it consults the fleet capability map
And returns true only if every live node on every channel — including the slowest, stable — advertises F
Otherwise it returns false and F's gated path must remain
```

#### UC-REC-6: A stable node ignores an alpha-only capability gracefully

```gherkin
Given alpha emits an event tagged with an ignorable feature-ID the stable node does not carry
When the stable node receives it
Then the event is dropped cleanly (fail-safe ignore, not fail-crash)
And the stable node continues operating
And no convergence or error results from the unknown capability
```

#### UC-REC-7: A must-negotiate capability refuses rather than splits

```gherkin
Given a feature-ID marked must_negotiate gates a coordination change
And one node carries it while the interacting peer does not
When the two nodes interact
Then the change is not silently bypassed by the unaware node
And the interaction holds to the previously agreed safe behavior until both sides carry the feature-ID
And no split-brain results
```

### Context map position

- **Customer-Supplier downstream of `integration`** — consumes the relayed, normalized inbound release/version events; never touches transport or provider protocols.
- **Customer-Supplier downstream of `config`** — desired-state inputs (channel, `pinned_minor`, health definitions).
- **Rides the event-bus CLUSTER scope** — emits and consumes cluster-visible events; does not own the bus.
- **Trigger relationship with `workflow`** — the `next-maintain` lifecycle phase is the orchestration entry point that hands off to this context's upkeep convergence; the phase is the trigger, reconciliation is the target.
- **No relationship with per-domain data evolution** — each domain owns its own upcasters; reconciliation owns only installation-level structural migration.

## Allowed values

- `channel`: `alpha`, `beta`, `stable`.
- `convergence step`: `checkout_build`, `migrate`, `restart`.
- `convergence outcome`: `converged`, `failed`.
- `health_status`: `healthy`, `unhealthy`, `restarting`.
- `feature-ID mark`: `ignorable`, `must_negotiate`.

## Known caveats

- **The fleet is deliberately multi-version, permanently.** alpha leads, beta trails, stable trails further. Cross-version interop is a continuous first-class invariant, not a transient rollout window. This is why the capability map and the compatibility contract live in scope.
- **The ingress is a single point of external-event intake.** While it is down the fleet processes no external events but is not broken; a periodic self-check or a second stateless ingress recovers the gap.
- **Cluster pub/sub is fire-and-forget.** A node offline when a release event publishes misses it; recovery is the next release signal or a periodic desired-state self-check, not event replay.
- **Installation migration is distinct from data upcasting.** This context owns the eager, ordered, once-per-host structural migration; per-record data evolution is each domain's own lazy upcasting. Do not conflate them.
- **Fleet identity is heartbeat-advertised, never config-sourced.** Each node's identity, version, and capability set reach the cluster through the Redis heartbeat, which already carries per-node `ComputerInfo`. The fleet capability map consumes that stream. A node reads its own local config only to know itself; it never reads a peer's config, and reconciliation introduces no separate identity distribution path.

## See Also

- docs/project/adr/0013-unified-cluster-events.md
- docs/project/adr/0024-reconciliation-bounded-context.md
- docs/project/adr/0025-two-layer-migration-model.md
- docs/project/adr/0026-cross-version-fleet-compatibility.md
- docs/project/adr/0027-feature-id-capability-gating.md
- docs/project/adr/0028-single-lan-bound-ingress.md
