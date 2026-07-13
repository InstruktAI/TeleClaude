---
description: Atomic quality rejection predicates shared by planning, building, and review, with stable evidence IDs and explicit enforcement placement.
visibility: public
---

# Quality Predicate Registry — Policy

## Rules

### One instrument across phases

This registry is phase-neutral. Each predicate has one stable ID and one
meaning. The phases consume the same predicate differently:

- The planner names how every triggered predicate is satisfied. Untriggered
  predicates are marked `N/A` with a reason in the plan's lane coverage.
- The plan reviewer independently verdicts every predicate. Planner evidence
  is an input, never proof.
- The builder self-verifies every predicate before build completion and records
  concrete evidence by ID under `Build Gates (Builder)` in `quality-checklist`.
- The build reviewer independently re-proves every predicate and records the
  result by ID in the tests lane of `review-findings`. Builder evidence is an
  input, never proof.
- The commit reviewer independently applies every predicate triggered by the
  reviewed diff. There is no planner or builder evidence to trust.

Silence is not coverage. Every predicate receives evidence or a reasoned
`N/A`. A phase does not copy or reinterpret the predicate text.

### Test-quality predicates

| ID      | Reject when                                                                                                                                                                                                                                                                                              | Applies when                                                     | Required evidence                                                                                                                                                         | Strongest enforcement                                    |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `TQ-01` | A behavioral test has no valid `<spec_id>` + `UC-<id>` binding, unless it is a sanctioned smoke-wiring test or Rust colocated unit; or a test targets a contract-defining declaration that is its own spec. Bug regression tests bind the approved regression scenario and are not an unbound exception. | Any test added or changed.                                       | Binding ID, or the named sanctioned exception and why it applies.                                                                                                         | Native binding lint, then review.                        |
| `TQ-02` | A functional test enters through an internal symbol rather than the behavior's real caller surface, or fakes an in-process collaborator so the real chain never runs.                                                                                                                                    | Any functional test.                                             | Named real entry surface and every faked process or network boundary.                                                                                                     | Review judgment.                                         |
| `TQ-03` | The test stays green under a plausible broken production implementation.                                                                                                                                                                                                                                 | Every behavioral and smoke test.                                 | One concrete production mutation that turns the test red. For smoke, this may be a missing route, registration, subscription, or end-to-end connection.                   | Review judgment.                                         |
| `TQ-04` | The assertion pins a hardcoded default, fallback, constructor default, config literal, or model/native shape rather than the behavior that value drives.                                                                                                                                                 | A test observes configuration, defaults, or native shape.        | Named downstream behavioral branch, or deletion of the non-behavioral test. Importing a production constant may prove the resolution mechanism without pinning its value. | Review judgment.                                         |
| `TQ-05` | The test re-tests a dependency's declared behavior instead of TeleClaude's adapter contract or a relied-upon external semantic.                                                                                                                                                                          | A test exercises third-party code or an external service.        | Named application contract or relied-upon external semantic, plus the application failure the test catches.                                                               | Review judgment.                                         |
| `TQ-06` | Primary evidence is a logger, metric, trace, private helper, constructor/DI capture, mock-call echo, passthrough, primitive side effect, or wiring detail.                                                                                                                                               | Any assertion.                                                   | The observable application behavior asserted instead. A smoke test may assert concrete registration or route wiring, but `TQ-03` still applies.                           | Review judgment.                                         |
| `TQ-07` | String content is asserted by literal, substring, prefix, suffix, or pattern.                                                                                                                                                                                                                            | Any string-content assertion.                                    | Snapshot, narrow non-empty boundary guard, or imported production constant where behavior turns on identity.                                                              | Snapshot tooling, then review.                           |
| `TQ-08` | A runtime test scans production source or file text to enforce a static structural rule.                                                                                                                                                                                                                 | A test uses AST/source/file scanning as its assertion substrate. | The type, native linter, or justified custom lint that owns the invariant.                                                                                                | Type system or native lint; never a runtime test.        |
| `TQ-09` | Pass or fail depends on real-clock timing, guessed sleeps, or a race between shortened production intervals.                                                                                                                                                                                             | Any time-dependent test.                                         | Observable synchronization condition with bounded failure, or a controlled clock/timer advance.                                                                           | Deterministic clock/synchronization design, then review. |
| `TQ-10` | An agent-authored unit test exists in Python or TypeScript, or a test wears a functional label while violating `TQ-02`.                                                                                                                                                                                  | Any Python or TypeScript test.                                   | Existing approved scenario to bind at a real boundary; when none exists, route the missing contract upstream instead of inventing a test.                                 | Language-specific lint where mechanical, then review.    |
| `TQ-11` | Owned persisted data changes shape without a forward migration and an old-shape golden fixture that loads through the new model.                                                                                                                                                                         | An owned persisted or serialized field set changes.              | Migration path and golden fixture proving old input becomes the current shape.                                                                                            | Migration tooling, then review.                          |
| `TQ-12` | A snapshot changes without its diff being read, matched to intent, anomaly-checked, and reported.                                                                                                                                                                                                        | Any snapshot delta.                                              | Report line naming what changed and why it is intended.                                                                                                                   | Snapshot tooling, then review.                           |
| `TQ-13` | A scenario binding is duplicate, orphaned, stale, removed, or weakened.                                                                                                                                                                                                                                  | The scenario inventory or bound tests change.                    | Binding-coverage output plus the scenario-to-test delta.                                                                                                                  | Native binding lint, then review.                        |

### Enforcement placement

Move a predicate to the strongest layer that can express it: type first, native
lint second, justified custom lint third, agent judgment last. Semantic
questions such as real-boundary honesty, mutation killing, and whether a test
re-tests a dependency remain review judgments; do not build scanners that grade
them.

## Rationale

Agents compress dense prose and omit predicates that never enter their active
context. Stable IDs make omission visible, direct required reads make the
instrument available, and phase symmetry makes quality the builder's duty
rather than only the reviewer's cleanup. Separating predicates from rationale
keeps the gate scannable without discarding the reasoning in the broader
testing and review policies.

## Scope

The test-quality predicate family applies to every plan, build, build review,
and commit review that adds, changes, removes, or relies on tests. The registry
is designed to accept other lane families later; only the `TQ-*` family is
defined here now.

## Enforcement

- Plan review rejects missing or implausible evidence plans for triggered IDs.
- Build completion requires builder evidence or a reasoned `N/A` for every ID.
- Build and commit review independently apply triggered IDs; unresolved
  violations block approval under existing verdict arithmetic.
- A custom automated check is accepted only when the predicate's Enforcement
  column permits it and types/native tooling cannot express the invariant.

## Exceptions

None beyond the exceptions stated in the predicate that owns them. A smoke test
is exempt from scenario binding and functional-boundary entry, but not from
mutation killing. Rust colocated units are exempt only from scenario binding;
the remaining applicable predicates still govern them.

## See Also

- ~/.teleclaude/docs/software-development/policy/testing.md
- ~/.teleclaude/docs/software-development/policy/definition-of-done-lanes.md
- ~/.teleclaude/docs/software-development/concept/functional-test-boundary.md
