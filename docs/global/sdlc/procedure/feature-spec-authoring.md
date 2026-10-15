---
description: 'Author and maintain feature specs: prose contracts for behavior, Gherkin use cases only at user-goal level, stakeholder actors, immutable use-case identity, and scenario-volume discipline.'
activation_trigger: 'Use before creating or editing any feature spec or its Gherkin use cases.'
---

# Feature Spec Authoring — Procedure

## Goal

Author feature specs whose prose states each owner's behavioral contract and
whose Gherkin use cases, at user-goal level only, form the product's acceptance
fence: agent-authored, agent-audited, stable enough to bind evidence against,
and readable at the level of behavior rather than implementation.

## Preconditions

- The work is behavioral — it changes a contract of the system that a test
  could bind. Non-behavioral work (refactor, migration, tooling with no contract
  change) produces no feature spec.
- The hub-and-spoke placement rules are loaded
  (`sdlc/principle/documentation-first-development`): a feature
  spec sits at `spec/feature/<context>/<concept-name>.md` within the scope whose
  bounded context owns the behavior, concept-named, never slug-named. Most sit
  under `docs/local/`; the scope follows the owning context rather than being
  fixed to one.
- Pending-change mechanics are loaded
  (`general/procedure/doc-snippet-authoring`): a scenario describing behavior
  not yet delivered is wrapped in a planned marker naming its delivering slug.

## Steps

1. **Classify, twice.** First, behavioral or not: a change is behavioral when
   it alters a contract a test could bind. Non-behavioral work stops here, with
   no feature spec. Second, does the change create or alter a user goal? A use
   case exists only at user-goal level, as
   `sdlc/principle/documentation-first-development` §3a defines it: a goal a
   stakeholder of the product achieves, stated in the stakeholder's own terms,
   that the product owner can accept or reject a release on. Subfunctions and
   internal mechanics are written as the spec's prose contract (rules,
   invariants, refusal conditions, tables) and get no use case. A failure or
   refusal that threatens a goal is an extension of that goal's use case.

1a. **Select the owning context.** Place the feature spec under the bounded
context that owns the behavioral decision, as governed by
`sdlc/policy/domain-ownership`. The observer, entry
adapter, transport, scheduler, and runtime host do not choose the owner. A
cross-context journey decomposes into owner-local behavioral contracts;
architecture design may coordinate their relationship but never becomes a
shared owner. If no single owner can be named, stop authoring and resolve
the boundary first. Ownership is decided per use case, not once per spec: a
spec correctly placed under its context still admits no scenario whose
predicate another context decides. Before authoring a scenario, read the spec
of every context whose outcome its `Then` clauses assert —
`telec docs index --local --areas spec`, then `telec docs get <id>`, with
`--target <slug>` when the owner is pending.

2. **Name the stakeholder as the actor.** Each use case names who pursues the
   goal: a person (an operator at the TUI, a customer at the help desk) or an
   agent acting for a named person. The platform's own sessions coordinating
   with each other are machinery, never use-case actors. A use case whose actor
   is ambiguous, or is the platform's own machinery, is defective.

3. **Write at behavior level — the refactor-survival test.** Every scenario
   sentence must survive any behavior-preserving refactor unchanged. Function
   names, modules, schema fields, CLI internals, and event names do not appear
   in scenario text, whoever the stakeholder is: behavior language is what
   makes the fence.

4. **Structure use cases for stable identity.** Scenarios live under a
   `### Use cases` heading. Each identified scenario is a `#### UC-<area><n>:`
   subsection containing exactly one fenced Gherkin block; ids are unique
   within the spec. A Gherkin block not yet under a `#### UC-` header is an
   anonymous scenario — the id-assignment backlog, worked down as scenarios
   acquire bindings.

5. **Honor identity immutability.**
   - An id, once assigned, is never renumbered and never reused.
   - The header carries the id alone. A use case states its current predicate
     and says nothing about how that predicate got there: edit counts, revision
     digits, and supersession notes are history, and history lives in git.
   - When a semantic change moves a predicate, every source declaration bound
     to that use case is re-validated against the new predicate in the same
     change — one atomic corpus migration, never a silent re-point.
     Synchronization rejects the intermediate state.
   - A retired id stays retired: its header remains with no Gherkin block, and
     the id is never reassigned.

6. **Gate volume by falsifiability, not by count.** One use case states one
   falsifiable behavioral rule with one facing and one trigger class. Data
   variations are examples or a scenario outline inside that use case, never
   sibling use cases. Duplicate predicates collapse into one — across the
   corpus, not within one spec. Two scenarios whose `Then` clauses, read
   without actor and surface words, state one rule are one rule, and it lives
   in the owning context's spec; a different facing, entry point, transport, or
   computer does not individuate it. A scenario that survives only by
   asserting another context's outcome is consumer restatement
   (`general/policy/snippet-value-contract`) and is not authored; this
   context's contribution is one sentence in its prose with the owner's id, or
   its own use case whose `Then` clauses assert only what this context decides.
   A mega-scenario whose `Then` clauses assert unrelated rules splits. There is
   no numeric cap; the prepare lanes prune scenario floods by these rules, not
   by arithmetic.

7. **Mark pending behavior honestly.** A scenario describing behavior the
   system does not yet exhibit is authored in present tense as the future
   contract and wrapped in a `planned:<slug>` (new scenario) or
   `planned-change:<slug>` (changed scenario) marker naming the delivering
   todo. Delivery folds the marker away. A live spec is never overwritten to
   assert behavior the running system does not have.

## Outputs

- A feature spec whose use cases are individually addressable
  (`spec_id + UC-id`), names its stakeholder, and is stated at behavior level.
- A stable identity surface that project-sanctioned test bindings can
  reference without drift.

## Recovery

- An existing spec whose Gherkin blocks share one `#### UC-` header: split into
  one header per falsifiable scenario on first touch, assigning fresh ids to
  the split-out blocks; never reuse or renumber the original.
- A collision between an established lineage and a later pending identity claim:
  the established lineage retains the identity. The later carrier's owner
  assigns a fresh identity in the intended semantic family, updates every
  reference owned by that carrier, and reruns synchronization. Between pending
  claims, the earlier committed reservation retains the identity. Never rename
  both sides, rename a live identity, or rely on automatic reassignment.
- A spec asserting behavior the live system demonstrably lacks: wrap the
  broken contract in a planned marker bound to the todo that will deliver it,
  or correct the text to current truth — a stale current spec is a defect.
- An existing use case whose `Then` clauses all assert another context's
  decisions: retire it under step 5 — the header stays with no Gherkin block —
  and add at most one sentence to the spec's prose naming this context's own
  contribution with the owner's id. A `Then` clause asserting another
  context's outcome inside an otherwise owned use case is deleted, not
  rewritten. A pending scenario of this shape is deleted with its planned
  block, and its id is not reused. The consumer's scenario is never extended
  toward the owner's rule to make it complete.

## Discipline

The failure mode this procedure guards is implementation language leaking into
scenario text and unstable ids breaking every binding downstream. When editing
a spec, never renumber to "clean up" — identity outlives tidiness. When a
scenario names a function, an event, or a field, remove that implementation
detail and restate the sentence in behavior terms. When unsure whether a
change is semantic or merely wording, ask whether
anything bound to the old sentence would now judge differently; if yes, it is
semantic.

The third failure is a spec that grows by re-observing other contexts' rules
through its own surface. When a `Then` reads "executes there", "reaches the
operator", "is refused by", "is authorized by", ask which context decides that;
if not this one, the clause goes and the owner is cited.

## See Also

- ~/.teleclaude/docs/sdlc/principle/documentation-first-development.md — hub-and-spoke placement and concept naming.
- ~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md — planned-marker mechanics for pending scenarios.
