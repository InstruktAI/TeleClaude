---
id: 'software-development/design/sdlc/work'
type: 'design'
domain: 'software-development'
scope: 'global'
description: 'Work phase design: build-review-fix loops, artifact consumption rules, and role focus for realizing prepared changes.'
---

# Work — Design

## Required reads

- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define how prepared artifacts are realized into code through iterative
build-review-fix loops.

## Inputs/Outputs

**Inputs**

- `requirements`
- `test-specs`
- `implementation-plan`
- computed supporting context and evidence where automation can provide it

**Outputs**

- implemented change
- review findings
- approved change ready for integration

## Invariants

- Build consumes the full prepare artifact chain rather than treating any single
  artifact as sufficient truth.
- Review validates both local correctness and upstream artifact fidelity.
- Fixes are treated as new work that must be re-reviewed, not as automatically
  safe patches.

## Primary flows

### Build

Goal:

- realize the prepared artifacts in code

Lead/support:

- `B` leads
- `A` supports

How rigor is preserved:

- execution is constrained by `requirements + test_specs + implementation-plan`
- `A` prevents drift away from intended outcome and user value

### Review

Goal:

- validate the built change against intent, acceptance, execution, and quality

Lead/support:

- `A` leads
- `B` supports

How rigor is preserved:

- review asks whether the right thing was built correctly
- `B` pressures technical rigor, edge handling, and structural correctness

### Fix and re-review

Goal:

- resolve findings without losing alignment

Lead/support:

- `B` leads fixes
- `A` supports and then leads re-review

How rigor is preserved:

- fixes remain bound to the same authority chain
- every loop must close by re-validating the actual resolved change

## Failure modes

- builders optimize only for passing specs or only for checking off plan tasks
- review checks local correctness but misses intent drift
- fixes become narrow patches that introduce new misalignment or churn

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/overview.md —
  operational steps for executing the work phase
