---
visibility: public
number: 0074
date: 2026-08-11
description: v1 is maintained with bug fixes and operator-needed changes until a vNext cut adopts a journey, replacing the approved-P0-only maintenance gate.
---

# v1 Is Maintained Until vNext Adoption — ADR

## Context

ADR-0068 froze v1 feature intake and confined it to "the failures required for it
to remain the temporary build host", on the premise that a vNext cut would adopt a
journey soon enough for that constraint to expire quickly. Ten domain anchors
restated that constraint independently as an approved-P0-only maintenance gate.

vNext adoption is further out than the freeze assumed, and v1 is not merely hosting
the build — it is the operating platform, and the work it needs to keep operating
is not confined to build-host failures. Practice diverged accordingly: defect fixes
and operator-needed changes ship regularly against a written contract that permits
neither.

The gate also has no mechanism behind it. There is no stamp, field, or command that
records an approved-P0 authorization, and the platform's own rules forbid an agent
writing a human's approval into a durable record. Reviewers therefore raise a
blocking finding that the process offers no way to answer, on work whose necessity
is not in dispute.

Ten independent restatements of one stance is also why the divergence went
unnoticed: no single line owned the boundary, so nothing became visibly wrong when
reality moved.

## Decision

v1 is maintained until a vNext cut adopts a journey. It receives bug fixes and the
changes its operators need to keep working. It does not acquire new architecture
that vNext is designed to replace; design authority for the replacement stays in
TeleClaudeNext.

The approved-P0-only maintenance gate is withdrawn. The maintenance stance is
stated once, in the domain glossary; domain anchors reference it rather than
restating it.

## Consequences

- Defect fixes and operator-needed changes proceed on their merits. The written
  contract matches what is shipped, so reviewers stop raising an authorization
  finding that has no mechanism to satisfy.
- The boundary that still holds is architectural, not procedural: v1 does not grow
  structures vNext exists to replace. That line is a judgement rather than a gate,
  and it will be argued case by case — which is a real cost compared to a
  bright-line rule, and is accepted deliberately.
- A single owner for the stance means the next revision changes one line. It also
  means anchors no longer carry their own boundary text, so a reader of one anchor
  must follow the reference to learn the stance.
- Removing the gate removes a brake. v1 can now accumulate work that vNext will
  discard, and nothing mechanical prevents that; only the architectural boundary
  and ordinary scope discipline do.
- The pressure that motivated the original freeze — v1's maintenance burden
  competing with replacement progress — is unresolved by this decision. It is
  traded for the cost of a contract nobody could satisfy.

## Alternatives Considered

- **Keep the gate and build the missing mechanism** — a stamp recording a P0
  authorization. Rejected: it would formalize a constraint that practice has
  already overtaken, and spend design effort making an obsolete gate satisfiable.
- **Keep the gate and rely on case-by-case exceptions.** Rejected: every change
  then requires an authorization the record cannot hold, so the exception becomes
  the path and the written contract becomes decoration.
- **Leave the anchors restating the stance independently.** Rejected: ten copies
  are why this divergence survived unnoticed, and the next shift would strand nine
  of them again.
