---
description: 'Work phase design: build-review-fix loops, artifact consumption rules, and role focus for realizing prepared changes.'
domain: 'software-development'
id: 'software-development/design/sdlc/work'
scope: 'global'
type: 'design'
visibility: 'public'
---

# Work — Design

## Required reads

- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define how prepared artifacts are realized into code through iterative
build-review-fix loops.

## Inputs/Outputs

**Inputs**

- `prd`
- optional `architecture`
- in-scope feature-spec scenarios
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
- Automation supplies supporting evidence and checks, but work quality still
  depends on judgment during build, review, and fixes.
- Work is iterative by default; rigor comes from explicit loops, not from
  assuming one-pass implementation.

## Primary flows

### Build

Goal:

- realize the prepared artifacts in code

Lead/support:

- `B` leads
- `A` supports

How rigor is preserved:

- execution is constrained by `prd + optional architecture + feature-spec scenarios + implementation-plan`
- `A` prevents drift away from intended outcome and user value

Automation supplies:

- structural context, impact clues, and available mechanical checks
- diffable evidence, test execution, and other computable support

Human/AI touchpoint:

- AI performs most implementation work
- humans enter when trade-offs, risk, or domain meaning cannot be delegated

Exit condition:

- the realized change is coherent against the full artifact chain, not just
  against local convenience

### Review

Goal:

- validate the built change against intent, acceptance, execution, and quality

Lead/support:

- `A` leads
- `B` supports

How rigor is preserved:

- review asks whether the right thing was built correctly
- `B` pressures technical rigor, edge handling, and structural correctness

Automation supplies:

- diffs, failing/passing evidence, computed scope, and other factual review
  inputs where available

Human/AI touchpoint:

- AI can perform most review work
- humans enter where acceptance, risk, or product meaning requires explicit
  judgment

Exit condition:

- findings are explicit enough to either approve the change or send it back for
  targeted rework

### Fix and re-review

Goal:

- resolve findings without losing alignment

Lead/support:

- `B` leads fixes
- `A` supports and then leads re-review

How rigor is preserved:

- fixes remain bound to the same authority chain
- every loop must close by re-validating the actual resolved change

Automation supplies:

- rerun evidence, changed-scope evidence, and other mechanically generated
  support for confirming whether the fix truly addressed the finding

Human/AI touchpoint:

- AI performs most fix work
- humans enter when findings reveal a deeper mismatch in intent, acceptance, or
  allowable trade-offs

Exit condition:

- the review loop closes only when the change is approved, not when the builder
  subjectively feels done

### Work loop matrix

| Step     | Main question                                | Lead | Support | Rigor mechanism                                                  |
| -------- | -------------------------------------------- | ---- | ------- | ---------------------------------------------------------------- |
| `build`  | Can we realize the prepared truth correctly? | `B`  | `A`     | build stays bound to PRD, architecture context, specs, and plan  |
| `review` | Did we build the right thing correctly?      | `A`  | `B`     | review checks intent, acceptance, and technical quality together |
| `fix`    | Can we resolve the finding without drift?    | `B`  | `A`     | fixes remain tied to the same artifact chain and are re-reviewed |

## Failure modes

- builders optimize only for passing specs or only for checking off plan tasks
- review checks local correctness but misses intent drift
- fixes become narrow patches that introduce new misalignment or churn
- teams treat approval as a one-pass outcome instead of an iterative convergence
  loop

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/overview.md —
  operational steps for executing the work phase
