---
description: Review a lifecycle build by slug against its prepared intent, plan, implementation, and shared review contract.
---

# Review Build — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/review.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Review the implementation dispatched for one slug against its approved intent,
prepared artifacts, and standards. The slug supplies the review context; the
shared review procedure supplies the review judgment.

## Preconditions

- The slug was supplied by the dispatching work orchestrator.
- The approved intent artifact resolves: `prd` for a `feature`; `input` for a
  `change` or `bug`; the implementation plan's _Intent & scope_ for a planned
  change with no input.
- `implementation-plan` exists for every kind.
- `architecture` is readable when present and not skipped.
- `quality-checklist` exists with Build and Review sections.
- The build phase completed for the slug.

## Steps

### 1. Establish the slug's review context

Use the slug supplied by the dispatch. A build reviewer never selects work from
`telec todo list`.

Apply the artifact-discovery rule from
`software-development/policy/preparation-artifact-quality`: list the slug's
artifacts, read `log` when present, and read every artifact relevant to the
review.

Read in full:

- The kind-resolved approved intent artifact. For a bug, also read
  `diagnosis`. Historical `requirements` artifacts remain readable records but
  carry no live intent fallback.

- `architecture` when present, plus the domain or design snippets it indexes.
- `implementation-plan`.
- `plan-review-findings`.
- `quality-checklist`.
- The relevant project README, generated agent instructions, and current
  project documentation through `telec docs`.

The intent artifact outranks the plan as scope authority. A behavioral delta
that the intent does not call for is a Critical scope finding even when the
approved plan contains it. For a bug, `input` sharpened by `diagnosis` is the
scope authority.

State what every required outcome promises before running a lane. Reading only
the diff is insufficient.

Use merge-base to focus the implementation diff:

```bash
git diff $(git merge-base HEAD main)..HEAD --name-only
git diff $(git merge-base HEAD main)..HEAD
```

Orchestrator-managed state files are task context. Do not raise findings for
them unless the review scope explicitly includes planning or state edits.

### 2. Check build completeness

- Every implementation-plan task is checked.
- Every deferral is justified.

An unchecked task or unjustified deferral yields `REQUEST CHANGES`.

### 3. Execute the shared review contract

Execute `software-development/procedure/lifecycle/review` in full.

For this invocation:

- The target is the dispatched slug.
- The applicable contract is the approved intent and its success criteria.
- The scope lane runs.
- All catalog lanes run according to their trigger conditions.
- Builder evidence in `quality-checklist` directs attention but never
  substitutes for independent proof.

### 4. Persist the build-review result

Write the complete findings to:

```bash
telec todo artifacts write {slug} review-findings "<content>"
```

Stamp the arithmetic verdict:

```bash
telec todo stamp {slug} --verdict approve|changes_requested --phase build_review
```

Report the summary and verdict to the work orchestrator. The reviewer writes no
other artifact and makes no source change.

## Report format

```text
REVIEW COMPLETE: {slug}

Requirement-Violations:
- <finding with citation>

Critical:
- <finding with citation>

Important:
- <finding with citation>

Verdict: APPROVE | REQUEST CHANGES
```

## Outputs

- `review-findings` persisted on the dispatched slug.
- `build_review` verdict stamped on the dispatched slug.
- Summary and verdict reported to the work orchestrator.

## Recovery

If the slug or a required prepared artifact cannot be resolved, report the
blocker and stop. Never select another todo as a substitute.
