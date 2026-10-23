---
description: 'Prepare phase design: isolated specification authorship followed by independent review of the completed revision.'
visibility: 'public'
---

# Prepare — Design

## Required reads

- @~/.teleclaude/docs/sdlc/principle/externalized-structural-context.md
- @~/.teleclaude/docs/sdlc/design/lifecycle/overview.md

## Purpose

Turn authorized intent into a complete specification and reviewed pending
contracts through sequential authorship and independent review
(`sdlc/procedure/lifecycle/prepare/overview-v2`,
`sdlc/procedure/lifecycle/prepare/intake-v2`). The driver coordinates the item;
the author owns its specification and the dedicated reviewer owns its verdict.
The review relationship is governed by
`sdlc/procedure/lifecycle/review`.

## Inputs/Outputs

Inputs are the intent body, carried artifacts, governing policies and owner
contracts, and relevant source evidence. Carried proposals inform the work;
they supply no authority beyond the confirmed intent.

Outputs are the complete specification in the item's body, reviewed pending
contract references, completed review/disposition records and preparation bound
to the approved body revision. The existing item record carries these outputs.

## Invariants

- The author completes the target before review begins. The driver supplies
  intent and constraints, handles operational obstructions and dispatches a
  dedicated reviewer (`sdlc/procedure/lifecycle/review`). Each coherent doc
  commit retains its normal independent commit review.
- The reviewer derives obligations and checks applicable implementation policies
  and prior art independently before reading the author's rationale. The driver
  coordinates and arbitrates scope and procedure, never substitutes its own
  technical approval for the reviewer's verdict.
- Readiness satisfies `sdlc/policy/definition-of-ready` and
  `sdlc/policy/preparation-artifact-quality`, with every valid blocking finding
  resolved. Review scope includes the complete delivery approach and owning
  contracts, not just the prose's internal consistency.
- A bug's causal basis is established under `sdlc/concept/defect-evidence`.
  Verification follows the project's testing ruling and the assigned scope.
- The author independently remedies the completed findings or records their
  evidence-backed rejection. An isolated adjudicator handles genuine unresolved
  validity/scope disputes; it neither designs a fix nor changes the horizon.
- Readiness names the reviewed body revision; a moved body is reviewed before
  the prepared act. Human decisions remain the closed list in
  `general/policy/human-contract`.

## Primary flows

```mermaid
sequenceDiagram
    participant D as Driver
    participant A as Author
    participant R as Independent reviewer
    D->>A: Intent, constraints and source pointers
    A->>A: Complete specification; obtain doc-commit reviews
    A-->>D: Finished body revision and contracts; stop editing
    D->>R: Exact target and authoritative inputs
    R->>R: Independent complete-specification review
    R-->>D: Complete report and verdict
    loop Only while valid findings remain
        D-->>A: Complete verdict
        A->>A: Independent remediation or evidenced rejection
        A-->>D: Completed revision and dispositions
        D->>R: Revised target and dispositions
        R-->>D: Complete re-review verdict
    end
    D->>D: Record approved revision; prepare and clean up
```

The driver routes compromised independence and unresolved disputes through the
shared review procedure. Work returns an incorrect specification to preparation
with its concrete contradiction; existing source and review history are kept.

## Failure modes

- Early design discussion makes the later reviewer a co-designer.
- A coherent proposed contract is accepted despite a governing-policy conflict.
- A reviewer turns a speculative concern or preferred remedy into required work.
- The author satisfies a finding locally while leaving the changed premise
  inconsistent elsewhere in the artifact.
- Readiness or a contract review is inferred from answered findings rather than
  the completed independent verdict.
