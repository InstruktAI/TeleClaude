---
description: 'Software development lifecycle. Three-stage model: prepare, work, integrate.'
id: 'software-development/procedure/lifecycle/overview'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
---

# Lifecycle Overview — Procedure

## Goal

The software development lifecycle follows a three-stage model, each driven by its own state machine via the `telec todo` CLI.

### 1. Prepare (`telec todo prepare`)

Sequential artifact production with review gates:

- **Input refinement** — human refines thinking via `next-refine-input`
- **Discovery** — derive `requirements.md` from `input.md` (solo or triangulated)
- **Requirements review** — validate requirements against quality standard
- **Test specification** — write expected-failure test specs encoding behavioral requirements
- **Test spec review** — validate test specs for behavioral focus and convention compliance
- **Plan drafting** — produce `implementation-plan.md` and `demo.md` (or split the todo); plan tasks reference specific expected-failure tests they make GREEN
- **Plan review** — validate plan against policies, DoD gates, review lanes
- **Readiness gate** — formal DOR validation on the complete artifact set
- **Grounding check** — verify freshness of referenced files and policies

Outputs: `requirements.md`, test specification files (expected-failure-marked), `implementation-plan.md`, `demo.md`.

### 2. Work (`telec todo work`)

Build-review-fix-finalize cycle:

- **Build** — satisfy existing test specifications by implementing the code they specify; execute implementation plan task-by-task, commit per task
- **Review** — parallel review lanes (scope, code, principles, security, tests, errors, types, comments, demo, docs)
- **Fix** — address review findings minimally, re-review (capped at `max_review_rounds`)
- **Finalize** — integrate latest main, push branch, hand off to integration
- **Deferrals** — process deferred items into new todos
- **Demo** — validate during build, execute after merge, present via `/next-demo`
- **Bug fix** — systematic debugging for bug-type work items

### 3. Integrate (`telec todo integrate`)

Merge candidates to canonical main:

- **Squash merge** — single commit capturing full delivery intent
- **Conflict resolution** — resolve in integration worktree
- **Push** — advance `origin/main`
- **Delivery bookkeeping** — roadmap update, demo snapshot, worktree cleanup

### Principles

- **Serial execution**: one phase runs, completes, then the next begins
- **Deterministic handoffs**: every step ends cleanly before the next begins
- **No micromanagement**: orchestrator dispatches and monitors; workers implement autonomously
- **Quality gates**: pre-commit hooks enforce standards; review validates completeness

Work state lives in `todos/{slug}/state.yaml`.

## Preconditions

- Work item exists in `todos/roadmap.yaml`.

## Steps

1. Run `telec todo prepare [slug]` to produce and validate preparation artifacts.
2. Run `telec todo work [slug]` to build, review, fix, and finalize.
3. Run `telec todo integrate [slug]` to merge to canonical main.

## Outputs

- Delivered work item merged to main.
- Updated roadmap and delivery records.

## Recovery

- Each state machine is crash-safe — re-calling resumes from last persisted state.
- If blocked, record deferrals and reschedule the work item.

## See also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/work/overview.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/integrate.md
