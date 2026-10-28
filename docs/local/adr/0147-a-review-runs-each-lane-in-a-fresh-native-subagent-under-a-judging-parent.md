---
visibility: public
number: 0147
date: 2026-10-28
description: A review's parent builds the lane set, runs each applicable lane in a fresh native subagent from a lean brief, and keeps judgment of the whole and the verdict.
---

# A review runs each lane in a fresh native subagent under a judging parent — ADR

## Context

ADR-0017 made the review lanes one shared catalog. One reviewer then executed
every applicable lane itself, carrying the whole catalog, the SDLC baseline and
the target at once. In the commit review of the session-start shell guidance,
that reviewer passed the ownership lane with a sentence it had not established:
agent-specific shell rules sat in the generic hook receiver, a boundary the
adapter contract assigns to the agent adapters. Its own post-mortem found the
instructions already required the check; it had the direction and did not apply
it. Adding further rules to the same single session was not expected to change
that outcome.

The human directed that reviews split into focused lanes run by subagents of
the reviewer, with the reviewer routing, briefing them leanly from context it
holds itself, and judging the whole rather than collecting results.

## Decision

A review's parent establishes the intent and the governing contracts, builds
the lane set from the general catalog plus the project focus points its fixed
entry points reach, and gives each lane a disposition. Each applicable lane
runs in its own fresh native subagent of the reviewer's harness, never a fork
of the reviewer's conversation, from a brief that is its whole mandate: one
question, exact read addresses, established facts and verbatim owner excerpts.
The domain bundle is the parent's; a lane child reads only what its question
requires. Lane children investigate and return evidence; every session act
stays with the parent. The parent re-runs unsupported lane results, routes
contradictions back, assesses coverage and fit of the whole itself, and alone
writes the verdict.

## Consequences

- Each lane receives an investigation with its full attention, and a fresh
  child can catch what the parent misreads; the first trial observed one such
  catch.
- The parent's responsibility grows rather than shrinks: lane selection, brief
  quality and reconciliation decide the review's quality, and a poor brief or
  a steering one degrades every lane it reaches.
- Total cost rises with the number of applicable lanes: each child receives
  the instructions its harness injects at startup, even though it no longer
  loads the domain bundle.
- Children act under the parent's platform identity, so the boundary on
  session acts rests on the brief, not on a runtime gate.
- Briefs are not readable in every harness's transcript afterwards; the report
  carries each lane's question so coverage stays auditable.
- Whether reviews catch more of what matters is not established by adopting
  this design. It is judged by what escapes approval afterwards and by
  replaying past misses, not by finding counts.

## Alternatives Considered

- **One reviewer executing every lane, with more instructions.** Rejected: the
  failure occurred with the governing instruction already present.
- **A meta-reviewer judging the review.** Rejected: a second judge reading a
  persuasive report can accept the same false premise, and model errors
  correlate; it adds a layer without adding an independent investigation.
- **Lanes as separately dispatched platform sessions.** Rejected: confined
  review roles hold no dispatch reach by design, and native subagents give
  fresh context without platform reach or session bookkeeping.
- **Lane children loading the full domain bundle.** Rejected: it repeats per
  lane a read the parent already holds, multiplies cost and adds no judgment.
