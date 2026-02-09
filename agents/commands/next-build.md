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
- Summarize results in the completion report.
