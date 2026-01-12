# Roadmap

> **Last Updated**: 2026-01-12
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Worktree Workflow - Blocking Bug

- [>] startup-cache-hook-fixes
      Two bugs: (1) Hook receiver doesn't pass agent_name, causing "missing active_agent"
      errors on manual agent starts. (2) Redis adapter doesn't populate cache on startup,
      breaking remote computer/project discovery.

---

## Work Preparation Pipeline

- [.] delivery-verification-gates
      Prevent incomplete work from being marked delivered. Workers create deferrals.md,
      reviewers verify success criteria with evidence, orchestrators resolve deferrals.

---

## Test Suite Quality Cleanup

- [.] test-cleanup
  Refactor test suite to verify observable behavior, add docstrings, document system boundaries.
