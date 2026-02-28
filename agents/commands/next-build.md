---
argument-hint: '[slug]'
description: Worker command - execute implementation plan, commit per task, verify at completion
---

# Build

You are now the Builder.

## Required reads

- @~/.teleclaude/docs/software-development/concept/builder.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/policy/version-control-safety.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/build.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/demo.md

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
- Never use stash workflows; keep worktree transitions commit-based.
- Do not stop with uncommitted build changes.
- Before reporting completion, commit all build work for this slug (including `implementation-plan.md` checkbox updates).
- Do not claim completion while any planned task is still unchecked.
- Update only `## Build Gates (Builder)` in `todos/{slug}/quality-checklist.md`.
- Final state before reporting must be:
  - all implementation-plan tasks done (`[x]`)
  - Build Gates section fully checked in `quality-checklist.md`
  - tests passing
  - lint passing
  - clean working tree for build-scope changes; pre-existing orchestrator-managed planning/state drift is allowed:
    - `todos/roadmap.yaml`
    - `todos/{slug}/state.yaml`
  - do not commit those orchestrator-managed drift files unless this build explicitly requires planning/state edits
  - if only those files are dirty, continue to completion without extra escalation about cleanliness
- Before reporting BUILD COMPLETE, run these steps in order:
  1. Run `telec todo verify-artifacts {slug} --phase build` — if it fails, fix the gaps and retry until it passes.
  2. Call `telec todo mark-phase {slug} --phase build --status complete`.
  3. Then report BUILD COMPLETE.
- End with: `Ready for review.`
- Summarize results in the completion report.
