---
description: 'Work phase design: independent implementation followed by complete-target review and sequential remediation.'
visibility: 'public'
---

# Work — Design

## Required reads

- @~/.teleclaude/docs/sdlc/design/lifecycle/overview.md

## Purpose

Deliver a prepared specification through a builder that independently completes
its implementation and a driver that reviews the completed target afterward
(`sdlc/procedure/lifecycle/work/build-v2`,
`sdlc/procedure/lifecycle/work/overview-v2`). Review isolation, findings and
adjudication are owned by `sdlc/procedure/lifecycle/review`.

## Inputs/Outputs

Inputs are the prepared body revision, reviewed owner contracts, assigned branch
and worktree, governing policies and source evidence. Outputs are the completed
implementation, revision-bound review and remediation records, and a stamp at
the independently approved integration head, or a grounded return to preparation.

## Invariants

- The builder owns the mechanism and self-checks the complete delivery. The
  driver coordinates operational progress without early technical review or
  co-design. A co-designer obtains an unprimed review instead of certifying its
  contribution (`sdlc/procedure/lifecycle/review`).
- Commit notices record source progress. Technical review starts after the
  completed-target handoff and covers the whole delta, including commits whose
  notices were missed; intermediate publication establishes no approval.
- The reviewer derives the applicable obligations independently and executes
  every applicable lane in `sdlc/policy/definition-of-done-lanes`. Proposed
  contracts and earlier verdicts do not waive governing policies.
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
    participant D as Driver / isolated reviewer
    participant B as Builder
    participant I as Integrator
    D->>B: Prepared intent, constraints and source pointers
    B->>B: Implement and self-check complete delivery
    B-->>D: Completed head and evidence; stop editing
    D->>D: Independent whole-delta review
    loop Only while valid findings remain
        D-->>B: Complete revision-bound verdict
        B->>B: Independent remediation or evidenced rejection
        B-->>D: Completed head and dispositions
        D->>D: Re-review findings and changed surface
    end
    D->>D: Stamp approved head with independent report
    D-->>I: Candidate at that commit
```

A ready item questioned before admission retains its source and review history.
The driver assesses the stated reason under the same finding-validity rules and
performs the existing release or kickback act.

## Failure modes

- Per-commit coaching commits the reviewer to the mechanism before final review.
- The last patch is reviewed while the complete delivery remains unexamined.
- A lane is marked satisfied without source evidence for its actual obligations.
- A reviewer prescribes extra machinery instead of establishing a scoped defect.
- The builder treats a reply as approval, or implementation changes during a
  review leave its verdict bound to the wrong head.
