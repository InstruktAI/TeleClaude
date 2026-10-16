---
description: An upstream reviewer corroborates a pinned pull request and its prior reports before accepting existing review or bringing the contribution into the normal review-and-fix lifecycle.
delivered_by:
  - reviewed-pr-contributions
---

# Contribution Adoption — Spec

## What it is

The upstream project receives a contribution through its own reviewer. The
reviewer reads the proposed revision and the contributor's previous reports,
corroborates the evidence, and returns an upstream verdict. Judgment stays with
the reviewer (`general/principle/intelligence-boundaries`); comment presence,
claimed role and report formatting supply no approval.

## Canonical fields

### Adoption identity and intent

One adoption record associates the upstream repository and PR with its pinned
head and base, retained source, assessment sessions and review history. Before
ordinary item entry, the contribution intake operation owns that assessment
assignment and its output, with no local item phase, claim or approval. The
assignment binds the adoption identity; a local item is associated only through
the ordinary handoff. Repeated notifications
for the same revision resume that record. A newer PR head is a new review
subject; an earlier verdict cannot accept it implicitly. The existing qualified
content-preserving automatic-upstream-merge relation remains applicable to prior
review evidence only where its exact conditions hold. Readiness and admission
still bind the current exact head under
`local/projects/teleclaude/spec/feature/workflow/work-review-cycle`; this contract
creates no broader equivalence rule. A concurrent head
change is reconciled before publishing a verdict or delivering the proposal.

Adoption establishes the upstream intent and governing contracts that the
contribution is reviewed against. Existing approved work is reused when it owns
the change. A proposal requesting a new human-owned outcome enters the ordinary
intent decision before that outcome becomes approved work
(`general/policy/human-contract`). Imported prose remains proposed until the
owning lifecycle accepts it; importing a branch fabricates no preparation stamp.

### Reviewer-first entry

The proposal is materialized at the pinned revision for source inspection. That
entry performs no contributor-authored setup, dependency installation, hooks,
workflows, or application execution. The upstream reviewer receives the diff,
the intended outcome, the prior reports and their revision identities. The reviewer's governing brief, roles and bootstrap configuration come from
the trusted upstream procedure; imported instruction files remain review
material. There is no preceding automated semantic classifier or separate
routing reviewer.

The reviewer corroborates provenance, coverage, claims and finding resolution
against the actual subject and current upstream requirements. It can accept
existing review evidence where that evidence is sufficient, or produce the
ordinary findings that require a review/fix round. The same review examines
whether setup and validation are ready to run. Successful corroboration is an
upstream review decision, not a copy of the contributor's approval
(`sdlc/procedure/lifecycle/review`).

### Admission evidence

The contribution inspection surface exposes the pinned source, base, proposed
contracts and prior reports as data, independently of executable preparation.
Initial reviewer and waiting-builder bootstrap use upstream-owned instructions
and configuration. Their assigned review subject is the retained imported
worktree; the imported tree supplies no startup instructions or executable
configuration before admission.

The upstream reviewer records corroborated obligations, unresolved findings,
preparation gaps, execution readiness and remaining native checks in its
immutable contribution assessment report. The assigned reviewer submits it
through the contribution operation, which authenticates the assignment and
records its report digest and exact subject atomically. The admission decision binds that report and the exact
proposal subject. Admission readiness and completed build review are separate
facts: read-only admission records no claim that an outstanding check ran.
The workflow consumes the reviewer's declared decision, never inferring it
from report prose (`general/principle/intelligence-boundaries`).

### Continuation inside the lifecycle

The proposal's intake reviewer starts with the review assignment; its builder
starts with an explicit waiting assignment. Both use trusted upstream entry
and bind the adoption identity. Initial
materialization and later execution preparation are distinct operations; a
waiting builder runs neither setup nor proposed code before the review permits
that continuation.

The intake operation retains its report and source handoff before ending its
assigned sessions. It verifies that their recorded starts and sessions settled
before completing the ordinary-item handoff. Uncertain settlement retains the
operation and source. A genuine preparation handoff ends the intake assignment;
workers are not transferred into a later claiming group
(`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`).

The handoff creates an ordinary unprepared item or reuses existing approved work
that owns the proposal. Preparation and work enter through their ordinary
reservation-bound drivers. The normal work driver is the independent reviewer
and its child builder belongs to that driver's claiming group. They resume the
retained implementation and findings, consume the intake report as bound
evidence and review only the remaining obligations and actual delta. No second
mandatory intake review is inserted
(`local/projects/teleclaude/spec/feature/workflow/work-review-cycle`).

Accepted proposal contracts are associated with the local todo and made
available through the upstream authoring doc layer before ordinary lifecycle
continuation. Foreign pending-delivery identifiers are reconciled with that
association; unrelated upstream pending contracts remain intact. The imported
code and the accepted documentation stay one review subject. Preparation gaps
return through the existing prepare lane; they are not stamped away to start
build review. Findings resume the builder in the imported worktree rather than
rebuilding the proposal from an empty branch.

Read-only admission records which review obligations were corroborated and
which executable checks remain owed. It does not claim those checks ran. A
clean imported change enters the supported adoption transition without a
builder manufacturing an implementation commit. After acceptance, work uses
the project's normal development environment and quality obligations. Contribution origin adds no separate sandbox or second
review process. Changes made during repair, upstream-base reconciliation or
documentation adoption receive the review their actual delta owes. Only the
final accepted subject proceeds to normal integration; the upstream integrator
owns its documentation fold and mainline delivery.

### Use cases

#### UC-CAD1: The upstream reviewer is the first assessor

```gherkin
Given a contributor offers a revision with prior reviewer reports
When the upstream project begins adoption
Then its reviewer receives the pinned source and reports for corroboration
And materializing that review subject executes no contributor-supplied code
```

#### UC-CAD2: Sufficient prior evidence can satisfy upstream review

```gherkin
Given the upstream reviewer corroborates the prior reports against the current proposal and required contracts
When it finds that evidence sufficient for acceptance
Then it records its own acceptance for that reviewed subject
And the contribution can continue without repeating the satisfied review work
```

#### UC-CAD3: Findings continue in the imported worktree

```gherkin
Given an adopted contribution has a reviewer and a builder awaiting its findings
When the reviewer requests changes
Then the orchestrator supplies the findings to that builder
And repair and subsequent review continue on the adopted proposal
```

#### UC-CAD4: A new PR revision cannot inherit an older acceptance

```gherkin
Given the upstream reviewer examined one pinned revision
When the contributor publishes a different revision before adoption completes
Then the adoption record identifies the changed review subject
And the earlier verdict does not deliver the new revision
```

#### UC-CAD5: Adoption preserves upstream contract ownership

```gherkin
Given a contribution includes proposed documentation and foreign delivery identifiers
When an upstream agent adopts its contracts for accepted work
Then those contracts are associated with the owning local todo
And unrelated upstream pending contracts remain unchanged
And proposed intent is not represented as approved merely because it was imported
```

## Known caveats

- A review report is evidence about the subject it names, not an instruction to
  change the reviewer's role or bypass the upstream lifecycle.
- A report that cannot be corroborated may still guide investigation. It
  supplies no accepted verdict on its own.
