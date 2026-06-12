---
description: 'The task lane is decoupled from the SDLC prepare machine: two runner-routed agent runs (draft-plan, run) gated by human authorization, recurrence via a schedule reusing the durable task-plan, ephemeral runs over a durable todo, self-bookkeeping via a continuity log, and a predictable durable workspace output home.'
date: '2026-06-12'
adr_status: 'accepted'
number: '40'
---

# Task Lane: Decoupled, Recurring, Self-Bookkeeping — ADR

## Context

`project/adr/0015-kind-as-lifecycle-entry-point` introduced `task` as the
non-SDLC kind: an actionable unit an agent performs directly, created silent,
grooming a `task-plan`. The follow-on task-lane design then modeled task
preparation as a degenerate path **through the SDLC prepare state machine**
(`task_plan_drafting → prepared`, derived by the same machine that owns
PRD/architecture/plan/review), entered through `telec todo prepare`, and modeled
execution as a one-shot gated on a human authorization stamp.

Three problems surfaced. First, the coupling is a leaky abstraction: a non-SDLC
flow borrows SDLC vocabulary (`prepared`), the SDLC entry point
(`telec todo prepare`), and a `kind==task` special-case branch threaded through a
machine whose entire reason to exist is PRD/architecture/plan/review — for
marginal reuse of phase derivation. Second, the model had **no recurrence**,
which is the dominant assistant / business-operations use case ("every morning,
do X and report"). Third, `/analyze-todo-input` wrote the `task-plan` at
classification time, and there was no convention for where a task's filesystem
outputs land — the path agents take when they invent output locations and users
lose the results.

The task primitive is also fully **decoupled from the project it runs in**: todos
are per-project (`{project_root}/.teleclaude/todos.db`), so a business folder runs
its own tasks, logs, and outputs independently of any code project.

## Decision

1. **The task lane is decoupled from the SDLC prepare state machine.** A task
   never enters the prepare machine and is never driven through
   `telec todo prepare`. The lane is two dedicated, runner-routed agent runs with
   a human authorization gate between them:
   - `/next-prepare-task` reads `input`, drafts the `task-plan`, and ends by
     requesting authorization. It writes nothing else.
   - `/next-run-task` executes the authorized `task-plan` with the agent's native
     tooling.
     No PRD, architecture, implementation-plan, review, drift, or worktree applies.

2. **`/analyze-todo-input` only classifies and routes.** It sets the kind on the
   todo it is handed and writes no `task-plan` and no child todos. Plan authoring
   belongs to `/next-prepare-task`.

3. **Authorization is the per-task autostart opt-in.** The lifecycle runner
   dispatches `/next-run-task` only when the task is authorized, not held, has a
   `task-plan`, and its schedule or dependency gate is satisfied. The default
   autostart policy (`task=false`) governs unauthorized tasks; a human
   authorization stamp flips that one task to runnable. `hold` is the override
   brake.

4. **Recurrence via a `schedule`.** A task carries an optional `schedule` — a
   one-shot instant or a recurring rule — that generalizes the prior one-shot
   `datetime`. `schedule` and `after` dependencies are mutually exclusive. The
   durable `task-plan` is reused across firings; recurrence never re-drafts the
   plan.

5. **The run is ephemeral; the todo is durable.** Each firing is a fresh session
   that reads, executes, records, and terminates. Nothing stays alive between
   firings; a recurring task is a durable todo the runner fires, not a long-lived
   process.

6. **Self-bookkeeping via continuity.** A `log` artifact on the todo is the
   agent's work diary and run-integrity record — what it did, what it encountered
   (including failures), and which scheduled run completed. On wake the agent
   reads the `log` first and continues from it
   (`general/principle/continuity` — read the evidence, not memory). Restart
   idempotency lives in the `log` (keyed by the scheduled run instant), not in the
   filesystem layout. The agent self-curates the log, compressing it when it
   grows. No generic cross-context memory-injection engine is built; the affordance
   plus the instruction is the mechanism.

7. **Outputs land in a predictable, durable workspace.** Filesystem deliverables
   go under `{project_root}/workspace/<slug>/`, reusing the existing non-code
   artifact workspace convention. Unlike an SDLC slug — whose workspace is
   archived and torn down at delivery — a task has no delivery event, so its
   workspace is **never archived or cleaned**; it persists for the life of the
   todo as durable evidence that tasks read and operate on over time. Internal
   organization (flat, or per-run dated subfolders) is the plan's choice, not a
   mandated structure; the predictable slug root is the only guaranteed location.

## Consequences

- The task-lane pending design across the workflow specs is revised to this
  model; the prepare-state-machine task branch (task entering prepare, deriving
  `prepared`) is removed. `task_plan_drafting` and `task_running` are task-lane
  phases, not prepare-machine phases.
- New deliverables under the `task-lane` slug: the `/next-prepare-task` and
  `/next-run-task` procedures, the `log` artifact, and recurrence (the
  `schedule` generalizing the one-shot `datetime`).
- The result handoff (send a message / email) is invoked by the `task-plan`
  through the existing `telec` CLI surface; `/next-run-task` does not own a
  handoff primitive. Extending outbound messaging to external recipients is a
  separate capability.
- Holder-as-task-decomposition is not part of this model; a holder remains the
  generic split primitive for SDLC todos.
- The output convention is enforced by prominent instruction in
  `/next-run-task`; a hard filesystem sandbox is deferred (`worker-sandbox-profiles`).

## Alternatives Considered

- **Route tasks through the prepare state machine** (the prior pending design) —
  rejected: it entangles a non-SDLC flow with SDLC machinery and vocabulary for
  marginal reuse of phase derivation, when the lifecycle runner already owns the
  task gates and the routing is a small guard table.
- **A generic cross-context memory-injection engine** for run continuity —
  rejected: an agent self-bookkeeping a `log` under the continuity principle is
  simpler and more general than code that must anticipate every context.
- **Mandatory per-run dated output folders** — rejected: they fight the common
  case of tasks collaborating on shared, growing artifacts and force folder
  discovery on dependent tasks. A predictable slug root plus a log-based
  integrity check serves both one-shot and recurring runs without them.
