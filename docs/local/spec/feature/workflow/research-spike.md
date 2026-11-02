---
description: 'A `kind=spike` todo verifies third-party behavior a waiting decision rests on: it is prepared and run in the task lane without human authorization, its run may commit documentation, and the work waiting on it — including a preparation already under way — stays waiting until it is delivered.'
visibility: 'public'
delivered_by: [spike-todo-kind]
---

# Research Spike — Spec

## Required reads

- docs/global/sdlc/principle/domain-driven-design.md
- docs/global/sdlc/spec/domain-spec.md
- @docs/local/spec/domain/workflow.md

## What it is

A spike is the todo an agent files when a decision rests on third-party
behavior that no third-party documentation records as verified. The decision
waits while the spike verifies the behavior and records it; once the spike is
delivered, the waiting work resumes on a verified fact instead of a guess. The
kind's definition and its result destinations are
`sdlc/spec/todo-kind-spike`; when an agent files one is
`sdlc/policy/research-spikes`. This spec states how the workflow carries a
spike.

## Canonical fields

### The kind

- `spike` is a canonical kind, accepted wherever a kind is accepted and listed
  wherever the kinds are listed (`local/projects/teleclaude/spec/feature/workflow/todo-creation`).
- A spike is created without dispatch, as a task is, and enters
  `task_plan_drafting`. It accepts neither a `schedule` nor a supplied plan.

### Preparation

- The lifecycle runner dispatches `sdlc/procedure/lifecycle/task/prepare-task`
  for a spike without a `task-plan`, as it does for a task; preparation is not
  gated by autostart.
- A spike reaches `prepared` when its `task-plan` exists. A prepared spike is
  runnable: it needs no `task_approved` stamp, and the stamp is refused for it as
  for every non-task todo (`local/projects/teleclaude/spec/feature/workflow/state-stamping`).

### Run

- The lifecycle runner dispatches `sdlc/procedure/lifecycle/task/run-spike` for
  a prepared spike that is not held, whose dependency gate is satisfied and whose
  kind is enabled by `workflow.autostart.spike`
  (`local/projects/teleclaude/spec/teleclaude-config`). A manual start runs it
  regardless of autostart, through the same work-operation route a task's manual
  start takes.
- The run session carries the `spike-runner` role
  (`local/projects/teleclaude/spec/feature/identity/agent-roles`), whose reach
  admits committing to the repository, which the task runner's does not.
- A spike's firing-start stamp and its outcome stamp are accepted and reconciled
  as a one-shot task's: `success` delivers the spike, `error` holds it with the
  task-error source and its reason.

### Waiting on a spike

- A spike holds the todos that depend on it — at both dispatch gates, and in a
  preparation already under way — until it is delivered
  (`local/projects/teleclaude/spec/feature/workflow/dependency-graph`).

## Known caveats

- A spike is not repository work and never appears on the GitHub workflow
  store (`local/projects/teleclaude/spec/feature/workflow/github-work-record`).
- Nothing in the workflow inspects which paths a spike's commits touch; the
  run procedure confines them to the two documentation homes and independent
  commit review checks it.
