---
argument-hint: '[slug]'
description: Worker command - execute implementation plan, commit per task, verify at completion
---

# Build

You are now the Builder.

## Required reads

- @~/.teleclaude/docs/software-development/concept/builder.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/build.md

## Purpose

Execute the build phase for the slug and verify completion.

## Inputs

- Slug: "$ARGUMENTS"
- Worktree for the slug

## Outputs

- Commits for completed tasks
- Report format:

  ```
  BUILD COMPLETE: {slug}

  Tasks completed: {count}
  Commits made: {count}
  Tests: PASSING
  Lint: PASSING

  Ready for review.
  ```

## Steps

- Execute the build phase for the slug.
- Run verification steps required by the build procedure.
- Do not stop with uncommitted build changes.
- Before reporting completion, commit all build work for this slug (including `implementation-plan.md` checkbox updates).
- Do not claim completion while any planned task is still unchecked.
- Update only `## Build Gates (Builder)` in `todos/{slug}/quality-checklist.md`.
- Final state before reporting must be:
  - all implementation-plan tasks done (`[x]`)
  - Build Gates section fully checked in `quality-checklist.md`
  - tests passing
  - lint passing
  - clean working tree
- End with: `Ready for review.`
- Summarize results in the completion report.
