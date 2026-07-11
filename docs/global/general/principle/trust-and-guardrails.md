---
description: 'Agents are trusted by default. A guardrail earns its place only where restoring state cannot repair the harm — interference and contract violation. Everything else is direction, carried by briefs.'
visibility: 'public'
---

# Trust and Guardrails — Principle

## Principle

Agents operating inside the platform are trusted. Trust is the default posture, not a reward, and it is not withdrawn because an agent might act wrongly — it is the condition under which agents become useful at all.

A guardrail earns its place only where **restoring state cannot repair the harm**. Two harms meet that bar:

- **Interference** — two agents acting on one object. The stored value is recoverable; the other agent's reasoning, already formed from the value it read, is not.
- **Contract violation** — a contract changed underneath the party executing it. The document is recoverable; the work performed against the wrong version is not.

Everything else is direction. Direction is carried by the agent's brief, not by a gate.

Reversibility is an invariant of the state layer, engineered rather than enforced: durable records are versioned, removals are soft, and a mutation that cannot be undone is a defect in the state layer, never an occasion for a permission rule. A gate placed around a destructive operation makes the destructiveness permanent, because the gate outlives the repair.

A guardrail is addressed to the object, never to the caller's rank. It reads what the object is — who holds it, what phase it is in — and never who is asking. Rank is a proxy for the object's state, and a proxy drifts from the thing it stands for.

A refusal names its door. The guardrail does not merely deny; it states the sanctioned path that satisfies the invariant — release the claim, or return the contract to the phase where it is open. The door changes the world so the invariant holds honestly. It never suspends the invariant.

## Rationale

Guardrails accumulate. Each one is added for a case that was real, and each one is expressed in whatever vocabulary the system happened to have. When the object's state is not expressible, rank stands in for it, and the rank list grows an entry per role that happened to be nearby when the case arose. The list then reads as a design and defends itself as one, long after the condition it approximates has become expressible directly.

The discipline that prevents this is a bar high enough that almost nothing clears it. Reversibility clears the field: deletion, renaming, reclassification, forced migration — all repairable, none deserving a gate. What survives is the harm that lands where state restoration cannot reach: in another agent's formed reasoning, or in work already performed. Those two are irreducible, and they are properties of the object.

Judgment cannot be gated. Whether an agent should refactor adjacent code, widen a scope, or heal a blocker it does not understand is a question of judgment, and code that grades judgment decays (`general/principle/intelligence-boundaries`). The brief carries direction because direction is semantic.

A refusal is nonetheless the moment judgment becomes reachable. An agent that meets a blocker and is free to route around it will route around it, reasoning fluently about why this case is different. An agent that meets a refusal has one move: stop, and tell someone. The guardrail does not supply the judgment. It creates the moment the judgment is required, and it hands over the door rather than a wall.

## Implications

- **The gate reads the object, not the caller.** Ownership and phase are facts about the world. A caller's role, job, or rank is an assertion about the caller, and it answers a different question than the one the gate is asking.
- **Focus and integrity are separate layers.** The set of operations a brief includes is focus: declared alongside the brief, cheap to change, and its violation costs a refused call. Interference and contract violation are integrity: enforced against the object, and their violation costs work no one can restore.
- **Every caller is an agent, so no gate has a human path.** The human's will enters only through the agent it addresses. Capability, ownership, and phase all read the agent and the object; none is lifted, widened, or suspended by human presence, because the human is never in the call.
- **The human steers by whom they address, not by overriding a gate.** Directing a capable agent gets the act done; directing an incapable one earns the refusal that routes the human to the agent that can. The refusal is the routing, and it is exactly the containment a narrow brief exists to provide.
- **The involvement record is orthogonal to authorization.** Whether a human shaped an act is declared for audit, never consulted to permit it. It widens nothing and suspends nothing; a false declaration buys no operation and corrupts only the audit trail, where it is detectable against the session's own transcript.
- **A new gate is evidence of a missing dimension.** When an invariant cannot be expressed against the object, the object model is thinner than the domain. Widen the object; do not add a call site.
- **A guardrail that cannot name its door is not finished.** A refusal without a sanctioned path teaches agents to treat the platform as an obstacle and to route around it.

## Tensions

- **Trust vs. containment.** Trust is the default, yet a dispatched agent that meets an anomaly reaches for whatever tool ends the anomaly, and its brief gives it no view of the blast radius. Containment is what the two invariants buy; the rest is the brief's work, and the brief is fallible.
- **Gate vs. brief.** A gate is reliable and blind; a brief is intelligent and ignorable. Placing a rule in the wrong one is the recurring failure: judgment compiled into a gate produces an enumeration that rots, and integrity entrusted to a brief produces damage no reviewer catches.
- **Reversibility as an aim vs. as an assumption.** Treating the state layer as reversible before it is makes the two invariants the only defense against defects they were never meant to cover. The aim is load-bearing: where a mutation is not yet reversible, that is a defect to repair, and repairing it is not optional because a guardrail elsewhere appears to compensate.
- **Refusal as routing vs. refusal as noise.** A refusal that names its door invites the agent to walk through it, including when walking through it is exactly what should have been escalated instead. The door is a sanctioned path, not a sanctioned decision.

## See Also

- ~/.teleclaude/docs/general/policy/human-involvement-recording.md — which facts record whether a human was in the loop, and why the declaration is audit-only and never an authorization input.
- ~/.teleclaude/docs/general/concept/lineage-vs-authorship.md — why the identity on a record never answers who acted, and never authorizes.
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why judgment belongs in the brief rather than in code that grades it.
