---
visibility: 'public'
description: "A deliberately multi-version fleet keeps interoperating — nodes on different channels exchange events without a newer node's changes breaking an older one. New capabilities are ignored by unaware nodes; shared shapes evolve only additively until the slowest channel has caught up."
---

# Fleet Cross-Version Interoperability — Spec

## Required reads

- docs/global/sdlc/spec/feature-spec.md
- @docs/local/spec/domain/reconciliation.md

## What it is

The behavioral contract that keeps a permanently multi-version fleet working together. Because channels are deliberately skewed — alpha ahead of beta ahead of stable — nodes running different versions exchange events all the time, as the steady state. This spec states what must remain true so that a newer node's changes never break an older node, and an older node never silently does the wrong thing. It is stated in behavior, independent of the wire format or messaging technology.

**Business value:** the maintainer can move fast on their own machine without breaking a friend's machine. A cautious node keeps working when a bleeding-edge node ships something new; it degrades gracefully rather than failing. This is what makes automated distribution safe — without it, reliable delivery would just reliably propagate breakage.

## Canonical fields

### Interop rules

- **Unknown new capabilities are ignored, not fatal.** A node that receives a capability it does not recognize drops it cleanly and keeps working.
- **Shared shapes evolve additively within a series.** A node tolerates extra fields it does not understand and absent optional fields. Adding to an existing message never breaks an older reader.
- **Removing or breaking a shared shape waits for the slowest node.** A field or behavior the whole fleet relies on may be removed only after every live node — including the slowest channel — no longer needs it.
- **Capabilities that require agreement refuse rather than guess.** A change that two nodes must agree on to stay safe (a coordination protocol) is not silently bypassed by an unaware node; it holds until both sides support it.

- **Safe removal is decided from the live capability set, not version labels alone.** A compatibility behavior stays until every live node positively advertises the feature ID whose support permits its removal. A missing map, empty live set, or any node without that ID leaves removal unsafe.

- **Peer command errors are diagnosed by capability.** If discovery shows the peer lacks a capability carried by the forwarding node, its command error is reported as a possible outdated-build mismatch with a remedy and the original error preserved. If the peer advertises all capabilities carried by the forwarding node, its error is returned unchanged. A version string supplies context; it does not decide the mismatch.

- **Procedure entry is a capability that requires agreement.** A node advertises `procedure-entry` when it creates sessions by naming a published procedure. A session-create request naming a procedure that is forwarded to a node not advertising it is refused before any side effect, naming the missing capability; a request naming a retired command that reaches a node advertising it is refused naming the unknown command. No node translates between the two shapes. The agent role a session carries travels on an additive `role` field; the older `system_role` and `job_role` fields stay populated with a **legacy projection derived from the role's class and reach** — a focused-class role projects as `worker`, the integrator and coordinator as themselves, any other full-reach role as `orchestrator`, and any other contained role as its own name. A projected value reaches an older node only where no clearance reads it: in session snapshots, caller provenance and authored-turn labels, which that node reads for display and record alone (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`: only the principal crosses as identity, and a role carried in a message is read by no clearance). An older node's clearance reads the relayed principal and its own records, and its record derivation never meets a catalog name, because a session carrying one is created only on a node that advertises `procedure-entry`. A contained role's set is therefore evaluated only where the session was created, and no older node widens or narrows it.

### Use cases

#### UC-FXI-1: An older node tolerates a newer node's added field

#### UC-FXI-2: An older node ignores a brand-new capability

#### UC-FXI-3: A breaking removal waits for the slowest channel

#### UC-FXI-4: A coordination change refuses rather than splits

#### UC-FXI-5: "Safe to remove" is answered from the fleet's actual state

#### UC-FXI-6: An operator receives an accurate peer command error

```gherkin
Scenario: The peer lacks a capability carried by the forwarding node
Given an operator forwards a command to a peer whose advertised capabilities omit one carried by the forwarding node
When the peer rejects the command with an internal error
Then the operator is told the peer may need an update and how to remedy it
And the peer's original error remains available for diagnosis

Scenario: The peer carries all capabilities of the forwarding node
Given an operator forwards a command to a peer that advertises every capability carried by the forwarding node
When the peer rejects the command with an internal error
Then the operator sees the peer's error unchanged
And no outdated-build claim is added
```

#### UC-FXI-7: A same-build failure is surfaced without a false outdated-build claim

### Cross-context references

- Owned by `reconciliation` (`@docs/local/spec/domain/reconciliation.md`); the fleet-interop concern, backed by the fleet capability map.
- The concrete compatibility mechanisms (versioned envelopes, tolerant readers, upcasters, expand/contract) live in the decision and design layer, not in this version-agnostic contract.
- Pairs with `@docs/local/spec/feature/reconciliation/channel-gated-self-update.md`: self-update creates the version spread; this spec keeps the spread safe.

## Known caveats

- **Version-agnostic by construction.** This spec names no envelope format, no Redis, no language. The mechanisms live in the design layer and the delivering implementation. The swap test applies to every scenario.
- **The version spread is the steady state, not a transient.** Interop is a permanent invariant; there is no "after rollout" point where skew disappears.
- **"Safe to ignore" vs "must agree" is a real distinction.** Most new capabilities are safe to ignore; a minority (shared coordination) are not, and mislabeling the second kind as the first reintroduces split-brain risk.

## See Also

- docs/local/adr/0026-cross-version-fleet-compatibility.md
- docs/local/adr/0027-feature-id-capability-gating.md
