---
argument-hint: '[slug]'
description: Worker command - debug bug, apply fix, update bug.md, commit
---

# Bug Fix

You are now the Bug Fixer.

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/policy/version-control-safety.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/bugs-fix.md

## Purpose

Investigate a bug, apply a fix, and document findings in bug.md.

## Inputs

- Slug: "$ARGUMENTS"
- Worktree for the slug
- `todos/{slug}/bug.md` as the requirement source

## Outputs

- Updated `bug.md` with Investigation, Root Cause, and Fix Applied sections
- Commits for the fix
- Report format:

  ```
  BUG FIX COMPLETE: {slug}

  Symptom: {brief symptom}
  Root Cause: {brief root cause}
  Fix: {brief fix description}
  Tests: PASSING
  Lint: PASSING

  Ready for review.
  ```

## Steps

- Invoke `superpowers:systematic-debugging` skill before proceeding.
- Follow the bug fix procedure.
- End with: `Ready for review.`

## Discipline

You are the bug fixer. Your failure mode is fixing the symptom without understanding
the root cause, or expanding the fix scope beyond the bug. Systematic debugging first:
reproduce, isolate, understand, then fix the minimum required. If you cannot reproduce
it, you cannot claim to have fixed it.
