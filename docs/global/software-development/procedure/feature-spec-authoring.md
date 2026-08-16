---
description: 'Author and maintain feature specs as the behavioral regression fence: facing-typed actors, behavior-level Gherkin, immutable use-case identity, and scenario-volume discipline.'
activation_trigger: 'Use before creating or editing any feature spec or its Gherkin use cases.'
---

# Feature Spec Authoring — Procedure

## Goal

Author feature specs whose Gherkin use cases form the platform's behavioral
regression fence: agent-authored, agent-audited, stable enough to bind evidence
against, and readable at the level of behavior rather than implementation.

## Preconditions

- The work is behavioral — it changes what an observer can experience of the
  system. Non-behavioral work (refactor, migration, tooling with no contract
  change) produces no feature spec.
- The hub-and-spoke placement rules are loaded
  (`software-development/principle/documentation-first-development`): feature
  specs live at `docs/project/spec/feature/<context>/<concept-name>.md`,
  concept-named, never slug-named.
- Pending-change mechanics are loaded
  (`general/procedure/doc-snippet-authoring`): a scenario describing behavior
  not yet delivered is wrapped in a planned marker naming its delivering slug.

## Steps

1. **Classify.** Behavioral or not — one question. A change is behavioral when
   a test could bind it: an observer (human or agent) can experience a
   difference. Well-logged internals are observable by agents; "observable by
   no one" is not a real category. Non-behavioral work stops here, with no
   feature spec.

2. **Type every actor by facing.** Each scenario names who experiences the
   behavior, and the actor's kind is explicit from the scenario language: a
   human actor (an operator reading Discord, a user at the TUI) or an agent
   actor (a session consuming structured records, a peer receiving a message).
   Facing selects the acceptance authority downstream — human observation for
   human-facing behavior, structured runtime evidence for agent-facing
   behavior — so a scenario that leaves its observer ambiguous is defective.
   Users comprise humans and agents; when a behavior is specifically human-
   facing, say so specifically.

3. **Write at behavior level — the refactor-survival test.** Every scenario
   sentence must survive any behavior-preserving refactor unchanged. Function
   names, modules, schema fields, CLI internals, and event names do not appear
   in scenario text — those live in the plan's observation map, which binds to
   the scenario from below. This holds for agent-facing scenarios exactly as
   for human-facing ones: behavior language is what makes the fence, not who
   reads it.

<!-- planned-change:code-uc-blueprint-traceability -->
4. **Structure use cases for stable identity.** Scenarios live under a
   `### Use cases` heading. Each identified scenario is a `#### UC-<area><n>:`
   subsection containing exactly one fenced Gherkin block; ids are unique
   within the spec. A Gherkin block not yet under a `#### UC-` header is an
   anonymous scenario — the id-assignment backlog, worked down as scenarios
   acquire bindings.
<!-- change:code-uc-blueprint-traceability -->
4. **Structure use cases for stable identity.** Scenarios live under a
   `### Use cases` heading. Each identified scenario is a `#### UC-<area><n>:`
   subsection containing exactly one fenced Gherkin block; ids are globally
   unique across the published specification corpus. A Gherkin block not yet
   under a `#### UC-` header is an anonymous scenario — the id-assignment
   backlog, worked down as scenarios acquire bindings.
<!-- /planned-change:code-uc-blueprint-traceability -->

5. **Honor identity immutability.**
   - An id, once assigned, is never renumbered and never reused.
   - A wording change that preserves the predicate keeps the id and its
     revision.
   - A semantic change — the predicate itself moves — increments the use
     case's revision, recorded in the header (`#### UC-<area><n> (r2):`; an
     absent revision reads as r1). Anything bound to the prior revision is
     explicitly superseded, never silently re-pointed.
   - A retired use case keeps its header as a tombstone with a one-line
     supersession note and no Gherkin block; the id stays retired forever.

6. **Gate volume by falsifiability, not by count.** One use case states one
   falsifiable behavioral rule with one facing and one trigger class. Data
   variations are examples or a scenario outline inside that use case, never
   sibling use cases. Duplicate predicates collapse into one. A mega-scenario
   whose `Then` clauses assert unrelated rules splits. There is no numeric
   cap; the prepare lanes prune scenario floods by these rules, not by
   arithmetic.

7. **Mark pending behavior honestly.** A scenario describing behavior the
   system does not yet exhibit is authored in present tense as the future
   contract and wrapped in a `planned:<slug>` (new scenario) or
   `planned-change:<slug>` (changed scenario) marker naming the delivering
   todo. Delivery folds the marker away. A live spec is never overwritten to
   assert behavior the running system does not have.

## Outputs

- A feature spec whose use cases are individually addressable
  (`spec_id + UC-id @ revision`), facing-typed, and stated at behavior level.
- A stable identity surface that observation maps
  (`software-development/spec/observation-map`) and any project-sanctioned test
  bindings can reference without drift.

## Recovery

- An existing spec whose Gherkin blocks share one `#### UC-` header: split into
  one header per falsifiable scenario on first touch, assigning fresh ids to
  the split-out blocks; never reuse or renumber the original.
- A spec asserting behavior the live system demonstrably lacks: wrap the
  broken contract in a planned marker bound to the todo that will deliver it,
  or correct the text to current truth — a stale current spec is a defect.

## Discipline

The failure mode this procedure guards is implementation language leaking into
scenario text and unstable ids breaking every binding downstream. When editing
a spec, never renumber to "clean up" — identity outlives tidiness. When a
scenario names a function, an event, or a field, push that detail down into the
observation map and restate the sentence in behavior terms. When unsure whether
a change is semantic (revision bump) or wording (same revision), ask whether
anything bound to the old sentence would now judge differently; if yes, it is
semantic.

## See Also

- ~/.teleclaude/docs/software-development/spec/observation-map.md — how plans bind runtime evidence to the ids this procedure stabilizes.
- ~/.teleclaude/docs/software-development/principle/documentation-first-development.md — hub-and-spoke placement and concept naming.
- ~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md — planned-marker mechanics for pending scenarios.
