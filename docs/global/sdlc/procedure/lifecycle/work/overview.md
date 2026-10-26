---
description: 'Work stage overview. Build, review, fix, finalize cycle driven by the work state machine.'
activation_trigger: 'Use when asked to become the work orchestrator for a todo or drive telec todo work through build, review, fix, and finalize handoff.'
visibility: 'public'
role: work-orchestrator
parameters:
  - name: slug
    required: true
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: slow
---

# Work Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/general/procedure/orchestration.md
- @~/.teleclaude/docs/sdlc/procedure/lifecycle/overview.md
- @~/.teleclaude/docs/sdlc/policy/preparation-artifact-quality.md

## Goal

Drive the work state machine (`telec todo work`) through the build-review-fix-finalize
cycle until the todo is delivered or blocked. The orchestrator dispatches workers as
instructed by the state machine and supervises their progress.

### The doc layer is frozen — prepare authors, work executes

Prepare is the only lifecycle phase that authors doc snippets, on `main`,
serialized by the documentation lease. From PREPARED onward the doc layer is frozen for the

slug: no work-phase session — builder, reviewer, fixer, or finalizer — changes
the doc layer or takes its state as work. Writing under `docs/**`, folding
pending markers, and confirming or verifying whether they are folded are the same
violation whatever verb the task uses. Reading doc snippets as input is untouched
and required: the work phase binds in-scope feature-spec scenarios and implements
against published contracts. The slug's doc reflection already exists as pending
markers authored at prepare; the integrator folds them at delivery.
A doc need discovered mid-build (a missing scenario, a wrong planned contract)
is a plan defect: surface it and route through the kickback path (Step 9) so
prepare re-derives on `main` — never edit `docs/**` in the worktree.

### Work ends in delivery or kickback

Prepare settles intent, scope, and every decision the human owns
(`general/policy/human-contract`) before the todo reaches PREPARED; work
executes that settlement and holds no human lane. Every work outcome is
delivery or a kickback to Prepare (Step 9). A finding, blocker, or question
whose answer would change intent or scope is a plan defect and returns the
todo to Prepare, which decides whether its re-derivation involves the human.
Technical recovery, builder–reviewer disagreement, and tooling obstruction are
resolved by the agents. A worker's or reviewer's statement that a human
decision is needed is a claim the orchestrator assesses under this rule, never
a routing instruction.

<!-- planned:github-person-decisions -->

### A person's review on the item's pull request

For an item of a project on the GitHub workflow store, a configured person who
owns the repository, is a member of the organization that owns it, or
collaborates on it, and who holds write access to the repository, may review
the item's pull request. Their request for
changes, given on the commit the build currently stands on and before
delivery, is a `changes_requested` build-review verdict: the platform records
their review as that round's review report, and the build returns to fix. The
fixer validates each of its points under
`sdlc/procedure/lifecycle/fix-review-findings` like any finding, and a point
whose answer would change intent or scope is a kickback ground (Step 9). Their
approval stamps nothing, because work holds no human lane; it reaches the
session working the item as their message. A review on an earlier commit, or
by anyone else, changes nothing and is answered on the pull request.
<!-- /planned:github-person-decisions -->

## Preconditions

- Target slug has completed preparation (state: PREPARED).
- `telec todo artifacts read {slug} implementation-plan` exists and is approved.
- Feature work additionally carries an approved `prd`; its optional
  `architecture` artifact is approved or explicitly skipped.
- Bug work additionally carries a settled `diagnosis`.
- Worktree is available or can be created for the slug.

## Steps

<!-- @include: docs/snippets/step-role-read.md -->

### 1. Enter the state machine

Call `telec todo work {slug}` for the current slug. The call returns an operation
receipt; when the outcome wakes this session, read the instruction block with
`telec operations get <operation_id>` (`general/procedure/orchestration`) and
execute it. The work orchestrator is scoped to that slug only; it does not
continue into unrelated work after the slug reaches a terminal handoff.

If the slug resolves to a holder, execute only the direct child commands the
machine returns. Before dispatching a worker for a child, read that child's
`implementation-plan` (with `prd`, optional `architecture`, and in-scope
feature-spec scenarios as context). Never read holder artifacts as executable
work input.

When the state machine instructs a dispatch, select `--mode`:

- **Builders and fixers**: `med` (well specced out plan should not require slow mode).
- **Reviewers**: `slow`. A lifecycle build review is not a doc-snippet-only review.
- **Finalizers**: `fast`.

### 2. Build

The state machine dispatches a builder worker via `build`. The builder:

- Executes the implementation plan task-by-task
- Commits per task
- Reports BUILD COMPLETE when done

When the builder is ready for review, it stamps
`telec todo stamp [slug] --build-complete`. The orchestrator then calls
`telec todo work [slug]` again. The work state machine reads the stored
`lifecycle_phase` and dispatches the next step. Git commits and build gates are
evidence only; they do not advance the phase on their own.

### 3. Review

After build completes, the state machine dispatches a reviewer via `review-build`
and records the exact HEAD under review. While that reviewer is still alive, the state
machine must reuse it instead of dispatching a second reviewer. On the next
`telec todo work` call the machine first checks whether a live reviewer already owns
the slug. If so, it keeps waiting on that reviewer; a successful merge of
`origin/main` into the worktree gives it no follow-up.

The reviewer runs parallel review lanes (scope, code, principles, security, tests,
errors, types, comments, docs) and writes `review-findings`. When the reviewer idles,
the next `telec todo work` call reconciles the verdict from `review-findings` and emits
the next action: advance the phase on APPROVE, or relay findings to the existing builder
on REQUEST CHANGES.

### 4. Fix (if needed)

On REQUEST CHANGES, the state machine finds the live builder session and sends the
findings via `telec sessions send`. The builder loads the fix procedure on demand
(`sdlc/procedure/lifecycle/fix-review-findings`) and addresses the
findings without losing context.

Recoverable process failures are the worker's own to recover. The work state
machine merges `origin/main` into the worktree before dispatch/review; if that
machine-owned merge returns `MERGE_MAIN_FAILED`, the builder's own procedure
carries the recovery mechanics. Failed lint/test gates, dirty worktrees,
missing stamps, and stale branch publication are the same: the child mutates
the worktree. When the child cannot proceed from its brief, the orchestrator
classifies and routes recovery under `general/procedure/orchestration` and
`general/policy/human-contract`; a technical or architectural blocker does
not itself require the human.

Review/fix loops report their round count against the configured threshold. No
fresh fixer session is dispatched — the original builder handles the fix cycle,
and the next review round reuses the same reviewer session when it is still
alive. Crossing the threshold refuses nothing and summons no one; this
orchestrator owns continuation under the shared convergence contract
(`sdlc/procedure/lifecycle/review`).

### 5. Finalize

On APPROVE, the state machine dispatches a finalizer via `finalize`. The
finalizer integrates latest main into the worktree, resolves conflicts, pushes
the branch, and reports FINALIZE_READY. The state machine then drives the finalize
handoff, emitting end commands for the slug's workers and then for the work
orchestrator itself. Successful handoff is the terminal state for this
orchestrator session.

**Integration is not the work orchestrator's scope — authority ends at finalize.**
After a finalizer reports FINALIZE_READY, re-enter `telec todo work [slug]` to trigger
the handoff; the state machine records durable finalize state and emits the terminal
cleanup script.
Never dispatch `integrate`, call `telec todo integrate`, or work around permission
denials to reach integration. Integration is a separate singleton role with its own
lease, worktree, and dispatch path. If the machine does not advance past finalize
because a child needs recoverable worktree or branch-publication help, guide that
child through recovery first. If the blocker is not recoverable inside work scope,
record the blocker and stop — do not escalate scope.

### 6. Deferrals

If `deferrals` exists, the state machine dispatches deferral resolution via
`defer` before or after finalize. Deferral processing decides each entry and
creates or files only what `sdlc/policy/todo-creation-discipline` admits.

### 7. Bug fix

For bug-type work items, the state machine dispatches `build` — the same
builder as a change/feature. The bug's mandate is the reviewed
`implementation-plan` plus the `diagnosis` (code-grounded root cause, fix
approach, and verification approach produced in the prepare phase); the builder
executes the plan and drives the reproduction test RED→GREEN. Diagnosis happens
upstream in the prepare phase, not here.

Its post-completion bookkeeping matches the normal build path: the build worker
stamps `telec todo stamp [slug] --build-complete`, then the orchestrator re-enters
`telec todo work [slug]`.

### 8. A stamp the worker owed and did not make

The engine reads durable state, never artifacts. A verdict written into
`review-findings` is the reviewer's report; `build_review.verdict` in state is the
record the machine acts on. The same holds for a finished build: the work is not
complete to the state machine until `build_complete` is stamped, whatever the
commits show.

So a worker that finishes its work, writes its artifact, and idles without
stamping leaves the lifecycle stalled until someone records what the artifact
already says. The orchestrator does not wait for the worker to return and do it.
Where the work is done, the orchestrator stamps it and proceeds — this authority
is the orchestrator's own, not the worker's alone.

The condition is the whole of it: the orchestrator stamps because it has
established the work is finished, never because waiting has become tedious. An
approved review carrying zero unresolved findings, or a build whose findings are
all fixed and whose checks have passed, is established. A review whose findings
the orchestrator has not read is not, and no amount of elapsed time makes it so.

Read the state before using this. A verdict already stamped needs nothing, and
re-stamping over a worker that was mid-write is how two records disagree.

### 9. Kickback to prepare (orchestrator-owned)

A build can stall on a plan defect that no fix resolves — the implementation plan
cannot be executed as written and needs re-derivation, not a fix round. The builder
surfaces the reason to its orchestrator and preserves its work.

The orchestrator owns the technical kickback decision under
`general/policy/human-contract`; the worker does not invoke it. Read the
builder's evidence, establish why re-preparation can resolve the plan defect
within authorized intent, and record that direction before acting. A build
that differs from the plan only in file placement, helper names, or
decomposition shows no plan defect and is no basis for kickback
(`sdlc/policy/preparation-artifact-quality`); a review that asks for kickback on
that ground alone is answered through the review loop, its finding and verdict
intact (`sdlc/procedure/lifecycle/review`). A needed
change to product intent or scope is itself a kickback ground: Prepare
re-derives and alone decides whether that involves the human. A change to the
governing process contract follows `sdlc/policy/process-change-authority`. An
unresolved technical question returns to evidence and its agent owner, never to a human merely because a
fix round failed. Kickback supplies no approval of the revised plan; normal
independent preparation review remains required.

On that grounded direction the orchestrator runs
`telec todo stamp [slug] --kickback --reason "<why the plan cannot be built>"`. The
stamp appends the reason to `input` (creating `input` when the todo has none) and
invalidates the implementation-plan, so the phase derives back to `plan_drafting`.

The stamp ends this orchestrator's part. Once the reason is durable, the
platform releases the todo's lifecycle claim and ends the slug's work-lane
sessions — every session this orchestrator started, then the orchestrator
itself. The orchestrator neither re-enters `telec todo work [slug]` nor ends
anything itself. The worktree with its build commits, the local and remote
branch, and the workspace directory remain. The lifecycle runner dispatches a
fresh prepare orchestrator, whose planner reads the kickback block in `input`
as authoritative re-derivation context. At PREPARED that orchestrator ends like
any other, and the lifecycle runner dispatches a fresh work orchestrator under
the kind's work-lane autostart policy. Its work machine finds the plan changed
under the existing build and hands the builder machine-derived reconcile
instructions — the diff between the plan version the build started against and
the re-approved plan — so the builder reverts what the amendment invalidates,
keeps what still serves, and continues.

## Outputs

- Code changes implementing the plan, committed and reviewed.
- Review findings addressed.
- Branch finalized and ready for integration.
- Deferrals decided, with new todos or bug filings only where admitted.

## Recovery

- If a worker stalls or cannot proceed from its brief, inspect and route its
  recovery under `general/procedure/orchestration`.
- Failed recovery iterations require a grounded reassessment and an accountable
  owner, not automatic human escalation; apply `general/policy/human-contract`.
- When review continuation stops, record the grounded cause and route the next
  contribution under the shared convergence contract
  (`sdlc/procedure/lifecycle/review`), without changing verdict ownership or
  weakening unresolved findings, which still block approval.
- The state machine checkpoint is crash-safe — re-calling `telec todo work` resumes from last state.

## See also

- ~/.teleclaude/docs/sdlc/procedure/lifecycle/work/build.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/work/review-build.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/fix-review-findings.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/work/finalize.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/work/deferrals.md
