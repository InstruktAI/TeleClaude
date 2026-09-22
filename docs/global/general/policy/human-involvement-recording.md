---
description: 'Audit-only record of whether a human was in the loop: which durable facts carry it, how it is derived from observed presence, and why it never refuses the act it annotates.'
visibility: 'public'
---

# Human Involvement Recording — Policy

## Rules

### The three tests

A durable fact records human involvement only when **all three** hold. A fact that fails any one of them records nothing.

- **Commitment** — the fact binds the human or the business to something beyond the process: money or legal state, speech carried in the human's name, standing granted to a person, or knowledge that downstream agents act on without verifying.
- **Discretion** — the fact turned on a fork the human owns. A fact a specialist produces by following the process, identically every time, carries no discretion and records nothing.
- **Opacity** — the human's involvement is not already legible from the fact itself. A record whose entire content _is_ the human's decision states its own provenance and records nothing further.

The tests are conjunctive by design. Each one alone admits a wide class of facts; together they admit few.

### The record is derived, never adjudicated

- Involvement is **derived by the platform from the human's observed presence at the fact**, once, at the moment the fact is created. The acting agent supplies the intent to record; the platform supplies the value.
- Involvement is **derived mechanically at every door**. At a human door the human is the caller of that fact-producing act by construction. At an agent door the platform reads the recency of authenticated human input to the acting session and records `true` inside the window, `false` outside it.
- Involvement **decays with the human's presence, not with the agent's use of it.** A human's direction stays live in an agent's context for the rest of the session, so an agent's sense of being shaped by the human never decays and cannot bound the record. Observed presence does decay, and it is what the record reports.
- Involvement is **never inherited or propagated**. A record on a session launch, todo, artifact, commit, parent session, or earlier operation supplies no value for any later fact.
- Involvement is **never inferred from identity**. A principal without a system root means a human started the session, not that a human was present at a later act. Lineage names delegated authority and never records involvement (`general/concept/lineage-vs-authorship`).
- The record is **orthogonal to authorization**. It records whether a human was present at the fact; it is never consulted to permit an operation. It widens no brief, suspends no ownership, and unfreezes no contract — authorization reads the acting agent and the object alone, and every caller is an agent (`general/principle/trust-and-guardrails`).
- The record **never refuses the act it annotates**. A declaration the observation does not support records `false` and the act proceeds. A malformed invocation — a declaration carrying no reason — is refused as argument validation, which judges the call and never the human.

### The record fails toward audit

Absence records `false`. A declaration the observation does not support records `false`. Either way the fact is filed as agent-initiated and surfaced for audit; neither hides an autonomous act behind a default. Forgetting is therefore never the profitable move.

A discarded declaration is observable, carrying the observed age of the last human input and never the supplied reason, so over-declaration is measured rather than guessed at.

The record's integrity rests on **detection, not prevention**. The record makes every claim about the human falsifiable against the session's own transcript and traceable to the session that produced it.

### Granularity

Involvement is stamped **on the fact, once, and is immutable thereafter** — alongside the door that produced it and the lineage under which it ran. It is not stamped on operations. Almost every operation is determined by the process, so an operation-level flag would read `false` nearly everywhere and `true` wherever an agent chose, and a flag that is cheap to add is a flag that means nothing.

### Facts that qualify

Speech carried to third parties in the human's name. Records that commit money or legal standing. Grants of access or authority to a person. Knowledge published into the layer other agents read as contract.

### The known outlier

Documentation snippets and agent artifacts pass all three tests and carry no involvement record, because no operation exists to attach one to: they are authored as files, not through a command the platform can stamp. They are covered instead by independent review and by lint. This is a gap held open deliberately, not a claim that such authoring is human-driven by construction. A future operation over these artifacts carries the record like any other qualifying fact.

## Rationale

Attribution matters exactly where a future reader forms a belief about the human. Nobody reads a set of review findings and concludes something about the human who owns the project; everyone reads an invoice, a published message, or a granted role and concludes the human stood behind it. The tests select for that reading.

Commitment alone over-selects: outward-facing work performed inside a brief — a support reply, an escalation — is expected, bounded, and speaks for a role rather than for the human. Discretion is what excludes it, and discretion is also what excludes the whole machinery of the process, where the human holds no intent and trusts the specialist. Opacity excludes the records that already say what they are, whose provenance is their own content.

Deriving the value rather than adjudicating a claim about it resolves a contradiction the claim-shaped form cannot escape. "A human shaped this" is unbounded and self-assessed: the human's direction remains live in the agent's context long after the human has gone, so a good-faith agent asserts it indefinitely. Presence is bounded and observable, so the platform can answer the question the record exists to answer without asking the agent to bound something it has no way to bound. An agent is then never told its own sense of the conversation is false — the record simply reports a different, narrower fact.

A record that authorizes nothing must not veto anything. Holding an act hostage to an annotation gives the annotation the force the rest of this policy denies it, and the refusal lands on the party least able to satisfy it: the agent cannot make the human return. Recording `false` and proceeding is the same outcome omission produces, which is what the fail-toward-audit rule already requires. Discarding the declaration visibly, with the observed age, keeps the divergence measurable without spending it on a failed act.

Rarity is the record's value. It exists so the human can ask one question — which commitments were made in my name while I was not there — and receive a short, honest answer. Every fact that carries the record without earning it lengthens that answer and cheapens the attention it was built to direct.

## Scope

All agents, all projects. Every durable fact the platform creates or mutates on a human's behalf.

## Enforcement

- A fact that passes the three tests and carries no involvement record is a defect in the surface that creates it.
- A fact that carries the record without passing all three tests is noise, and is removed rather than tolerated.
- A surface that refuses, aborts, or degrades a fact-producing act because an involvement declaration was not supported by the observation is a defect. Only a malformed invocation is refused.
- Deriving involvement from a principal, a lineage root, or the absence of a system identity is a defect.

## Exceptions

- None. The documentation and agent-artifact outlier is a gap in the operation surface, not an exemption from the rule.
