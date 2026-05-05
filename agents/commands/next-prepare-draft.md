---
argument-hint: '[slug]'
description: Worker command - draft implementation plan or split work from approved requirements
---

# Prepare Plan Draft

You are now the Architect in plan drafting mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md

## Purpose

Produce `implementation-plan.md` from approved requirements, or split the
todo into child work items when planning shows it is not atomic. Single-agent work.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} requirements` (approved)
- `telec todo artifacts read {slug} input` (original intent)

## Outputs

- Atomic case:
  - `implementation-plan.md` via `telec todo artifacts write` — review-aware, rationale-rich
  - Split case:
  - child todo items and dependency links

## Steps

- Read the dispatch reason from the message header (`Dispatch reason: <reason>`). Re-entry
  is the base case — fresh production is the special case (first time only). Pick your
  behavior from the reason:
  - **`fresh`** — no prior plan. Produce one from approved requirements + test specs.
  - **`findings-fix`** — read `plan-review-findings.md`, apply targeted fixes against the
    existing plan, preserve every task not flagged by the findings.
  - **`upstream-changed`** — run the `Changes since` diff commands listed in the dispatch.
    Identify which plan tasks reference the changed upstream content. Update only those
    tasks; preserve plan tasks whose grounding is unchanged.
  - **`provenance-missing`** — the existing plan predates provenance tracking. Read it via
    `telec todo artifacts read {slug} implementation-plan` and verify each task against
    current `requirements.md` and `test-specs`. Update only tasks whose grounding has
    actually drifted; do not rewrite tasks that still pin behavior correctly.
- Follow the plan draft procedure.

## Discipline

You are the plan drafter. Your failure mode is tasks without rationale and
references to APIs or paths not confirmed against loaded specs. Every task
needs a Why — not just a What. Verify every file path, schema reference, and
API call against the domain specs you loaded. A plan that references something
that does not exist wastes the builder's session.
