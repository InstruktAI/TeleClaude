---
description: 'Prepare phase design: a driver that holds the item derives its obligations, dispatches one author who writes the spec into the item body, challenges it, and records readiness at the exact body revision it judged.'
visibility: 'public'
---

# Prepare — Design

## Required reads

- @~/.teleclaude/docs/sdlc/principle/externalized-structural-context.md
- @~/.teleclaude/docs/sdlc/design/lifecycle/overview.md

## Purpose

Define how preparation produces the spec that work consumes.

Preparation turns the intent in an item's body into a fleshed-out spec in that
body. Two sessions carry it. The preparation driver
(`sdlc/procedure/lifecycle/prepare/overview-v2`) holds the item, derives the
obligations, challenges what is written and decides readiness. The author it
dispatches (`sdlc/procedure/lifecycle/prepare/intake-v2`) owns the spec's
content and disposes every challenge. The person who owns the intent may drop
in at any time and is waited on only when a fork is genuinely theirs.

## Inputs/Outputs

**Inputs**

- the intent the item's body carries, in whatever form it arrived
- the item's log: earlier notes, reasons and the person's decisions
- the codebase (ground truth)
- the todo landscape (signal about project direction and adjacent work)
- applicable documentation and domain context

**Outputs**

- the spec in the item's body: the outcome, the prose behavioral contract, any
  admitted user-goal use cases, and falsifiable invariants
- the durable contract changes the spec needs, as reviewed pending snippets, or
  an explicit `doc_impact_none` reason
- the log: the derivation, the challenges and their dispositions, the readiness
  verdict and every limit left open
- the item prepared at the exact body revision the driver judged

## Invariants

- The driver holds the item and judges; the author writes. The driver never
  judges a spec it wrote.
- The driver derives the smallest complete authorized outcome and the existing
  path for comparable outcomes before it reads the author's draft, so the
  challenge is independent of the draft (`sdlc/policy/substrate-anchoring`).
- Every challenge names its evidence and the contract it rests on; the author
  answers each with a change or with evidence.
- Readiness is the driver's judgment against the contract, the evidence and the
  consequence of what remains, never a count of open items.
- A bug is prepared only to an established cause, judged by the driver from the
  evidence (`sdlc/concept/defect-evidence`); a cause the filer supplied is input.
- A spec that changes a domain rule names the single bounded context that owns
  it (`sdlc/policy/domain-ownership`).
- Use cases are written only for admitted user goals
  (`sdlc/procedure/feature-spec-authoring`).
- Readiness names the body revision it judged; a body that has moved since is
  not prepared until it is judged again.
- A fork the person owns is put to them as one question while the item waits;
  every other decision is the driver's and is recorded.
- Automation supplies supporting facts for judgment; it does not decide
  scope, trade-offs, or design quality on its own.

## Primary flows

### Preparation

```mermaid
sequenceDiagram
    participant D as Preparation driver
    participant A as Author
    participant P as Person
    D->>D: claim the item, derive the obligations
    D->>A: dispatch the author
    A->>A: write the spec into the body, author pending contracts
    A-->>D: body ready for challenge
    loop until ready
        D->>A: challenge, with evidence
        A-->>D: each item changed or rejected with evidence
    end
    opt a fork the person owns
        D->>P: one question; the item waits and the driver ends
        P-->>D: the person's decision starts the next driver
    end
    D->>D: prepared, naming the body revision judged
```

### Returning to preparation

Work returns an item to preparation when the spec itself is wrong or
unbuildable (`sdlc/design/lifecycle/work`). The next preparation driver reads
the reason from the log and judges the spec again; the branch and its commits
are kept.

## Failure modes

- The driver judges the author's draft without its own derivation and confirms
  the draft's framing instead of challenging it.
- The spec grows mechanisms the authorized outcome does not need because the
  challenge covered only missing behavior.
- A bug is prepared on a plausible cause that its evidence does not establish.
- A question the driver could settle from evidence is put to the person.
- Durable contract changes stay in the body and never reach reviewed pending
  snippets, so work has nothing retrievable to build against.

## See Also

- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/overview-v2.md —
  the executable procedure for driving preparation
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/intake-v2.md
- ~/.teleclaude/docs/sdlc/procedure/feature-spec-authoring.md
