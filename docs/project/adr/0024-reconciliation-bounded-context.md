---
adr_status: 'accepted'
date: '2026-06-11'
description: 'Keeping a fleet of installations converged to a desired state (version, schema, health, upkeep) is its own bounded context — reconciliation — not part of integration. Integration owns foreign-protocol boundaries; reconciliation owns the control loop that drives actual state toward desired state and guards cross-version fleet interop.'
number: '24'
visibility: 'public'
---

# ADR-0024: Reconciliation Is a Bounded Context, Separate From Integration — ADR

## Context

The platform runs as a small fleet of installations on different machines and channels — a developer laptop on `alpha`, a Mac mini on `beta`, friends' machines and a Raspberry Pi on `stable`. Something must keep each installation converged to its desired state: the newest release on its channel, an up-to-date schema, a healthy running daemon, and routine upkeep. In v1 this responsibility was smeared across a deployment webhook handler, a bespoke `deployment:version_available` Redis fan-out, and a localhost-bound API server. It never functioned end to end (see ADR-0028).

The question this forced: which bounded context owns "keep actual state equal to desired state across the fleet"?

The instinct was to file it under `integration`. Integration's own change-axis test refutes that. Integration is defined by *foreign* boundaries — protocols and formats controlled by systems we do not own: "when Telegram's webhook format changes, integration changes." Self-update logic does not change when GitHub's webhook shape changes; it changes when *our* channel policy, *our* update procedure, or *our* desired-state model changes. Those are rules about our own fleet, on a different change axis. Folding them into integration makes integration a god-context that owns both "parse foreign protocols" and "manage our fleet."

A second observation sharpened the scope: the fleet is *deliberately* multi-version. `alpha` is always ahead of `beta` is always ahead of `stable`. Version skew is not a transient rollout window — it is the steady state, permanently. So guaranteeing that differently-versioned nodes keep interoperating is a first-class, continuous concern that needs an owner, and that owner is whatever knows each node's version and capability set.

## Decision

Introduce a new bounded context, **`reconciliation`**, that owns desired-state convergence for the fleet. Its single invariant is *actual → desired*, and every responsibility is a convergence concern:

- **Version** — converge each installation to the newest release on its channel (`alpha` / `beta` / `stable`), exactly once, restarting healthy.
- **Schema (installation-level)** — run the ordered structural release migrations between versions.
- **Health** — keep the daemon running and healthy; converge by restart.
- **Upkeep** — scheduled maintenance tasks. This context absorbs the orphaned `next-maintain` lifecycle phase, which becomes the orchestration entry point that hands off to reconciliation.
- **Fleet interop** — own the fleet capability/version map (which node runs which version and advertises which feature-IDs), the authoritative input to "is it safe to require or remove a capability yet?" (see ADR-0026, ADR-0027).

Context relationships:

- **Customer-Supplier downstream of `integration`** — integration terminates and normalizes external webhooks and publishes a cluster-visible event; reconciliation *subscribes* and reconciles. Reconciliation never touches transport or provider protocols.
- **Customer-Supplier downstream of `config`** — config supplies desired-state inputs (channel, `pinned_minor`, health definitions).
- Rides the **event-bus CLUSTER scope** as infrastructure; does not own it.

Reconciliation does NOT own: per-aggregate data schema evolution (each domain owns its own upcasters on a shared kernel — see ADR-0025); agent-artifact authoring or distribution (`agent_artifacts` keeps `telec sync`); product/work lifecycle (`workflow`).

The name is `reconciliation` because the domain *is* a control loop, the same shape Kubernetes calls a reconciler. "deployment" was rejected as too narrow (it omits health/upkeep/migration); "maintenance" reads as chores on first encounter; "lifecycle" collides with `workflow`'s todo-lifecycle vocabulary.

## Consequences

**Positive:**

- Clean change-axis separation: foreign-protocol ingress stays in `integration`; fleet convergence policy lives in `reconciliation`. Neither becomes a god-context.
- The deliberately-multi-version fleet gains a single owner for cross-version interop and the capability map.
- The bespoke `deployment:version_available` fan-out and its self-update-gating bug (the fan-out only fired if the ingress itself updated) retire in favour of integration-publishes / reconciliation-subscribes.
- The orphaned `next-maintain` phase finds a home, turning a vocabulary overlap into a real trigger→target relationship.

**Negative:**

- Reconciliation needs an always-on runtime to host its loop. On the v2 Rust track this is the first long-running Rust process and its supervision (see ADR-0028 and the `rust-daemon-runtime` delivery).
- A new bounded context to specify and maintain. Justified: the responsibility is real, cohesive, and currently ownerless.

## Alternatives Considered

**Keep it inside `integration`.** Rejected: violates integration's own change-axis definition and makes it a god-context owning both foreign protocols and fleet policy.

**Name it `deployment`.** Rejected: too narrow. The domain covers health, upkeep, and migration convergence, not just shipping code.

**Name it `maintenance`.** Considered seriously — it matches the "keep the desired state actual" intent and would absorb `next-maintain`. Rejected as the primary name because the default reading is "housekeeping chores," which undersells the version-convergence core; `reconciliation` names the control loop precisely. `maintenance` survives as the name of one capability (scheduled upkeep) inside the context.

**Name it `lifecycle`.** Rejected: `workflow` already owns "lifecycle" (the `lifecycle_phase` enum, prepare/work/integrate). A second meaning would corrupt the ubiquitous language.
