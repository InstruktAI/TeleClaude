---
visibility: public
description: A deliberately multi-version fleet keeps interoperating — nodes on different
  channels exchange events without a newer node's changes breaking an older one. New
  capabilities are ignored by unaware nodes; shared shapes evolve only additively
  until the slowest channel has caught up.
---

# Fleet Cross-Version Interoperability — Spec

## Required reads

- docs/global/software-development/spec/feature-spec.md
- @docs/project/spec/domain/reconciliation.md

## What it is

The behavioral contract that keeps a permanently multi-version fleet working together. Because channels are deliberately skewed — alpha ahead of beta ahead of stable — nodes running different versions exchange events all the time, as the steady state. This spec states what must remain true so that a newer node's changes never break an older node, and an older node never silently does the wrong thing. It is stated in behavior, independent of the wire format or messaging technology.

**Business value:** the maintainer can move fast on their own machine without breaking a friend's machine. A cautious node keeps working when a bleeding-edge node ships something new; it degrades gracefully rather than failing. This is what makes automated distribution safe — without it, reliable delivery would just reliably propagate breakage.

## Canonical fields

### Interop rules

- **Unknown new capabilities are ignored, not fatal.** A node that receives a capability it does not recognize drops it cleanly and keeps working.
- **Shared shapes evolve additively within a series.** A node tolerates extra fields it does not understand and absent optional fields. Adding to an existing message never breaks an older reader.
- **Removing or breaking a shared shape waits for the slowest node.** A field or behavior the whole fleet relies on may be removed only after every live node — including the slowest channel — no longer needs it.
- **Capabilities that require agreement refuse rather than guess.** A change that two nodes must agree on to stay safe (a coordination protocol) is not silently bypassed by an unaware node; it holds until both sides support it.

### Use cases

#### UC-FXI-1: An older node tolerates a newer node's added field

```gherkin
Given a newer node emits an event that carries a new optional field
When an older node that predates the field receives the event
Then the older node ignores the unknown field
And processes the event using the parts it understands
And does not error
```

#### UC-FXI-2: An older node ignores a brand-new capability

```gherkin
Given a newer node emits an event for a capability the older node has never heard of
And the capability is one that is safe to ignore
When the older node receives it
Then the older node drops the event cleanly
And continues operating with no error and no side effect
```

#### UC-FXI-3: A breaking removal waits for the slowest channel

```gherkin
Given a shared field is being retired
When the change is proposed
Then the old field is kept alongside the new form while any live node still depends on it
And the old field is removed only after every live node — including the slowest, stable — has stopped depending on it
And at no point does a live node receive a shape it cannot interpret
```

#### UC-FXI-4: A coordination change refuses rather than splits

```gherkin
Given a change that two nodes must both honor to remain safe (for example, a shared coordination protocol)
And one node does not yet support it
When the two nodes interact
Then the change is not silently bypassed by the unaware node
And the interaction holds to the previously agreed safe behavior until both sides support the change
And no split-brain (both nodes acting on conflicting assumptions) occurs
```

#### UC-FXI-5: "Safe to remove" is answered from the fleet's actual state

```gherkin
Given a capability is a candidate for removal
When the fleet is asked whether removal is safe
Then the answer is derived from which versions and capabilities the live fleet actually advertises
And not from a version-number comparison alone
And removal proceeds only when every live node confirms it no longer needs the capability
```

### Cross-context references

- Owned by `reconciliation` (`@docs/project/spec/domain/reconciliation.md`); the fleet-interop concern, backed by the fleet capability map.
- The concrete compatibility mechanisms (versioned envelopes, tolerant readers, upcasters, expand/contract) live in the decision and design layer, not in this version-agnostic contract.
- Pairs with `@docs/project/spec/feature/reconciliation/channel-gated-self-update.md`: self-update creates the version spread; this spec keeps the spread safe.

## Known caveats

- **Version-agnostic by construction.** This spec names no envelope format, no Redis, no language. The mechanisms live in the design layer and the delivering implementation. The swap test applies to every scenario.
- **The version spread is the steady state, not a transient.** Interop is a permanent invariant; there is no "after rollout" point where skew disappears.
- **"Safe to ignore" vs "must agree" is a real distinction.** Most new capabilities are safe to ignore; a minority (shared coordination) are not, and mislabeling the second kind as the first reintroduces split-brain risk.

## See Also

- docs/project/adr/0026-cross-version-fleet-compatibility.md
- docs/project/adr/0027-feature-id-capability-gating.md
