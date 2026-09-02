---
description: Surface and rank deepening opportunities, select one through agent judgment and independent peer falsification, then converge on that module's interface within settled ownership and scope.
activation_trigger: Use when asked to find refactoring or deepening opportunities in a codebase, to run an architecture improvement sweep, or to design or redesign one module's interface.
---

# Deepening Discovery — Procedure

## Required reads

@~/.teleclaude/docs/software-development/principle/module-depth.md
@~/.teleclaude/docs/software-development/policy/substrate-anchoring.md
@~/.teleclaude/docs/software-development/principle/architectural-defaults.md
@~/.teleclaude/docs/general/procedure/visualizing-for-humans.md

## Goal

Find where a codebase's structure causes friction, rank the candidates for
deepening from evidence, select one, and converge on that module's interface
through peer stress-testing and parallel design. The unit of progress is one
deepened module, never a campaign; the budget is bounded by scope and by cost
caps, and the human is involved only where their lane is crossed.

## Preconditions

- The required reads above are loaded; the `grill-me` skill is available.
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

### 4. Rank and select from evidence

Rank the candidates on the evidence gathered: the deletion test's result, the
dependency category, blast radius from blueprint facts with their confidence
limits, churn and co-change, and how many callers currently orchestrate the
module's steps. Select one candidate — the agent's decision, recorded with its
reason. Selection crosses the human's lane only when the candidate changes
what a human experiences, widens the scope the human asked for, or touches a
safety-gated action; then it is surfaced under `general/policy/human-contract`
before anything proceeds.

Render the ranked candidates as one report for the human to see, per
`general/procedure/visualizing-for-humans`: per candidate the files involved,
the problem and the solution in one sentence each, the wins in terms of
leverage, locality, and how tests improve, a before-and-after diagram, the
dependency category, the owning context and anchor module, and the selection
with its reason. Flag a conflict with an existing ADR only when the friction
is real enough to reopen the decision. The report orients; it is not a menu.
Use the vocabulary of `module-depth` exactly — module, interface,
implementation, depth, seam, adapter, leverage, locality — and the domain
language of the domain specs for the domain.

### 5. Stress-test the selection with an independent peer

Dispatch an independent peer to falsify the selection and its constraints:
the owning context, the anchor, the dependency category, what sits behind the
seam, which tests survive, and whether a cheaper candidate was passed over. A
valid finding follows the finding contract of
`software-development/procedure/lifecycle/review`; a peer objection is a
claim, not an order. Facts are found by agents, never asked of the human. When
the human has explicitly invoked a collaborative exploration, the `grill-me`
skill walks the same decision tree with them instead; otherwise the human is
not consulted.

### 6. Design it twice

Frame the problem space — constraints, dependency category, a rough
illustrative sketch — then dispatch three or more sub-agents in parallel, each
with a different design constraint: minimize the interface; maximize
flexibility; make the most common caller trivial; design around ports and
adapters where a cross-seam dependency exists. Each returns the interface with
its invariants, ordering, and error modes; a usage example; what the
implementation hides; the dependency strategy; and where leverage is high or
thin. Compare on depth, locality, and seam placement, choose one or a hybrid,
and record the choice with its reason; the independent peer checks the choice
against the constraints. The human sees the chosen design in the report; they
decide only where their lane is crossed.

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

The failures this procedure guards against are two. Converging unchecked:
selecting a candidate or an interface without evidence and without a peer's
falsification, merging across a context boundary because depth looked better
there, or inventing a parallel to an existing module because it was not looked
for. And handing the human a technical menu: candidate selection, seam
placement, and interface design are the agent's decisions under the human
contract, recorded with their reasons and stress-tested by a peer; the human
is surfaced only where their closed lane is crossed. Ownership and anchoring
are settled before any depth judgment, and the procedure ends at a design
handed to the lifecycle, never at code.

## Outputs

- One ranked candidate report, with the selection and its reason, visible to
  the human.
- For the selected candidate: a peer-tested set of constraints and a chosen
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
- ~/.teleclaude/docs/general/policy/human-contract.md — why selection and design are the agent's decisions.
- https://github.com/mattpocock/skills (MIT) — prior art: the hot-spot scoping, deletion test, dependency categories, and design-it-twice pattern this procedure re-expresses under TeleClaude doctrine.
