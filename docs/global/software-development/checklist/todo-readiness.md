---
description:
  Five criteria for implementation-ready todos. Single-session, verifiable,
  atomic, clear scope, known approach. Guides work breakdown.
id: software-development/checklist/todo-readiness
scope: domain
type: checklist
---

# Todo Readiness — Checklist

## Goal

A todo is ready for implementation when it meets all five criteria. If any criterion fails,
split or clarify before assigning work.

## Preconditions

- The task has a clear owner and scope.
- The target area of the codebase is known.
- The desired outcome is stated.

## Steps

1. **Single-session fit** — can one AI session complete it without context exhaustion?
   - Task fits within typical context window.
   - No deep dependency chains.
   - Scope is bounded.
2. **Checkable success** — are outcomes concrete and verifiable?
   - Observable acceptance criteria.
   - Tests or checks can prove completion.
   - Definition of done is unambiguous.
3. **Safe integration** — can the work be committed without breaking the system?
   - Changes are incremental.
   - No half-finished states.
   - Clear entry/exit points.
4. **Clear requirements** — is context sufficient for pragmatic decisions?
   - Requirements cover what and why.
   - Edge cases addressed or deferred.
   - Patterns and constraints are known.
5. **Known approach** — is the technical path established?
   - Known patterns apply.
   - No significant unknowns needing research.
   - Stack is familiar.

## Outputs

- **Ready**: proceed to implementation planning.
- **Not ready**: split or clarify before assigning.

## Recovery

- Too large → split into smaller todos with dependencies.
- Unclear requirements → clarify with the user before planning.
- Unknown approach → create a research todo first.
- Cross-cutting concerns → separate infrastructure from feature work.
