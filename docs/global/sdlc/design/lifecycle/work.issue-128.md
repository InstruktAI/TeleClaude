---
description: 'Work phase design: separate builder, reviewer and driver, with coherent commit reviews and final delivery review.'
visibility: 'public'
---

# Work — Design

## Required reads

- @~/.teleclaude/docs/sdlc/design/lifecycle/overview.md

## Purpose

Deliver a prepared specification through a builder that independently completes
coherent units and a dedicated reviewer that assesses each finished unit and
the resulting whole delivery. The driver coordinates their handoffs
(`sdlc/procedure/lifecycle/work/build-v2`,
`sdlc/procedure/lifecycle/work/overview-v2`). Review isolation, findings and
adjudication are owned by `sdlc/procedure/lifecycle/review`.

## Inputs/Outputs

Inputs are the prepared body revision, reviewed owner contracts, assigned branch
and worktree, governing policies and source evidence. Outputs are the completed
implementation, revision-bound review and remediation records, and a stamp at
the independently approved integration head, or a grounded return to preparation.

## Invariants

- The builder owns implementation; the dedicated reviewer owns independent
  technical assessment; the driver coordinates and arbitrates scope and
  procedure under `sdlc/procedure/lifecycle/review`.
- Each coherent commit is reviewed after completion, before the next unit.
  Commit notices prompt the driver to obtain the factual handoff. The machine
  does not judge whether a unit is semantically complete. Per-commit review
  assesses current obligations without demanding the whole feature at each step.
- Final review covers the resulting whole delivery, cross-unit interactions and
  every applicable lane of `sdlc/policy/definition-of-done-lanes`, including
  commits whose notices were missed. Earlier approvals cannot replace it or
  waive governing policies.
- Findings and implementation authority remain separate. The reviewer proves
  each violation and its bounded closure condition; the builder chooses the
  compliant remedy. Existing scope and verification policy remain binding.
- Completed verdicts and completed remediations alternate. Disputed findings
  follow the shared isolated-adjudication path, preserving the review ledger.
- A stamp names the exact reviewed head and carries the complete independent
  report. No Requirement-Violation, Critical or Important finding remains open.
  The existing machine gates and integration-head checks continue to apply.
- A wrong specification returns to its preparation owner; work does not rewrite
  its contract to make findings pass. Human involvement follows
  `general/policy/human-contract`.

## Primary flows

```mermaid
sequenceDiagram
    participant D as Driver
    participant B as Builder
    participant R as Independent reviewer
    participant I as Integrator
    D->>B: Prepared intent, constraints and source pointers
    loop Each coherent unit, including remediation
        B->>B: Implement, check and commit
        B-->>D: Finished SHA, scope and evidence; stop editing
        D->>R: Exact target and authoritative inputs
        R->>R: Independent assessment
        R-->>D: Complete report and verdict
        D-->>B: Finished verdict and next authorized work
    end
    B-->>D: Whole delivery complete at H
    D->>R: Final whole-delivery review at H
    R-->>D: Complete lane report and verdict
    D->>D: Stamp only independently approved H
    D-->>I: Candidate at that commit
```

A ready item questioned before admission retains its source and review history.
The driver obtains an independent assessment of the stated reason, arbitrates
its scope and performs the supported release or kickback act.

## Failure modes

- Live technical collaboration makes the later reviewer a co-designer.
- Batch-only review lets policy violations accumulate across unreviewed units.
- The driver overrides an independent verdict to advance delivery.
- The last patch is reviewed while the complete delivery remains unexamined.
- A lane is marked satisfied without source evidence for its actual obligations.
- A reviewer prescribes extra machinery instead of establishing a scoped defect.
- The builder treats a reply as approval, or implementation changes during a
  review leave its verdict bound to the wrong head.
