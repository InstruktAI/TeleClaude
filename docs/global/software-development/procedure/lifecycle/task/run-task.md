---
activation_trigger: 'Use when the lifecycle runner dispatches an authorized task for execution'
description: 'Execute one ephemeral run of an authorized task against its durable task-plan, carry continuity through the log, deliver outputs to the predictable workspace, and terminate. Non-SDLC; no commit.'
delivered_by:
  - task-lane
---

# Run Task — Procedure

## Required reads

@~/.teleclaude/docs/general/principle/continuity.md

## Goal

Execute **one ephemeral run** of an authorized `kind=task` todo against its
durable `task-plan`, carry continuity across runs through the `log`, deliver any
filesystem outputs to the task's predictable workspace, and terminate. The run is
the hands; the todo and its artifacts are the record. This is non-SDLC work: there
is no build, review, finalize, or commit.

## Preconditions

- The todo is `kind=task`, authorized, not held, dispatched by the lifecycle
  runner (or a manual start), with `lifecycle_phase=task_running`.
- A `task-plan` artifact exists. A `log` artifact may not (it is absent on the
  first run).
- The session is booted with the full `telec` CLI surface and available skills.

## Steps

1. **Read the evidence first.** You are a fresh instance with no memory of prior
   runs (`general/principle/continuity`). Read the `log` before anything else — it
   is the record of what previous runs did and encountered. If the `log` shows the
   run for this scheduled instant already completed, stop: the run is done. If the
   `log` is empty or absent, this is the first run and you begin it.

2. **Read the plan.** Read the `task-plan`. It is the human-approved intent and
   carries the specifics this procedure deliberately omits — what to produce,
   whether and to whom to hand off results, whether to include the `log` in any
   report.

3. **Execute, unbounded in method.** Do what the plan describes using whatever you
   need: query data, operate skills, fetch the web, generate content. This
   procedure does not narrow _what_ you do — the plan governs that. Do not reduce
   yourself to a fixed menu of actions.

4. **Hand off as the plan directs.** If the plan says to report results — to a
   person, a channel, or an external recipient — do it with the appropriate
   `telec` primitive. Reporting is plan-driven, never assumed.

5. **Deliver to the workspace.** Anything you create on the filesystem goes under
   `{project_root}/workspace/{slug}/` — the durable, predictable home, reused and
   grown across runs, never archived. Organize within it as the plan and the work
   require (flat, or a dated subfolder per run when runs produce distinct
   snapshots). Do not invent output locations elsewhere.

6. **Write the durable record.** Append a concise, dated entry to the `log`: what
   you did, what you produced, and what you encountered — including failures and
   obstacles ("the source was unreachable; deferred X"). The run is ephemeral; if
   it is not in the `log` or a workspace artifact, it is lost.

7. **Keep the `log` lean.** Short dated paragraphs. When the `log` has grown long
   across many runs, roll older entries up into a summary — your judgment, not a
   rule.

8. **Terminate.** The run is done; the todo stays durable for its next firing.

## Outputs

- An updated `log` artifact (a new dated entry; possibly compacted).
- Any deliverables under `{project_root}/workspace/{slug}/`.
- Any handoff the plan directed.
- The todo intact and durable, ready for its next scheduled run.

## Recovery

- **`task-plan` absent or unreadable.** Record the blocker in the `log` and stop;
  do not improvise the task.
- **A required capability fails** (network, API, auth). Record exactly what failed
  in the `log` and stop cleanly. Do not fabricate a result; the next run, or the
  human reading the `log`, continues from the evidence.
- **Handoff ambiguity.** The plan is authoritative. If the plan is silent on
  reporting, send nothing outward and leave it to the human.

## Discipline

You are a memoryless instance running someone's standing intent. The single
failure mode is acting as if you remember — skipping the `log`, or substituting
your own idea of the task for the plan. Read the `log`, execute the plan, record
what happened, terminate. You are powerful (the full CLI surface) but bounded by
the plan: never widen scope, never write outside the workspace, and never send
anything outward the plan did not sanction.
