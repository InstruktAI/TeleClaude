---
visibility: public
delivered_by:
  - reconciliation-self-update
description: Reconciliation bounded context — the control loop that drives each installation's
  actual state toward its desired state (version per channel, schema, health, upkeep)
  and guards interoperability across a deliberately multi-version fleet.
---

# Reconciliation Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `reconciliation` bounded context owns _desired-state convergence_ for the fleet of installations. Its single invariant is **actual → desired**: every responsibility is a step that drives a divergent installation back to the state its configuration declares. It owns version convergence (self-update to the newest release on the installation's channel), installation-level structural migration, process health, scheduled upkeep, and the fleet capability map that makes a deliberately multi-version fleet interoperate safely.

Reconciliation is a control loop, the shape Kubernetes calls a reconciler. It is _not_ `integration` — integration owns foreign-protocol boundaries (what external systems we do not control send us); reconciliation owns what _we_ do to keep _our_ fleet current, on a different change axis.

This context does NOT own: foreign-protocol ingress or transport (`integration`); per-aggregate data schema evolution (each domain owns its own upcasters on the shared engine); agent-artifact authoring or distribution (`agent_artifacts`); product/work lifecycle (`workflow`).

## Canonical fields

### Ubiquitous language

**Desired state**
: The state an installation's configuration declares it should be in — the newest release on its channel, the current schema, a healthy daemon, completed upkeep. The target of the control loop.

**Actual state**
: The installation's current observed state. Convergence closes the gap between actual and desired.

**Drift**
: A non-zero gap between actual and desired state. Drift triggers a convergence run.

**Convergence / reconcile**
: The act of driving actual state to desired state. Continuous, idempotent, and channel-scoped.

**Channel**
: The desired-state selector for version: `alpha` (newest code, every push to main), `beta` (every published release), `stable` (releases within a pinned minor series). The fleet runs all three at once, by design.

**Pinned minor**
: The `major.minor` series a `stable` installation tracks; releases outside it are ignored.

**Convergence step**
: One ordered action in a version convergence: checkout/build the target, run installation migrations, restart healthy.

**Installation migration**
: An eager, ordered, once-per-host structural migration between releases (DDL, on-disk layout). Distinct from per-aggregate data upcasting, which each domain owns.

**Health**
: The desired condition of the running daemon. Reconciliation converges a crashed or unhealthy daemon by restart.

**Maintenance / upkeep**
: Scheduled convergence tasks (cleanup, rotation, routine checks). Absorbs the `next-maintain` lifecycle phase, which becomes the orchestration entry point handing off to this context.

**Fleet**
: The set of installations across machines and channels that participate in the same cluster.

**Feature-ID**
: A stable, spec-like identifier for a new cross-node behavior — the named "expand" step in cross-version evolution. A node either carries a feature-ID (it implements the behavior) or it does not. A cross-node behavior carries its feature-ID so an unaware node can gate on it.

**Feature-ID registry**
: The authoritative catalog of every declared feature-ID and its `ignorable` / `must_negotiate` mark. It is the source of truth for what a feature-ID means and whether bypassing it when unaware is safe.

**Capability set**
: The set of feature-IDs an installation advertises it supports, plus its version.

**Fleet capability map**
: The cluster-wide aggregation of every node's capability set. The authoritative answer to "has the slowest channel caught up enough to require, or to remove, capability F?"

**Exactly-once convergence**
: An installation applies a given target version at most once; re-receiving the same signal is a no-op. The control loop is idempotent.

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
- **Contains:** the declared feature-ID entries, each with its identifier and `mark` (`ignorable` | `must_negotiate`), plus the registry's carried feature-ID set for this node. The catalog is declared in code and fixed per release; it is not operator-tunable configuration, because each mark is a safety decision reviewed together with the behavior it gates.
- **Invariants:**
  - A feature-ID is stable once declared; its identifier never changes.
  - Every declared feature-ID carries exactly one mark. An `ignorable` feature is safe to bypass when unaware; a `must_negotiate` feature is not.
  - A cross-node behavior carries its feature-ID with the event it rides, so a receiving node gates on it without prior knowledge of the behavior.
  - Graceful-ignore is the default: a node that receives a behavior tagged with an `ignorable` feature-ID it does not carry drops it cleanly — fail-safe ignore, never fail-crash — enforced at the cluster event-bus dispatch on the consuming node.
  - A `must_negotiate` feature is never silently bypassed: the initiating node gates the coordinated interaction on the fleet capability map before it proceeds, and holds to the previously agreed safe behavior until the peer advertises the feature-ID — so no split-brain occurs.
  - A feature-ID is retired — its registry entry and gated path removed — only once the fleet capability map shows every live node on every channel, including the slowest, carries it.
- **Identifier:** singleton — the platform's declared catalog.
- **Lifecycle:** An entry is added in code when a new cross-node behavior ships behind a feature-ID, and removed when the capability map confirms universal carriage on the slowest channel.

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

### Use cases (index of feature specs)

This section is an index. Each entry references a feature spec that owns the
Gherkin acceptance scenarios for one capability touching this context; the
detailed scenarios live in the feature spec, not here.

- **channel-gated-self-update** — `docs/project/spec/feature/reconciliation/channel-gated-self-update.md` — each installation converges to the newest release on its channel (alpha/beta/stable), evaluating each release against its own policy, applying a target at most once, and ending healthy or reporting failure.
- **fleet-cross-version-interop** — `docs/project/spec/feature/reconciliation/fleet-cross-version-interop.md` — a multi-version fleet keeps interoperating: unaware nodes drop ignorable capabilities cleanly, must-negotiate changes hold to prior-safe behavior rather than splitting, and "safe to require / contract feature F" is answered from the fleet capability map's live state.

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
