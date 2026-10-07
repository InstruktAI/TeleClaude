---
visibility: public
number: 113
date: 2026-10-07
description: The authoring session decides whether a commit owes independent review and stamps a discarded candidate itself; every commit-review outcome is a stamp, recorded on the todo its session chain claims, so lifecycle gates read verdicts instead of trusting transcripts.
---

# ADR-0113: Commit Authors Discard Review Candidates; Verdicts Are Stamps — ADR

## Context

ADR-0033 made every doc-snippet commit require an independent doc-hygiene
review, and the post-commit gate routes code commits to review the same way.
In practice many commits change no contract at all: a removal, a mechanical
correction, a restatement already decided elsewhere. Each still cost a
reviewer dispatch and a wait.

Commit review also left no durable outcome. The verdict existed only as text in
the reviewer's transcript, and the checkpoint's review gate was discharged by
the dispatch, not by a verdict. A prepare orchestrator could therefore derive
`PREPARED`, release its claim and end its children while a commit reviewer was
still working on that session's commits; nothing the lifecycle reads knew a
review was open.

Reviewer liveness cannot carry the outcome: commit reviewers stay open after
approving, so they keep the context of what they reviewed for later passes.

## Decision

- The post-commit gate names review candidates; it does not decide that review
  is owed. The authoring session decides per commit. A commit that changes a
  contract, a behavior, a process or what a governed text says goes to an
  independent reviewer. A commit that changes none of these is discarded as a
  candidate.
- Discarding is not reviewing. The author does not judge its change correct; it
  records that no review is owed, with a reason.
- Every outcome is a stamp on the commit SHAs, given through one command by
  either the reviewer (its verdict) or the author (its discard). The stamp lands
  in the review state of the todo that the stamping session's chain claims, and
  on no todo when the chain claims none. It discharges the checkpoint's
  post-commit review gate for those commits.
- Lifecycle gates read stamps. `PREPARED` is withheld while a commit the driving
  session authored under its claim lacks an `approve` stamp.

## Consequences

- Commits that owe nothing cost one stamp instead of a reviewer cycle.
- The independent-review guarantee of ADR-0033 now depends on the author's
  judgment of what owes review. A discard is attributable — the stamp names the
  session and its reason — but it is not checked by a second party.
- Commit review gains durable lifecycle state, which it previously avoided on
  purpose; the state is limited to the todo the session chain already claims.
- A handoff can no longer outrun an open review: the machine names the unstamped
  SHAs instead of deriving `PREPARED`.
- Reviewers keep their sessions after approving; nothing reads their liveness.

## Alternatives Considered

- **Keep mandatory independent review of every candidate.** Rejected: it spends
  reviewer cycles on commits that change no contract, and that cost is what
  pushed agents to route around the gate.
- **A separate verdict table keyed by SHA.** Rejected: a second store for review
  state beside the todo state the lifecycle already reads.
- **Treat a closed reviewer session as approval.** Rejected: reviewers stay open
  after approving to keep their context.
- **Have the orchestrator remember to wait for open reviews.** Rejected: a
  remembered step is the one that fails; the machine has to see the outcome.
