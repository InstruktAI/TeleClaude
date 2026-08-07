---
number: 74
date: 2026-08-08
description: The v1 Python test suite is abolished on measured defect evidence — 167 classified bugs showed the 1312-test suite caught none of the class it was aimed at, entrenched four defects, and taxed the bug lane maintaining itself.
---

# The v1 Python Suite Is Abolished on Measured Defect Evidence — ADR

## Context

This record is written retrospectively. The decision was taken on 2026-07-27 and
is recorded here on 2026-08-08, because the retrospective's own working files did
not survive and the evidence had no durable home in the artifact layer. The
reasoning below is reported from the deciding sessions' transcripts, not
reconstructed from the policy that resulted.

The v1 Python runtime carried a 1312-test suite, mandated by the platform
testing doctrine. A standing suspicion that the suite was not paying for itself
was converted into measurement rather than acted on as frustration.

**Method.** Every delivered bug in the durable record — 167, spanning 2026-03-31
to 2026-07-27 — was classified by five independent readers against a fixed
rubric.

**Catchability.**

| Finding                                          | Count     |
| ------------------------------------------------ | --------- |
| Catchable by no realistic pre-written agent test | 122 (73%) |
| Plainly catchable by a straightforward test      | 35 (21%)  |
| Catchable only by booting heavy machinery        | 6 (4%)    |

The 122 uncatchable bugs clustered on three recurring reasons: races requiring
an exact interleaving; the defect being the author's own design assumption, so a
test would encode the same wrongness — the tautology problem measured in the
wild; and config, environment, and prose surfaces that tests never exercise by
construction.

**Failure classes.** Wiring 32%, logic 30%, state 13%, process 12%, race 8%. The
non-logic classes total 70%, while the entire verification budget was aimed at
the other 30%.

**The control is built in.** All 1312 tests were in place while every one of the
167 bugs shipped — including all 35 of the plainly catchable class. Suite size
is empirically uncorrelated with defect capture in this codebase.

**The suite measured net-negative on two axes.** Four verified cases record an
existing test _pinning the defect as correct_, so the suite entrenched wrong
behavior rather than merely missing it. And at least 12 delivered bugs — roughly
7% of the entire bug lane — had the test suite itself as their subject: rot
sweeps, xdist flakiness, mass mock breakage.

**Method limits, stated.** One classifier vote per bug, and 36 of the 167 were
judged from bug reports rather than diagnosis artifacts. Two independent
aggregations agreed within two percentage points: a peer's independent partial
count of ~71% against the full count of 73%.

The surviving figures are also arithmetically incomplete, and are recorded as
such rather than reconciled after the fact. The catchability buckets account for
163 of the 167 classified bugs, and the failure classes sum to 95%. That residue
— four bugs and five percentage points — cannot be recovered now that the working
files are gone. It does not move the conclusion, which rests on the control
below rather than on the exact split, but a record that quietly rounded the gap
away would be the same self-serving reconciliation this decision exists to
reject.

## Decision

The v1 Python runtime authors no tests, and its suite and toolchain are removed.
Verification moves to evidence whose standard originates outside the authoring
session: the live-daemon checkpoint obligations, agent-driven walks of the real
running system, and human-ratified visual baselines.

Two boundaries are part of the decision rather than of the contract it produced,
because they are what was contestable about it:

- The global testing doctrine is **suspended here, not retracted**. It governs
  the Rust runtime and every other project unchanged.
- The moratorium expires when the Rust runtime supersedes v1. That runtime
  states its own testing doctrine; this decision does not constrain it.

The operative contract — what is banned, what is required in its place, and how
the tooling expresses it — is `project/policy/test-moratorium`. This record does
not restate it.

## Consequences

- The 35 catchable defects are branch and table errors in first-party logic —
  precisely the class Rust's exhaustive matching and closed types make
  unrepresentable. They fund the Rust runtime's type discipline and a small
  invariant surface there, not a Python suite that demonstrably did not catch
  them.
- The refactoring-safety-net argument that funds a suite in human-paced
  development does not hold here: an agent rewrites a module in minutes. What
  insurance still pays for is failure that is both silent and irreversible, and
  that class is served by the Rust runtime's invariant and architecture-fitness
  tests.
- Visual regression is retained as a **required** mechanical check rather than
  banned. Its baseline is captured from the rendered system and ratified by a
  human, so what it compares against is recorded reality rather than something
  an agent decided — the self-agreement argument does not reach it. CSS also has
  no blast-radius graph, so pixel diffing is the only detector for a shared-style
  edit breaking screens the author never visited.
- Accepted risk: v1 carries no pre-written regression net for the 21% catchable
  class until the Rust runtime supersedes it. The measured control is what makes
  this acceptable — the 1312-test suite did not catch that class either.
- The reasoning generalizes beyond this repository, but the evidence does not.
  Extending the ruling to any other project is a separate decision on its own
  evidence, never a consequence of this one.

## Alternatives Considered

- **Keep the suite and raise test quality through instruction.** Rejected: the
  stance a valuable test requires is adversarial distrust toward one's own work,
  and reinforcement learning from human feedback rewards agreeableness toward
  context — including code the model just produced. Instruction text cannot
  restore a stance the fine-tuning objective removes, which is why accumulated
  guidance never held. This is an information problem, not an intelligence
  problem: more capable models produce the same tautology.
- **Keep a reduced suite covering only the catchable 21%.** Rejected: the
  built-in control shows the full 1312 tests failed to catch that class, and a
  smaller suite carries no mechanism that would do better.
- **Keep the suite for refactoring safety.** Rejected on the recovery-cost
  argument above.
