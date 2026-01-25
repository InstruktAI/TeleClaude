---
description:
  Five criteria for implementation-ready todos. Single-session, verifiable,
  atomic, clear scope, known approach. Guides work breakdown.
id: software-development/todo-readiness
scope: domain
type: checklist
---

# Todo Readiness — Checklist

## Goal

A todo is ready for implementation when it meets all five criteria. If any criterion fails, apply story splitting patterns to break it down further.

Can one AI session complete this before context exhaustion?

- Task fits within typical context window
- No deep dependency chains requiring multiple investigation phases
- Scope bounded enough for single worker to hold in context

Are success criteria concrete and checkable? Can tests prove completion?

- Requirements specify observable outcomes
- Tests can verify behavior
- Definition of done is unambiguous

Can the work be committed without breaking the system? Are there clean boundaries?

- Changes can be integrated incrementally
- No half-finished states that break builds
- Clear entry and exit points

Are requirements unambiguous? Does the AI have enough context for pragmatic decisions?

- Requirements answer "what" and "why"
- Edge cases addressed or deferred explicitly
- Architectural patterns clear
- Worker can make reasonable implementation choices without escalation

Is the technical approach known, or does this need exploration first?

- Known patterns and solutions apply
- No significant unknowns requiring research
- Technology stack is familiar

If any criterion fails, **don't defer it to the worker** - break it down:

- Too large → Split into smaller todos with dependencies
- Unclear requirements → Clarify with user before creating implementation plan
- Unknown approach → Create research todo first, then implementation todo
- Cross-cutting concerns → Separate infrastructure from feature work

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
