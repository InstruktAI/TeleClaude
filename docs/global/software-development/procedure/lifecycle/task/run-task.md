---
activation_trigger: Use when the lifecycle runner dispatches an authorized task for
  execution
description: Execute an authorized task against its durable task-plan, carry continuity
  through the log, deliver outputs to the predictable workspace, and stay alive for
  human follow-up and the task's next scheduled firing. Non-SDLC; no commit.
---

# Run Task — Procedure

## Required reads

@~/.teleclaude/docs/general/principle/continuity.md

## Goal

Execute an authorized `kind=task` todo against its durable `task-plan`, carry
continuity across firings through the `log`, deliver any filesystem outputs to the
task's predictable workspace, and **stay alive** — for the human to inspect the
output and for the task's next scheduled firing. The run is the standing hands of a
durable intent; the todo and its artifacts are the record. This is non-SDLC work:
there is no build, review, finalize, or commit.

## Preconditions

- The todo is `kind=task`, authorized, not held, dispatched by the lifecycle
  runner (or a manual start), with `lifecycle_phase=task_running`.
- A `task-plan` artifact exists. A `log` artifact may not (it is absent on the
  first firing).
- The session is booted with the full `telec` CLI surface and available skills.

## Steps

1. **Read the evidence first.** You may be a fresh instance — the first dispatch, or
   a revival after a daemon restart — with no memory of prior firings
   (`general/principle/continuity`). Read the `log` before anything else. If the
   `log` shows the run for the current scheduled instant already completed, do not
   repeat it. If the `log` is empty or absent, this is the first firing and you begin
   it.

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
   this firing did, what it produced, and what it encountered — including failures
   and obstacles ("the source was unreachable; deferred X") and which scheduled
   instant it satisfied. The `log` is the continuity and restart-idempotency record
   across firings and restarts; if it is not in the `log` or a workspace artifact, it
   is lost.

7. **Keep the `log` lean.** Short dated paragraphs. When the `log` has grown long
   across many firings, roll older entries up into a summary — your judgment, not a
   rule.

8. **Stay alive.** Do not self-end. After a firing completes, remain available for
   the human to inspect the output and for the task's next firing — the lifecycle
   runner wakes this live session on each due scheduled instant; a one-shot task
   simply waits after its single firing. Never stamp build-complete, dispatch
   review, or enter finalize-ready.

## Outputs

- An updated `log` artifact (a new dated entry; possibly compacted).
- Any deliverables under `{project_root}/workspace/{slug}/`.
- Any handoff the plan directed.
- The todo intact and durable, and the run session alive for inspection and the
  next firing.

## Recovery

- **`task-plan` absent or unreadable.** Record the blocker in the `log` and stay
  alive; do not improvise the task.
- **A required capability fails** (network, API, auth). Record exactly what failed
  in the `log` and stay alive; do not fabricate a result. The next firing, or the
  human reading the `log`, continues from the evidence.
- **Handoff ambiguity.** The plan is authoritative. If the plan is silent on
  reporting, send nothing outward and leave it to the human.

## Discipline

You run someone's standing intent and stay alive to keep running it. The failure
modes are acting as if you remember across a restart (skipping the `log`),
substituting your own idea of the task for the plan, or self-ending — the run must
stay alive for the human to inspect and for the next firing. Read the `log` on
start, execute the plan per firing, record what happened, stay alive. You are
powerful (the full CLI surface) but bounded by the plan: never widen scope, never
write outside the workspace, and never send anything outward the plan did not
sanction.
