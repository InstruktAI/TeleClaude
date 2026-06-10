---
description: 'Software development lifecycle. Three-stage model: prepare, work, integrate.'
visibility: 'public'
---

# Lifecycle Overview — Procedure

## Goal

The software development lifecycle follows a three-stage model, each driven by its own state machine via the `telec todo` CLI.

### 1. Prepare (`telec todo prepare`)

Sequential artifact production with review gates:

- **Human refinement / handoff** — human edits preparation artifacts directly; the next `telec todo prepare [slug]` dispatch re-derives the lifecycle phase from the updated evidence
- **Intake** — derive and approve `prd` from `input` or live conversation
- **Architecture** — derive and approve the code-grounded technical brief, or skip with reason when it does not earn its place
- **Plan drafting** — produce `implementation-plan` (or split the todo); plan tasks reference PRD criteria, architecture constraints, and feature-spec scenarios
- **Plan review** — validate plan against policies, DoD gates, review lanes
- **Readiness gate** — formal DOR validation on the complete artifact set
- **Grounding check** — verify freshness of referenced files and policies

Outputs: `prd`, optional `architecture`, `implementation-plan`.

### 2. Work (`telec todo work`)

Build-review-fix-finalize cycle:

- **Build** — bind the feature-spec scenarios in scope and implement the code that satisfies them (RED-GREEN by scenario delta); execute implementation plan task-by-task, commit per task
- **Review** — parallel review lanes (scope, code, principles, security, tests, errors, types, comments, docs)
- **Fix** — address review findings minimally, re-review (capped at `max_review_rounds`)
- **Finalize** — integrate latest main, push branch, hand off to integration
- **Deferrals** — process deferred items into new todos
- **Bug fix** — systematic debugging for bug-type work items

### 3. Integrate (`telec todo integrate`)

Merge candidates to canonical main:

- **Squash merge** — single commit capturing full delivery intent
- **Conflict resolution** — resolve in integration worktree
- **Push** — advance `origin/main`
- **Delivery bookkeeping** — todo list update and worktree cleanup

### Principles

- **Serial execution**: one phase runs, completes, then the next begins
- **Deterministic handoffs**: every step ends cleanly before the next begins
- **No micromanagement**: orchestrator dispatches and monitors; workers implement autonomously
- **Quality gates**: pre-commit hooks enforce standards; review validates completeness

## Preconditions

- `telec todo list` shows items.
- On the first DB-backed access to an old project, TeleClaude auto-imports legacy markdown todo indexes into an empty `todos.db`. Detection requires an empty database plus at least one legacy index file (`roadmap.md`, `icebox.md`, `delivered.md`, or `bugs.md`).

## Steps

1. Run `telec todo prepare [slug]` to produce and validate preparation artifacts.
2. Run `telec todo work [slug]` to build, review, fix, and finalize.
3. Run `telec todo integrate [slug]` to merge to canonical main.

## Outputs

- Delivered work item merged to main.
- Updated todo list and delivery records.

## Recovery

- Each state machine is crash-safe — re-calling resumes from last persisted state.
- If blocked, record deferrals and reschedule the work item.
- Legacy-project import is one-shot. After the first successful import, TeleClaude stays DB-backed and does not re-read the markdown indexes on later calls.

## See also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/overview.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/integrate.md
