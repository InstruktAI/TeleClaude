---
description: Deep modules behind thin interfaces, settled inside correct boundaries — functional design governs the inside, depth governs the boundary, and depth arbitrates when the design fundamentals pull against each other.
---

# Module Depth — Principle

## Principle

A module is deep or it is gone. Deep means a small, stable interface hiding real
logic: callers know one cohesive capability and none of the steps behind it. A
module whose interface is as large as its implementation is a pass-through — a
seam that absorbs no complexity — and seams are where systems fail.

Depth is measured at the interface, by how little a caller must know, never by
implementation size. Ownership, cohesion, and invariant boundaries are settled
first (`software-development/principle/architectural-defaults`,
`software-development/principle/domain-driven-design`); depth then arbitrates
granularity and exposure disputes inside those boundaries. A deep god module is
still a god module.

Functional design governs the inside; deep-module design governs the boundary.
Small pure transformations, explicit data flow, and composition are how a
capability is built. One cohesive operation, with callers never orchestrating
implementation steps, is how it is exposed. The disease is exporting incidental
steps, not small functions.

## Rationale

Wiring is the largest failure class in the measured bug record, ahead of logic.
Every public seam is failure surface, and every step a caller must sequence is a
place to sequence it wrong. Agents also pay context for each thing a caller must
know; a thin interface is cheaper to use correctly than a wide one, and a change
behind it reaches zero callers.

The design fundamentals are vocabulary, not an arbiter. Applied one at a time
they conflict — SRP splits, KISS flattens, DRY extracts — and a reviewer without
a tiebreaker argues taste. Depth is the tiebreaker: the split that makes callers
know more loses.

Testable shape follows from the same cut. A capability exercisable through its
public contract with real or controlled effect collaborators needs no seam into
its internals; a module that can only be tested by patching its inside is too
shallow, or its effects are misplaced. Testable shape is mandatory architecture;
whether a test is admitted is a separate, evidence-gated decision.

## Implications

- **One-sentence contract.** A module states its capability in one sentence
  without "and". A sentence that needs "and" is a split candidate; a paragraph
  is a god module. The sentence names supported operations, invariants, and
  failure semantics; the decomposition behind it is private.
- **Depth arbitrates the fundamentals.** SRP counts reasons to change, not
  functions; splitting one cohesive mechanism across five files multiplies
  interfaces and callers now know five names. KISS is measured at the call site,
  not in the diff; ten simple leaked steps are more complex than one deep call.
  DRY is unchanged — knowledge lives once — and depth says where: inside the
  module that owns it. YAGNI holds — depth is for complexity that exists today,
  never for imagined future callers.
- **Effect boundaries are the only inversion points.** Dependency inversion
  applies at nondeterministic or side-effectful resources — storage, clock,
  transport, filesystem, randomness, environment — never everywhere. One
  composition root acquires concrete effect capabilities; deep modules receive
  narrow capabilities; internals are constructed privately. No dependency
  container, no service locator, no internal patch seam. Controlled clocks,
  temporary or in-memory stores, and independently conformant adapters are
  legitimate collaborators; interaction-recording mocks are not.
- **Public surface is the contract; everything else is private.** Nothing
  becomes public for a test's convenience. One word, one meaning: a term already
  bound in the state model is never reused for a second concept. A name claims
  no more authority than the construct owns — domain language when the construct
  genuinely owns that domain decision, the mechanism's name otherwise.
- **A pass-through is a signal, not a verdict.** A public function whose body
  forwards to another module unchanged is an inventory fact for the judging
  agent: it may be a legitimate stable capability, or a seam to merge away.
- **Reuse is evidence, not a goal.** A one-caller helper is not a defect; fifty
  private functions behind one domain operation are healthy. What is judged is
  whether callers must know internals, not how many functions exist.

## Tensions

- **Depth vs. SRP over-splitting.** Both are right about something: SRP about
  reasons to change, depth about what callers know. When they disagree, depth
  decides, because the caller pays for the split and the author does not.
- **Deep module vs. god module.** Depth invites accretion. The one-sentence
  contract is the guard: the moment the sentence grows an "and", the module has
  two contracts wearing one interface.
- **Inversion vs. ceremony.** Inverting every seam is the astronaut architecture
  the fundamentals already reject. Inverting none makes the module untestable
  without patching. The cut is the effect boundary.
- **Progressive deepening vs. rewrites.** No rewrite is mandated. Depth applies
  to new work and to deliberate deepening, module by module, through the normal
  lifecycle.

## See Also

- ~/.teleclaude/docs/software-development/principle/design-fundamentals.md — the vocabulary this principle arbitrates.
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md — the boundaries and state ownership settled before depth applies.
- ~/.teleclaude/docs/software-development/policy/substrate-anchoring.md — naming the existing module before building a new one.
