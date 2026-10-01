---
date: '2026-06-11'
description: 'A deliberately multi-version fleet (alpha ahead of beta ahead of stable, permanently) keeps interoperating only by an engineered contract, not by SemVer labels: schema-versioned event envelopes, tolerant readers as law, wire upcasters for non-additive changes, and expand/contract gated on the slowest channel. Automating deployment without this contract amplifies breakage rather than preventing it.'
number: '26'
visibility: 'public'
---

# ADR-0026: Cross-Version Fleet Compatibility Contract — ADR

## Context

The fleet is permanently multi-version by design: `alpha` leads, `beta` trails, `stable` (friends, Raspberry Pi) trails further. The shared substrate between heterogeneous nodes is Redis — the `cluster.*` and `workflow.*` event channels (ADR-0013), streams, leases, and any direct session-to-session calls. Per-machine SQLite/Postgres is not shared, so the blast surface for cross-version breakage is the event bus and direct RPC, not local storage.

SemVer plus the `alpha`/`beta`/`stable` channels is a _labeling_ convention. It communicates "this is breaking" to humans; it enforces nothing on the wire. Today the machinery is absent: the v2 `EventEnvelope` carries `channel, idempotency_key, emitted_at, principal, payload` and **no schema version**; the v1 fan-out consumer `from_json`s an event and dispatches it, so a field-shape change throws. As it stands, an `alpha` breaking change _would_ reach a friend's `stable` box and break it.

This reframes the deployment work: once auto-install is reliable, it becomes a fast, reliable machine for pushing `alpha`'s breaking changes onto `stable`. **Automating distribution without a compatibility contract amplifies the risk it does not remove.** The contract is therefore a prerequisite of safe auto-deployment, not an adjacent nicety.

## Decision

Adopt an engineered compatibility contract for everything crossing between nodes. Four mechanisms, layered:

1. **Schema-versioned envelopes.** Every event crossing Redis carries a `schema_version`. The `EventEnvelope` (and the `cluster.*` `ClusterEnvelope`) gain this field.
2. **Tolerant readers, as law.** Consumers ignore unknown fields and tolerate absent optionals (Postel). Additive changes within a major are then safe across the spread by construction. This is a hard rule, not a best practice — a consumer that rejects on unknown fields is a defect.
3. **Wire upcasters for the non-additive cases.** When a shared event's shape changes non-additively, the _consumer_ upcasts the event to the shape it understands before handling (the ADR-0025 pattern applied at the wire boundary — "upcasting of subscriptions"). This lives on the consume side so a lagging node can swallow a newer producer's event.
4. **Expand/contract gated on the slowest channel.** To make a breaking change: _expand_ (introduce the new alongside the old, both supported), wait until the spread has rolled past the expand point, then _contract_ (remove the old) — and contraction is permitted only once the **slowest channel (`stable`)** universally carries the expand. The `alpha → stable` propagation lag _is_ the compatibility window: nothing may be removed until the trailing node has passed the expand.

Ownership: the **event-bus** owns the versioned envelope and the upcast hook; **each domain** owns expand/contract on its own events; **`reconciliation`** owns the fleet version/capability map that answers "has the slowest channel caught up?" (ADR-0024, ADR-0027).

A pragmatic delivery floor: **versioned envelope + tolerant-reader-as-law + additive-only-within-a-major** makes the large majority of changes safe with zero upcasters. Wire upcasters are built only when a genuinely non-additive change to a shared shape first demands one.

## Consequences

**Positive:**

- A deliberately-skewed fleet stays interoperable by construction; a friend's `stable` machine does not fail because `alpha` moved.
- Auto-deployment becomes safe to automate, because the thing it automates (propagation) can no longer carry silent breakage.
- The "gated on the slowest channel" rule turns into a concrete, queryable check via the capability map (ADR-0027) rather than human SemVer reasoning.

**Negative:**

- Every cross-node event needs a version stamp and a tolerant decoder; existing consumers must be audited against the tolerant-reader rule.
- Expand/contract lengthens the time-to-remove for breaking changes to at least one full `alpha → stable` propagation cycle. This is the intended cost of fleet safety, not a bug.
- Wire upcasters share the cold-data/chain-growth caveats of ADR-0025; a never-contracted change keeps its upcaster indefinitely.

## Alternatives Considered

**Rely on SemVer + channels alone.** Rejected: a labeling convention enforces nothing on the wire; the current system demonstrates the failure (no envelope version, intolerant consumers).

**Homogenize the fleet (everyone on one version).** Rejected: it contradicts the entire alpha/beta/stable premise. The version spread is a deliberate feature, so interop must be engineered, not avoided.

**Versioned envelopes + upcasters, but no expand/contract discipline.** Rejected: upcasters handle decode, but without gating removal on the slowest channel a producer can still emit a shape no lagging consumer can represent. Expand/contract is what bounds _when_ a change is safe, not just _how_ it is decoded.
