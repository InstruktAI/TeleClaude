---
description: Independently review a drafted task-plan against the task contract before it is authorized.
delivered_by: [task-plan-review]
---

# Review Task — Procedure

## Required reads

@~/.teleclaude/docs/sdlc/procedure/lifecycle/review.md
@~/.teleclaude/docs/sdlc/spec/todo-kind-task.md

## Goal

Decide whether a drafted `task-plan` faithfully carries the task's intent and
is ready for authorization. Review what `sdlc/procedure/lifecycle/task/prepare-task`
owes, independently of the session that drafted it. Do not judge how the run
agent will carry the plan out.

## Preconditions

- The todo is a `task` with a drafted `task-plan`.
- The task-plan has not yet been authorized.
- The reviewer is dispatched independently from the drafting context.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. Read the `input`, the drafted `task-plan`, and any `log` material that bears
   on the task's intent.
2. Review the task-plan against the task contract
   (`sdlc/procedure/lifecycle/task/prepare-task`):
   - The action boundary, result, recipient and timing come from what the
     `input` carries.
   - No limit the `input` does not carry is presented as decided; it is left
     out or named as open for authorization.
   - Fulfilling it touches no repository-tracked file and makes no commit
     (`sdlc/spec/todo-kind-task`); a plan that does is a misclassified todo.
   - The bounded duplicate check was performed.
   - The plan carries its intent line, the operations the run performs, and the
     result handoff the input asks for, expressed so a run agent can carry it
     out with the available command surface.
   - A recurring task's plan holds on every firing, not only the first.
3. Write findings; do not rewrite the task-plan. Every finding cites the
   contract clause it violates and states what the drafter must reconsider.
4. Write the complete `task-plan-review-findings` report for this pass, including
   all review sections and the verdict even when no findings remain, and stamp
   `needs_work` or `approve` for `task_plan_review`. The stamp binds the current
   task-plan digest and the current report digest.

## Outputs

- A complete `task-plan-review-findings` report for every pass.
- A `task_plan_review` verdict bound to the current task-plan and report
  digests.
- No edit to the task-plan or any other artifact.

## Discipline

Judge the task-plan as an instruction contract against its input, not the run
agent's method. Apply the finding-validity, classification and verdict rules in
`sdlc/procedure/lifecycle/review`.

## Recovery

- If the `input` is insufficient to determine the action boundary, record the
  open intent for authorization; do not invent it.
- If the plan touches the repository, report the misclassification instead of
  reviewing it further.
