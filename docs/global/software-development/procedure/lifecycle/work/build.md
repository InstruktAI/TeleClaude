---
description: 'Build phase. Execute implementation plan tasks, commit per task, and manage deferrals.'
id: 'software-development/procedure/lifecycle/work/build'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Build — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/policy/version-control-safety.md

## Goal

Execute the implementation plan for a todo and produce verified, review-ready changes.

## Preconditions

- `telec todo artifacts read {slug} implementation-plan` exists and is readable.
- `telec todo artifacts read {slug} requirements` exists and is readable — **unless**
  the todo is prepped (`state.kind == "prepped"`), in which case there is no
  requirements artifact and the implementation-plan is the sole spec.
- `telec todo artifacts read {slug} quality-checklist` exists and includes `## Build Gates (Builder)`.
- The todo scope is implementable in one build phase.

## Steps

1. Read the requirements artifact via `telec todo artifacts read {slug} requirements`
   to confirm intent and constraints. If the todo is prepped (no requirements artifact
   exists), skip this step — the implementation-plan artifact is the combined
   spec-and-plan.
2. Read the implementation-plan artifact via
   `telec todo artifacts read {slug} implementation-plan` and identify unchecked tasks.
3. Determine the build mode from the nature of the work:
   - **Spec-satisfaction (default):** Pre-written xfail test specs exist. For each task, remove the expected-failure marker, then write the implementation that makes the test pass. This is the standard RED-GREEN-REFACTOR flow.
   - **Characterization:** The deliverable is test coverage for existing untested code (no pre-written specs). Follow the OBSERVE-ASSERT-VERIFY cycle from the testing policy. Coverage depth at meaningful public boundaries is the primary output — pin actual behavior, verify each test catches mutations, discard shallow tests that survive production faults.
4. Execute tasks sequentially:
   - Follow the build mode determined in step 3.
   - Commit changes for the task (one commit per task).
   - Update the task checkbox to `[x]` and include that change in the same commit.
   - Do not use `git stash`/`git stash pop`; keep the flow commit-based inside the current worktree.
   - When a test or check disagrees with the current code, do the intent-resolution work before fixing either side. Ascertain what is leading for the active objective, then fix the stale side of the mismatch.
   - When adding or updating tests, assert behavioral contracts; avoid exact wording assertions on docs/agent prose unless execution depends on that exact token.

   ### Snapshot acceptance

   When test output shows snapshot diffs, read each diff before accepting it. If
   the diff matches the task's stated intent, rerun with
   `telec code test --update-snapshots` and commit the updated snapshot files
   with the task. If the diff does not match intent, the code change is wrong:
   fix the code and do not update the snapshot. Concrete idioms and migration
   patterns live in `software-development/procedure/snapshot-testing`.
5. If a task is truly out of scope, create `deferrals.md` with the required template and continue with remaining tasks.
6. **Plan tasks that violate intelligence-boundaries.** If a plan task asks
   you to build a classifier, scorer, judge, evaluator, or auto-fixer on
   free-text content, stop. Per `principle/intelligence-boundaries`, the
   principle outranks the plan. Surface as a blocker and report back —
   the plan needs to change. Do not faithfully execute a task that
   substitutes code for the agent's judgment. Detection patterns:
   hardcoded vocabulary tables (`_ACK_*`, `_KEYWORDS`, `_HINTS`); regex /
   word-count thresholds making semantic decisions on free text;
   `is_meaningful` / `should_emit` / `is_actionable` predicates on
   natural language; auto-fixers rewriting agent artifacts to match
   structural rubrics. The defining test: would this code be unnecessary
   if the agent's briefing said the right thing?

## Pre-completion checklist

1. All tasks in `implementation-plan.md` are `[x]`.
2. Tests pass: `telec code test`.
3. All expected-failure markers removed for in-scope test specifications (spec-satisfaction mode).
4. No test assertions weakened or deleted from spec-delivered tests (spec-satisfaction mode).
   For characterization mode: each test verified via mutation check (VERIFY step).
5. Lint passes: `telec code lint`.
6. User-facing verification:
   - For browser-based frontend or web UI changes, run a Playwright smoke test in a real browser that exercises the changed path. Record the path exercised and the observed result in `quality-checklist.md` under the Build section.
   - For other user-facing changes (CLI output, TUI, interactive behavior), verify the change is observable and record what was checked and the result in `quality-checklist.md`.
   - If verification is not possible in the build environment, note the gap explicitly in `quality-checklist.md`.
7. Working tree is clean: `git status`.
   - If not clean, commit all remaining files in the worktree. Everything in the worktree belongs to the task.
8. Verify commits exist: `git log --oneline -10`.
9. Stamp explicit build completion: `telec todo stamp {slug} --build-complete`.

## Report format

```
BUILD COMPLETE: {slug}

Tasks completed: {count}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for review.
```

## Outputs

- Code changes implementing the plan.
- Updated `implementation-plan.md` with checked tasks.
- Commits for each task.
- Optional `deferrals.md` when scope must be escalated.

## Recovery

- If a task fails, log the error in `implementation-plan.md` notes and retry.
- If stuck after two attempts, stop and report the blocker.
