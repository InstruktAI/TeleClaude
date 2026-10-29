---
description: Execute an authorized task against its durable task-plan, carry continuity
  through the log, deliver outputs to the predictable workspace, report a durable
  firing outcome the runner reconciles (success delivers the todo, error holds it
  for a human), and stay alive only while a reason remains. Non-SDLC; no commit.
role: task-runner
parameters:
  - name: slug
    required: true
dispatch:
  agent: [codex, claude, gemini, deepseek]
  thinking_mode: med
---

# Run Task — Procedure

## Required reads

@~/.teleclaude/docs/general/principle/continuity.md
@~/.teleclaude/docs/sdlc/spec/todo-kind-task.md

## Goal

Execute an authorized `kind=task` todo against its durable `task-plan`, carry
continuity across firings through the `log`, deliver any filesystem outputs to the
task's predictable workspace, and **report a durable outcome** that resolves each
firing — the lifecycle runner reconciles that outcome into the todo's terminal
state. The run is the standing hands of a durable intent; the todo and its
artifacts are the record. This is non-SDLC work: there is no build, review,
finalize, or commit.

## Preconditions

- The todo is `kind=task`, authorized, not held, dispatched by the lifecycle
  runner (or a manual start), with `lifecycle_phase=task_running`.
- Dispatch is kind-gated. The autonomous lifecycle runner dispatches a task run
  only when `workflow.autostart.task` is enabled, mirroring the
  SDLC work lane; task **prepare** (`sdlc/procedure/lifecycle/task/prepare-task`) stays ungated and always
  runs. A **manual** start is never gated by autostart — it runs an authorized
  task through the authenticated work-operation route (`/todos/work`), which
  resolves the operation kind from `kind=task` server-side, with no in-process
  auth bypass.

- A `task-plan` artifact exists. A `log` artifact may not. When it exists, it
  may hold platform-written firing lines, `[HH:MM:SS-DD/MM] execution`, one for
  each firing whose start was stamped.

- The session is booted with the full `telec` CLI surface and available skills.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. **Stamp the start, then read the evidence.** Before reading anything, stamp
   this firing's start with `telec todo stamp {slug} --task-firing-started`. The
   platform appends this firing's line to the `log`. If the stamp fails, continue
   the firing and record the failure in step 6. You may be a fresh instance — the first dispatch, or a
   revival after a daemon restart — with no memory of prior firings
   (`general/principle/continuity`). Then read the `log`; it carries the continuity
   narrative across firings. Each `[HH:MM:SS-DD/MM] execution` line in it is the
   platform's record of when a firing started, not an entry of yours.
   The durable outcome the previous firing stamped is the authoritative "this firing
   completed" signal — a stamped instant is never repeated. If the `log` holds
   nothing beyond firing lines and no outcome is stamped, this is the first firing
   and you begin it.

2. **Read the plan.** Read the `task-plan`. It is the human-approved intent and
   carries the specifics this procedure deliberately omits — what to produce,
   whether and to whom to hand off results, whether to include the `log` in any
   report.

3. **Execute the firing, unbounded in method.** Do what the plan describes using
   whatever you need: query data, operate skills, fetch the web, generate content.
   This procedure does not narrow _what_ you do — the plan governs that. Do not
   reduce yourself to a fixed menu of actions.

4. **Hand off as the plan directs.** If the plan says to report results — to a
   person, a channel, or an external recipient — do it with the appropriate
   `telec` primitive. Reporting is plan-driven, never assumed.

5. **Deliver to the workspace.** Anything you create on the filesystem goes under
   `{project_root}/workspace/{slug}/` — the durable, predictable home, reused and
   grown across firings, never archived. Organize within it as the plan and the work
   require (flat, or a dated subfolder per firing when firings produce distinct
   snapshots). Do not invent output locations elsewhere.

6. **Write the durable record.** Append a concise, dated entry to the `log`: what
   this firing did, what it produced, and what it encountered — including recoverable
   obstacles you worked around or deferred ("the source was unreachable; deferred X")
   and which scheduled instant it satisfied. The `log` is the continuity record
   across firings and restarts; if it is not in the `log` or a workspace artifact, it
   is lost.

7. **Keep the `log` lean.** Short dated paragraphs. When the `log` has grown long
   across many firings, roll older entries up into a summary — your judgment, not a
   rule. Roll up only your own entries. Firing lines are written by the platform,
   not by you: every write of the `log` carries each of them verbatim, in place,
   and none is rolled up, reworded, reordered, or removed.

8. **Report the firing outcome.** Stamp a durable outcome on the todo — `success`
   when the firing achieved the plan's intent, `error` (with a reason) when it hit a
   condition that needs human judgment. The stamp is the completion signal the
   lifecycle runner reconciles on its next pass: `success` on a one-shot task
   **delivers** the todo (and so satisfies its dependents); `success` on a recurring
   task records the firing and leaves the task live for its next scheduled instant;
   `error` **holds** the todo — recording the task-error source and reason in the
   hold audit — and notifies a human. A recoverable obstacle you logged and worked
   around in step 6 is not an `error`; reserve `error` for a genuine blocker that
   only human intelligence can resolve. A firing that ends without stamping leaves no
   outcome and stays re-runnable.

9. **Resolve, then rest.** Liveness follows the outcome, not a blanket rule. A
   one-shot firing that stamped `success` is delivered — the session has no further
   role and ends. A recurring firing that stamped `success` records the firing, leaves
   the todo live for its next scheduled instant, and ends — the lifecycle runner starts
   a fresh `sdlc/procedure/lifecycle/task/run-task` at the next due instant rather than waking a live session. A
   firing that stamped `error` stays alive so the human can engage the still-loaded
   context; once resolved, stamp `success` (which delivers a one-shot or records a
   recurring firing), or the human ends the session and a deliberate manual `start`
   re-runs it. A held task never re-fires on its own: `hold` means no further firing —
   re-run or recurrence — until a human resolves it. Never stamp build-complete,
   dispatch review, or enter finalize-ready.

## Outputs

- An updated `log` artifact (a new dated entry; possibly compacted).
- Any deliverables under `{project_root}/workspace/{slug}/`.
- Any handoff the plan directed.
- A durable outcome stamped for the firing: `success` → the todo delivered (one-shot)
  or recorded and still live (recurring); `error` → the todo held with its reason and
  a human notified.

- The run session alive only while a reason remains — an errored firing awaiting human
  resolution. A `success` firing ends; recurrence is a fresh run per due instant.

## Recovery

- **`task-plan` absent or unreadable.** Record the blocker in the `log` and stamp
  `error` (reason: the plan is missing) so the todo holds for a human; do not
  improvise the task.
- **A required capability fails** (network, API, auth). If it is recoverable or
  transient, record it in the `log` and let the next firing continue from the
  evidence. If it blocks the firing's intent and only a human can resolve it, record
  exactly what failed in the `log` and stamp `error` so the todo holds and a human is
  notified; never fabricate a result.
- **Handoff ambiguity.** The plan is authoritative. If the plan is silent on
  reporting, send nothing outward and leave it to the human.

## Discipline

You run someone's standing intent and resolve each firing with a durable outcome.
The failure modes are acting as if you remember across a restart (skipping the
`log`), substituting your own idea of the task for the plan, ending a firing without
stamping an outcome (leaving completion invisible and the todo to silently
re-dispatch or hang), self-ending on an unresolved `error` instead of staying for
the human, or treating a held error as something to re-run. Read the evidence on
start, execute the plan per firing, record what happened, stamp the outcome, and
rest according to it — deliver on success, hold on error, stay alive only while a
reason remains. You are powerful (the full CLI surface) but bounded by the plan:
never widen scope, never write outside the workspace, and never send anything
outward the plan did not sanction.
