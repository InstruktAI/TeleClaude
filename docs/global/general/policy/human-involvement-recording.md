---
description: 'Which durable facts record whether a human was in the loop: the three tests a fact must pass, the declaration that carries it, and why the record fails toward audit.'
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

### What the flag is, and is not

- Involvement is **declared by the acting agent**, never derived. The agent asserts that a human was in the conversation that produced the fact — saw it, asked for it, or shaped it.
- Involvement is **derived mechanically only at a human door** — an entry point the platform itself stamps, where a human is the caller by construction.
- Involvement is **never inferred from identity**. A principal without a system root means a human started the session, not that a human is present for this act. Lineage names delegated authority and never records involvement (`general/concept/lineage-vs-authorship`).
- The flag is **orthogonal to authorization**. It records whether a human shaped the fact; it is never consulted to permit an operation. It widens no brief, suspends no ownership, and unfreezes no contract — authorization reads the acting agent and the object alone, and every caller is an agent (`general/principle/trust-and-guardrails`).

<!-- planned:human-involvement-propagates-at-dispatch -->
### Spawned-session context is a separate declaration

- Every operation that spawns or dispatches an agent session accepts an explicit human-involvement declaration and carries that value unchanged into the spawned session's context. An omitted declaration means `false`.
- The declaration is never derived from lineage, sender identity, the parent session, or the selected work item. A caller that declares `true` does so because a human is genuinely participating in the spawned session; watching an upstream agent work does not make a downstream specialist human-involved.
- Spawned context renders the declaration as `human_in_loop: true | false`. Downstream briefs, review claims, and escalations use that declaration when describing who supplied or shaped the work. A `false` declaration forbids calling an agent-selected input human-supplied; a `true` declaration records participation but still does not prove any specific human decision or authorization.
- This transient context declaration is not the durable fact record governed by the three tests below. It guides the spawned agent's posture and attribution language, grants no authority, and creates no durable involvement stamp by itself.
<!-- /planned:human-involvement-propagates-at-dispatch -->

### The record fails toward audit

Absence records `false`. A forgotten declaration files the fact as agent-initiated and surfaces it for audit; it never hides an autonomous act behind a default. Forgetting is therefore never the profitable move.

The flag's integrity rests on **detection, not prevention**. An agent can assert a human's approval falsely. The record makes the assertion falsifiable and traceable to the session that made it, and a false declaration is a serious violation answered by the durable record.

### Granularity

Involvement is stamped **on the fact, once, and is immutable thereafter** — alongside the door that produced it and the lineage under which it ran. It is not stamped on operations. Almost every operation is determined by the process, so an operation-level flag would read `false` nearly everywhere and `true` wherever an agent chose, and a flag that is cheap to add is a flag that means nothing.

### Facts that qualify

Speech carried to third parties in the human's name. Records that commit money or legal standing. Grants of access or authority to a person. Knowledge published into the layer other agents read as contract.

### The known outlier

Documentation snippets and agent artifacts pass all three tests and carry no involvement record, because no operation exists to attach one to: they are authored as files, not through a command the platform can stamp. They are covered instead by independent review and by lint. This is a gap held open deliberately, not a claim that such authoring is human-driven by construction. A future operation over these artifacts carries the declaration like any other qualifying fact.

## Rationale

Attribution matters exactly where a future reader forms a belief about the human. Nobody reads a set of review findings and concludes something about the human who owns the project; everyone reads an invoice, a published message, or a granted role and concludes the human stood behind it. The tests select for that reading.

Commitment alone over-selects: outward-facing work performed inside a brief — a support reply, an escalation — is expected, bounded, and speaks for a role rather than for the human. Discretion is what excludes it, and discretion is also what excludes the whole machinery of the process, where the human holds no intent and trusts the specialist. Opacity excludes the records that already say what they are, whose provenance is their own content.

The declaration is not verifiable, and making it verifiable is not possible: presence at a keyboard leaves no trace the platform can read. Keeping it out of authorization entirely bounds what a false declaration can buy — nothing. It permits no operation, so forging it corrupts only the audit record, where the falsehood stands against the session's own transcript and is detectable.

Rarity is the flag's value. It exists so the human can ask one question — which commitments were made in my name while I was not there — and receive a short, honest answer. Every fact that carries the flag without earning it lengthens that answer and cheapens the attention it was built to direct.

## Scope

All agents, all projects. Every durable fact the platform creates or mutates on a human's behalf.

## Enforcement

- A fact that passes the three tests and carries no involvement record is a defect in the surface that creates it.
- A fact that carries the record without passing all three tests is noise, and is removed rather than tolerated.
- A declaration of human involvement made where no human was in the conversation is a serious violation, traceable to the declaring agent's session through the durable record.
- Deriving involvement from a principal, a lineage root, or the absence of a system identity is a defect.

## Exceptions

- None. The documentation and agent-artifact outlier is a gap in the operation surface, not an exemption from the rule.
