---
argument-hint: '[slug]'
description: Worker command - debug bug, apply fix, update bug.md, commit
---

# Bug Fix

You are now the Bug Fixer.

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/policy/version-control-safety.md

## Purpose

Investigate the bug, apply a fix, and document findings in bug.md.

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

- FIRST: Invoke `superpowers:systematic-debugging` skill before proceeding
- Read `todos/{slug}/bug.md` to understand the symptom and discovery context
- Investigate the bug following the debugging skill's guidance
- Document your investigation in the `## Investigation` section of `bug.md`
- Identify and document the root cause in the `## Root Cause` section
- Apply the minimal fix required
- Document what you changed in the `## Fix Applied` section
- Commit the fix and `bug.md` updates together
- Run tests: `make test`
- Run lint: `make lint`
- Verify working tree is clean
- End with: `Ready for review.`
- Summarize results in the completion report
