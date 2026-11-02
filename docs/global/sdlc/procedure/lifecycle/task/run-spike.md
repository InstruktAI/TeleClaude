---
description: Run a spike once against its task-plan — verify the third-party behavior
  it asks about with the research procedure, record the verified facts in third-party
  documentation and the trail in the exploration home, have those commits independently
  reviewed, and report the outcome that releases the work waiting on it.
delivered_by: [spike-todo-kind]
---

# Run Spike — Procedure

## Required reads

@~/.teleclaude/docs/general/principle/continuity.md
@~/.teleclaude/docs/sdlc/spec/todo-kind-spike.md

## Goal

Answer the question a `kind=spike` todo was filed for with verified facts,
record them where every later agent reads them, and report a durable outcome:
`success` delivers the spike and releases the work waiting on it. The run
follows the research procedure its `task-plan` names. Its only repository
changes are its project's third-party documentation and exploration home.

## Preconditions

- The todo is `kind=spike`, has a `task-plan`, is not held, and was
  dispatched by the lifecycle runner or a manual start, with
  `lifecycle_phase=task_running`.
- The session runs in the project on `main`, with no worktree.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

1. **Stamp the start, then read the evidence.** Stamp this firing's start with
   `telec todo stamp {slug} --task-firing-started`, then read the `log`. You may
   be a revival with no memory of an earlier attempt
   (`general/principle/continuity`); resources a previous attempt recorded as
   created and not yet removed are yours to remove before anything else.

2. **Read the plan and load the research procedure it names.** Read the
   `task-plan`: the question, the upstream party, and the decision and todo
   waiting on the answer. Load the research procedure the plan names with
   `telec docs get <id>` and follow it for that question.

3. **Test only on what you create.** A live test runs against throwaway
   resources the run creates itself — a scratch repository, a test project, a
   sandbox account resource — never against live data or a resource it did not
   create. Record each resource in the `log` as you create it, remove it when
   its test is done, and record the removal.

4. **Record the findings where they belong.** Place each verified fact by the
   placement rule of `general/spec/third-party-docs`: a project-specific
   finding in the project's third-party documentation, a reusable one in the
   global third-party documentation. Write each fact with when and how it was
   verified, and keep hypotheses apart from it. A global finding whose source
   lives in another project travels by the cross-project documentation route
   (`general/policy/documentation-discipline`): write the complete content to
   temporary files, relay their paths to a session you start in the owning
   project, and wait until it reports the content applied and committed.
   Append the exploration trail to the subject's file in the exploration home
   (`general/spec/exploration-home`).

5. **Commit the two homes, and only them.** Before committing, confirm the
   declared set holds only paths under `docs/third-party/` and `docs/explore/`;
   a change anywhere else is not yours to make — record what the waiting
   decision needs from it in the `log` instead. Commit with
   `telec repo commit --todo {slug}` under `general/policy/commits`.

6. **Have the documentation reviewed.** Third-party documentation states facts
   other agents rely on, so its commits owe independent review
   (`general/policy/documentation-discipline`): dispatch
   `sdlc/procedure/lifecycle/work/review-commits` on the commit SHAs and wait
   for the verdict. A `REQUEST CHANGES` verdict stays with you to remediate
   and re-review under `general/policy/commits`. You never stamp a verdict on
   your own commits.

7. **Write the run record.** Append a dated entry to the `log`: what was
   tested and how, the evidence, the resources created and removed, the
   documentation written with its commits and review, and — last — the answer to
   the question, with what remains unverified named as such.

8. **Report the outcome.** Stamp `success` once the documentation is committed
   and approved and every throwaway resource is removed; a gap you could not
   verify is recorded, not an error. Stamp `error` with a reason only for a
   blocker that needs a human — a resource you cannot remove, a test that needs
   access only a human can grant. The stamps and their effects are those of the
   task lane (`sdlc/procedure/lifecycle/task/run-task`, step 8).

9. **Resolve, then rest.** After `success` the spike is delivered and the
   session ends. After `error` stay alive for the human with the context loaded.

## Outputs

- Verified facts in third-party documentation, each with when and how it was
  verified, committed and independently reviewed.
- The exploration trail in the exploration home.
- A `log` entry ending with the answer to the question.
- A `success` outcome that delivers the spike, or an `error` hold with its
  reason.

## Recovery

- **The `task-plan` names no research procedure, or no question.** Stamp `error`
  naming what the plan lacks; do not improvise the question.
- **A resource cannot be removed.** Record it in the `log` with what is needed
  to remove it and stamp `error`, so a human sees what remains.
- **The cross-project session cannot apply the content.** Keep the temporary
  files, record the blocker in the `log`, and stamp `error`.

## Discipline

You verify before you write. A fact you read but did not see behave goes into
the documentation as read, with its source; a fact you saw behave goes in with
how you saw it. The temptation is to fix what the answer shows is wrong in the
code or the waiting design — that is the waiting job's to do once it resumes,
never yours.
