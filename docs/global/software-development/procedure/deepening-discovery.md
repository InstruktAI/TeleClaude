---
description: Surface deepening opportunities in a codebase, present them for the human to choose one, then converge on that module's interface — with the human's attention as the budget and ownership settled before depth.
activation_trigger: Use when asked to find refactoring or deepening opportunities in a codebase, to run an architecture improvement sweep, or to design or redesign one module's interface.
---

# Deepening Discovery — Procedure

## Goal

Find where a codebase's structure causes friction, present the candidates for
deepening as a visual report, let the human pick one, and converge on that
module's interface through grilling and parallel design. The unit of progress
is one deepened module, never a campaign; the budget is the human's attention,
spent only on the candidate they chose.

## Preconditions

- `software-development/principle/module-depth`,
  `software-development/policy/substrate-anchoring`, and
  `software-development/principle/architectural-defaults` are loaded.
- The bounded contexts of the codebase are known from its domain specs
  (`docs/project/spec/domain/*`), or their absence is recorded.
- Blueprint facts (`telec code blueprint affected`, co-change history) are
  available and their coverage limits are known; unsupported edge classes are
  never read as "no dependents".

## Steps

### 1. Scope before scanning

Deepening pays off where change keeps landing, so decide where to look before
looking. If the human named a direction — a module, a subsystem, a pain point —
take it and skip inference. Otherwise walk back a good stretch of
`git log --oneline` and let the files and areas that keep recurring pull
attention first; widen the net only when the changes are scattered with no hot
spot. Read the domain specs and any ADRs touching the area first.

### 2. Settle ownership first

Every candidate respects bounded-context ownership before depth is judged. A
deepening never merges modules across a context boundary, never moves an
invariant to a new owner, and never creates a second implementation of a
capability that already exists: each candidate names the existing module whose
contract it deepens or extends, per `substrate-anchoring`. A candidate that can
only be justified by crossing a boundary is a domain-ownership question, not a
deepening candidate.

### 3. Explore by friction, not by rule

Dispatch one sub-agent to walk the scoped area. It explores organically and
notes where it experiences friction rather than applying a rubric:

- understanding one concept requires bouncing between many small modules;
- a module's interface is nearly as complex as its implementation;
- pure functions were extracted for testability while the bugs hide in how
  they are called — no locality;
- tightly coupled modules leak across their seams;
- parts that cannot be tested through their current interface.

Apply the deletion test to anything suspected shallow: would deleting it
concentrate complexity into one place, or merely move it? Concentration is the
signal. Classify each candidate's dependencies, because the category decides
how the deepened module is tested across its seam:

| Category            | Meaning                                                              | Deepening consequence                                                                                |
| ------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| in-process          | pure computation, in-memory state, no I/O                            | always deepenable; merge and test through the new interface                                          |
| local-substitutable | a real local stand-in exists (temporary store, in-memory filesystem) | deepenable; the seam stays internal and the stand-in runs in the test                                |
| remote but owned    | your own service across a network boundary                           | a port at the seam; the deep module owns the logic, transport is an injected adapter                 |
| true external       | a third-party service you do not control                             | an injected port with an independently conformant fake adapter — never an interaction-recording mock |

A seam is introduced only when at least two adapters are justified, typically
production and test; a single-adapter seam is indirection.

### 4. Present candidates; propose no interfaces yet

Render the candidates as one report for the human, per
`general/procedure/visualizing-for-humans`. Each candidate carries: the files
involved; the problem in one sentence; the solution in one sentence; the wins
in terms of leverage, locality, and how tests improve; a before-and-after
diagram of the shallowness and the deepening; the dependency category; the
owning context and the anchor module; and a recommendation strength of
`Strong`, `Worth exploring`, or `Speculative`. End with one top recommendation.
Flag a conflict with an existing ADR only when the friction is real enough to
reopen the decision.

Use the vocabulary of `module-depth` exactly — module, interface,
implementation, depth, seam, adapter, leverage, locality — and the domain
language of the domain specs for the domain. Do not propose interfaces at this
step. Ask the human which candidate to explore, and stop.

### 5. Grill the chosen candidate

Walk the decision tree with the human through the `grill-me` skill:
constraints, dependencies and their categories, the shape of the deepened
module, what sits behind the seam, which tests survive. Facts are the agent's
to find; decisions are the human's. Do not act until the frontier is empty.

### 6. Design it twice

Frame the problem space for the human — constraints, dependency categories, a
rough illustrative sketch — then dispatch three or more sub-agents in parallel,
each with a different design constraint: minimize the interface; maximize
flexibility; make the most common caller trivial; design around ports and
adapters where a cross-seam dependency exists. Each returns the interface with
its invariants, ordering, and error modes; a usage example; what the
implementation hides; the dependency strategy; and where leverage is high or
thin. Present them one at a time, compare on depth, locality, and seam
placement, then recommend one or a hybrid. Be opinionated; a menu is a failure.

### 7. Record side effects where they belong

- A domain term sharpened or introduced during the session updates the owning
  domain spec's ubiquitous language, at the moment it is resolved.
- A candidate the human rejects for a load-bearing reason earns an ADR only
  under `general/policy/adr-discipline`; ephemeral or self-evident reasons earn
  none.
- The chosen design enters the normal lifecycle as a bounded todo through the
  front door, carrying its anchor and dependency category; it is never
  implemented from inside this procedure.

## Discipline

The failure this procedure guards against is the agent converging alone: proposing
interfaces before the human has chosen a candidate, merging across a context
boundary because depth looked better there, or inventing a parallel to an
existing module because it was not looked for. Ownership and anchoring are
settled before any depth judgment, the human chooses the candidate, and the
procedure ends at a design handed to the lifecycle, never at code.

## Outputs

- One candidate report, presented to the human.
- For the chosen candidate: a grilled decision tree and a recommended
  interface design, with its dependency strategy.
- A bounded todo carrying that design, or a recorded rejection.

## Recovery

- If the scoped area has no hot spot and no named direction, report that and
  stop; do not scan the whole codebase.
- If a candidate cannot be anchored to an existing module or owning context,
  drop it from the report and record why.
- If blueprint coverage for the area is unknown, say so in the report; a
  missing edge is a blind spot, never evidence of independence.

## See Also

- ~/.teleclaude/docs/software-development/principle/module-depth.md — the vocabulary and the arbiter this procedure applies.
- ~/.teleclaude/docs/software-development/policy/substrate-anchoring.md — why every candidate names the module it deepens.
- ~/.teleclaude/docs/general/procedure/visualizing-for-humans.md — how the candidate report is rendered.
