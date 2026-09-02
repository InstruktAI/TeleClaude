---
description: The closure contract for a delivery's obligations — three obligation classes, the existing carrier of each, and the terminal state that closes each class.
---

# Obligation Inventory — Spec

## What it is

A delivery's obligation inventory is the enumerated, located set of things the
work must make true. It is not one artifact: it is the union of three existing
carriers, each owning one obligation class, and it is closed per class rather
than by a single boolean. The inventory is frozen with the reviewed preparation
artifacts; the builder evidences it, the reviewer independently reconstructs it
and verifies the evidence, and a builder who finds an entry invalid kicks back
rather than editing it.

## Canonical fields

Every obligation carries a class, a carrier location, and a state. States are
typed by class and never form one linear chain.

| Class            | Carrier                                                                                                                             | States                                                                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Static**       | Implementation-plan tasks, and the quality checklist's builder gates                                                                | `open` → `builder-evidenced` → `reviewer-verified` (terminal)                                                                                   |
| **Runtime**      | Observation-map entries (`software-development/spec/observation-map`)                                                               | `open` → `builder-evidenced` → `reviewer-verified-as-armed`, then the observation map's evidence states exactly, from `armed_unobserved` onward |
| **Human-facing** | Observation-map entries whose acceptance authority is human observation, and the quality checklist's user-facing verification lines | `open` → `builder-evidenced` → `reviewer-verified-as-armed` → `awaiting-human-observation` (terminal at delivery, truthfully)                   |

Evidence for a static obligation is the commit that delivers the task or the
checklist line that records the gate. Evidence for a runtime obligation before
merge is instrumentation confirmed at its boundary — armed is not observed, and
a worktree can produce no runtime evidence. Post-merge runtime evidence binds to
the exact runtime identity and observation window; silence without a qualifying
opportunity is not success, and missing telemetry is not clean evidence.

`blocked` is an inventory and process state only, never a runtime-evidence
state.

All evidence binds to the digests of the artifacts it was produced against and
to the commit and revision it was produced on. A change to the intent, the
preparation artifacts, the inventory, or the diff invalidates evidence produced
before it.

## Allowed values

- Class: `static`, `runtime`, `human-facing`.
- Pre-merge states, all classes: `open`, `builder-evidenced`; then
  `reviewer-verified` for static, `reviewer-verified-as-armed` for runtime and
  human-facing.
- Post-merge runtime states: the observation map's vocabulary, unchanged.
- Human-facing terminal: `awaiting-human-observation`.
- Process-only: `blocked`.

## Known caveats

- The inventory is only as complete as its independent reconstruction. A set
  that matches the plan's own list but omits a blast-radius obligation is
  defective; the reviewer recomputes the denominator rather than trusting it.
- Pre-merge review verifies runtime obligations are armed; the integrator
  executes the sanctioned live verification after merge. Neither substitutes
  for the other.
- No carrier is invented to satisfy this table. Where a surface's native output
  is its evidence, the observation map's binding rules apply unchanged.

## See Also

- ~/.teleclaude/docs/software-development/spec/observation-map.md — the runtime carrier and its evidence states.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/build.md — builder evidence and the kickback rule.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/review-build.md — independent reconstruction and two-way tracing.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/review.md — the finding contract and convergence bounds.
