---
description:
  Build phase. Execute implementation plan tasks, commit per task, and
  manage deferrals.
id: software-development/procedure/lifecycle/build
scope: domain
type: procedure
---

# Lifecycle: Build — Procedure

## 1) Load Context

Read:

1. `todos/{slug}/requirements.md` - WHAT to build
2. `todos/{slug}/implementation-plan.md` - HOW to build it

If either file is missing, stop and report error.

## 2) Assess Current State

Parse the implementation plan:

- Identify tasks already done `[x]`
- Identify tasks pending `[ ]`
- Focus on Groups 1-4 only (build tasks)

## 3) Execute Task Groups

Work through Groups 1-4 sequentially.

### Parallel Tasks

Tasks marked `**PARALLEL**` can run simultaneously. Execute them together and wait for all to complete.

### Sequential Tasks

Tasks marked `**SEQUENTIAL**` or `**DEPENDS:**` must run one at a time in order.

### Per-Task Workflow

1. Understand the task from `implementation-plan.md`.
2. Make code changes.
3. Commit to trigger hooks (lint + unit tests).
4. If hooks fail: fix issues and re-attempt the commit until hooks pass.
5. Update checkbox `[ ]` -> `[x]` in `implementation-plan.md`.
6. Commit code + checkbox update together.

**Important:** One commit per completed task.

## 4) Deferrals (Out-of-Scope Only)

If work seems out of scope:

1. Decide if it can be solved pragmatically using existing patterns.
2. Only defer when the decision changes architecture/contracts or requires external input.

If deferring, create `todos/{slug}/deferrals.md`:

```markdown
# Deferred Work

## [Item Title]

**Why deferred:** [Why truly out-of-scope or blocked]

**Decision needed:** [What choice or input is required]

**Suggested outcome:** NEW_TODO | NOOP

**Notes:** [Optional]
```

Continue working after writing deferrals.md.

## 5) Pre-Completion Checks

- Confirm all build tasks are checked.
- Ensure no task is marked "deferred" in the plan.

## 6) Report Completion

```
Build complete for {slug}
Tasks completed: {count}
Commits made: {count}
Tests: PASSING
Ready for review.
```

## Error Handling

- If a task fails: log error in implementation-plan.md notes, attempt fix.
- If stuck after 2 attempts: stop and report blocker.
