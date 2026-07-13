---
description: 'Build phase. Execute implementation plan tasks, commit per task, and manage deferrals.'
needs_domain_baseline: true
visibility: 'public'
---

# Build — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/builder.md
- @~/.teleclaude/docs/software-development/policy/quality-predicate-registry.md

## Goal

Execute the implementation plan for a todo and produce verified, review-ready changes.

## Preconditions

- `telec todo artifacts read {slug} implementation-plan` exists and is readable.
- The approved intent artifact is readable — `prd` for a `feature`, or `input`
  for a `change`/`bug` (see `software-development/concept/approved-intent-artifact`).
  For `change`/`bug` there is no PRD; that is intended, not a defect, and the
  implementation-plan (or, for a bug, the fix) is grounded in `input`. A `change`
  created via `--plan` has no `input` either — its `implementation-plan`'s
  _Intent & scope_ is the intent basis; the missing `input` is intended, not a defect.
- `architecture` (thin doc-edit log) is readable when present and not skipped; consult the domain/design snippets it points to for technical context.
- `telec todo artifacts read {slug} quality-checklist` exists and includes `## Build Gates (Builder)`.
- The todo scope is implementable in one build phase.

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

Apply the artifact-discovery rule from `preparation-artifact-quality`
(`telec todo artifacts list {slug}`) before assuming only the numbered
artifacts below exist — read `log` when present, and any other present
artifact relevant to executing this plan.

1. Read the PRD artifact via `telec todo artifacts read {slug} prd` to confirm
   intent, success criteria, and scope constraints. If `prd` is absent but legacy
   `requirements` exists, read `requirements` as the legacy intent contract. If the
   todo is prepped (no PRD or legacy requirements artifact exists), skip this step —
   the implementation-plan artifact is the combined spec-and-plan.
2. Read `architecture` when present and not skipped — it is the thin
   doc-edit log; consult the domain/design snippets it points to for
   technical context and intended invariants. The PRD's success criteria are
   the verification contract.
3. Read the implementation-plan artifact via
   `telec todo artifacts read {slug} implementation-plan` and identify the tasks
   not yet delivered by commits in the worktree.
4. Work from the scenario delta. The prepared artifacts identify the feature-spec scenarios this
   todo delivers — added, changed, and removed. For each:
   - **Added scenario** — bind it: write the test at the spec-mirrored path, confirm it fails,
     implement, confirm it passes.
   - **Changed scenario** — update the bound test to the new contract, confirm it fails against the
     current code, update the code, confirm it passes.
   - **Removed scenario** — delete its bound test, then the code it exclusively covered.
     You bind the scenarios the spec defines; you never invent what to test. See `policy/testing`.
5. Execute tasks sequentially:
   - Follow the build mode determined in step 4.
   - Commit changes for the task (one commit per task). The commit is the record
     that the task is done — the implementation-plan artifact is prepare-owned and
     not writable from a work-phase session.
   - Keep the flow commit-based inside the current worktree.
   - When a test or check disagrees with the current code, do the intent-resolution work before fixing either side. Ascertain what is leading for the active objective, then fix the stale side of the mismatch.
   - When adding or updating tests, assert behavioral contracts at public boundaries. Do not satisfy a task with logger assertions, log-level checks, config/model shape checks, private-helper tests, constructor/DI wiring captures, or mock-call echoes. If the plan asks for those, reinterpret it to the nearest behavior; if no behavior exists yet, surface the plan defect instead of inventing fake coverage.

   ### Snapshot acceptance

   When test output shows snapshot diffs, read each diff before accepting it. If
   the diff matches the task's stated intent, rerun with
   `telec code test --update-snapshots` and commit the updated snapshot files
   with the task. If the diff does not match intent, the code change is wrong:
   fix the code and do not update the snapshot. Concrete idioms and migration
   patterns live in `software-development/procedure/snapshot-testing`.

6. If a task is truly out of scope, create `deferrals.md` with the required template and continue with remaining tasks.
7. **Plan tasks that violate intelligence-boundaries.** If a plan task asks
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

### Test-quality self-review

Before declaring the build complete, apply every `TQ-*` predicate in the
quality-predicate registry. Under `Build Gates (Builder)` in the
`quality-checklist` artifact, record one line per ID: concrete evidence for a
triggered predicate or `N/A` with a reason. Name the production mutation each
behavioral or smoke test kills. A green suite is execution evidence, not this
self-review.

## Pre-completion checklist

1. Every implementation-plan task is delivered by a commit or explicitly recorded in `deferrals.md`.
2. Tests pass: `telec code test`.
3. Every in-scope added or changed scenario is bound and passing; removed scenarios' tests are deleted.
4. No spec-bound assertion weakened or deleted; no in-scope spec has orphan bindings (run
   `tools/lint/spec_coverage.py` on demand to check).
5. Every `TQ-*` predicate has builder evidence or a reasoned `N/A` in
   `quality-checklist`.
6. Lint passes: `telec code lint`.
7. User-facing verification:
   - For browser-based frontend or web UI changes, run a Playwright smoke test in a real browser that exercises the changed path. Record the path exercised and the observed result in `quality-checklist.md` under the Build section.
   - For other user-facing changes (CLI output, TUI, interactive behavior), verify the change is observable and record what was checked and the result in `quality-checklist.md`.
   - If verification is not possible in the build environment, note the gap explicitly in `quality-checklist.md`.
8. Working tree is clean: `git status`.
   - If not clean, commit all remaining files in the worktree. Everything in the worktree belongs to the task.
9. Verify commits exist: `git log --oneline -10`.
10. Stamp explicit build completion: `telec todo stamp {slug} --build-complete`.

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
- Commits for each task.
- Optional `deferrals.md` when scope must be escalated.

## Recovery

- If a task fails, analyze the error and retry.
- If stuck after two attempts, stop and report the blocker.
