# Roadmap

> **Last Updated**: 2026-01-12
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Worktree Workflow - Blocking Bug

- [ ] worktree-preparation
      Worktree preparation missing. Workers get vague "ensure dependencies" instructions,
      run `make install` from worktree, hijack main daemon. Need project-owned preparation
      hook and guards on install/init scripts.

---

## Test Suite Quality Cleanup

- [>] test-cleanup
      Refactor test suite to verify observable behavior, add docstrings, document system boundaries.

---

## Work Preparation Pipeline

- [>] todo-breakdown-assessment
      Add Definition of Ready check to next-prepare. Detects complex todos from input.md
      and breaks them into smaller child todos before requirements/plan creation.

- [ ] delivery-verification-gates
      Prevent incomplete work from being marked delivered. Workers create deferrals.md,
      reviewers verify success criteria with evidence, orchestrators resolve deferrals.

