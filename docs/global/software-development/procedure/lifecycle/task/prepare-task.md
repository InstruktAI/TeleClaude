---
activation_trigger: Use when the lifecycle runner dispatches task-plan drafting for
  a kind=task todo
description: "Convert a task todo's raw input into a durable, repeatable task-plan
  and request human authorization. Non-SDLC: no prepare state machine, no PRD/architecture/plan/review."
---

# Prepare Task — Procedure

## Required reads

@~/.teleclaude/docs/general/principle/continuity.md
@~/.teleclaude/docs/software-development/spec/todo-kind-task.md

## Goal

Turn a `kind=task` todo's raw `input` into a `task-plan` — the durable,
human-approved instruction set the task executes on every run — and then request
human authorization. This procedure does not execute the task, does not create
other todos, and never enters the SDLC prepare state machine. A task is non-SDLC:
no PRD, architecture, implementation-plan, or reviewer verdict applies.

## Preconditions

- The todo is `kind=task` at `lifecycle_phase=task_plan_drafting`, with an `input`
  artifact and no `task-plan` yet (or a refinement pass on an existing one).
- The session runs in the project on `main`, with no worktree.
- The `input` artifact is immutable; it is interpreted, never rewritten.

## Steps

1. **Read the `input`.** `telec todo artifacts read {slug} input`. Read it as
   intent to interpret, not a spec to obey literally.

2. **Reject if the intent touches the repo.** Judge the input against the
   boundary in `software-development/spec/todo-kind-task`. If fulfilling it
   requires modifying a repo-tracked file or a commit, do not draft a
   `task-plan`: report to the human that the todo is misclassified — name the
   repo-touching work implied — and recommend `telec todo update {slug}
--kind <change|feature|bug>`. Stop here.

3. **Check for an obvious duplicate.** Scan `telec todo list` for a plausible
   match — the shallow, bounded check `software-development/spec/todo-kind-task`
   requires. If one turns up, surface it to the human before drafting rather
   than proceeding; do not attempt deeper reconciliation.

4. **Interpret it into a `task-plan`.** Author the plan as the durable, repeatable
   contract reused on every firing:
   - an intent line ("I read your request as …");
   - the operations the run performs;
   - the result handoff the human asked for, if any — what to produce and where it
     goes (a person, a channel, an external recipient) — expressed so the run
     agent can carry it out with the `telec` CLI surface;
   - whether the run reports its `log`.
     The plan is the _what_; the run agent decides the _how_ with its own tooling.

5. **Write the `task-plan`.** `telec todo artifacts write {slug} task-plan "…"`.

6. **Request human authorization.** Present the `task-plan` to the human and ask
   them to authorize it — and, if they want it scheduled, to set a `schedule`
   (a one-shot instant or a recurring rule). Authorization is the human's call;
   the session never authorizes on their behalf, and writing the `task-plan` never
   implies approval.

7. **Hand off to the runner.** Once the human authorizes, the task becomes a
   runner candidate: the lifecycle runner dispatches `/next-run-task` when the
   task is not held and its schedule or dependency gate is satisfied.

## Outputs

- A `task-plan` artifact (durable, repeatable instruction set).
- An authorization request surfaced to the human; the `input` unchanged.

## Recovery

- **Input too sparse to interpret.** Surface the gap and ask one direct question;
  do not invent scope into the plan.
- **Intent requires repo modification.** Refuse per Step 2; do not draft a
  `task-plan`.
- **Plausible duplicate found.** Refuse per Step 3; surface it to the human
  rather than guessing whether it is truly redundant.
- **Refinement.** When the human revises the intent, rewrite the `task-plan` and
  request authorization again. Any prior authorization is invalidated by a
  substantive plan change.

## Discipline

You draft and request approval; you never execute the task and never authorize it
yourself. The `task-plan` is the durable contract a long-lived run agent will
execute repeatedly across firings (and re-read after any restart) — write it so it
stands on its own across many future firings, not as a one-time script. Sliding from
"classify this as task" into drafting a plan for repo-touching or duplicate work
without checking Steps 2 and 3 first, or from "draft the plan" into "do the work,"
are the failure modes here.
