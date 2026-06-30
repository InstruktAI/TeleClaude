---
description: 'Phase A state machine driving a Todo from draft input through PRD → architecture → plan to prepared, returning the next orchestrator instruction on each call.'
visibility: 'public'
---

# Prepare State Machine — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The prepare state machine is the workflow capability that drives a Todo through its preparation Phases — from the initial `draft` Phase, through `prd_drafting`, `prd_human_approval`, optionally `architecture_drafting` / `architecture_review`, then `plan_drafting` / `plan_review`, and finally `prepared`. Each call by the orchestrator advances exactly one logical step: it reads the persisted Todo state, derives the current Phase from artifact presence and review verdicts, and returns a verbatim instruction telling the orchestrator what to do next — load a drafting procedure inline, dispatch a reviewer worker, request a human approval Stamp, or recognize that the Todo is now `prepared`.

A `kind=task` Todo does not enter this machine. Task preparation is a separate non-SDLC lane: `/next-prepare-task` reads `input`, writes the `task-plan`, and requests human authorization — dispatched by the lifecycle runner, never by this state machine or `telec todo prepare`. The phase advances to `prepared` on `task-plan` presence without any PRD, architecture, implementation-plan, or reviewer verdict.

Preparation is local-first and runs on the project's `main` branch with no worktree, which is what authorizes it to write artifacts and snippets to the canonical doc layer. The machine itself owns no UI or worker code; it owns the invariants on transitions and the resolution of which next instruction matches the current evidence. When the entrypoint is a structural holder, prepare refuses to operate on the holder directly and routes the operator to the runnable direct children instead. When tracked artifacts have drifted along any of the classes enumerated in `@spec/feature/workflow/drift-detection` (code, upstream-artifact, owned-snippet, upstream-snippet, age), the machine surfaces drift as a blocker and routes to a drift-analyzer worker before the Todo may reach `prepared`; the per-artifact collapsed status follows the `substantive > pending > cosmetic > fresh` priority rule. A loop guard bounds in-call internal transitions so a misconfigured state always surfaces an explicit error rather than spinning silently.

## Canonical fields

### Use cases

```
Given a Todo at lifecycle_phase=draft with no prd Artifact
When the orchestrator runs "telec todo prepare my-feature"
Then the machine loads the BA intake procedure for the orchestrator session
And the returned instruction tells the session to read the procedure and author a prd Artifact
And the machine does NOT dispatch a separate worker for drafting
```

```
Given a Todo at lifecycle_phase=prd_drafting with a freshly written prd Artifact
When the orchestrator calls "telec todo prepare my-feature" again
Then the machine derives the next lifecycle_phase as prd_human_approval
And returns an instruction to read the prd to a real human and run "telec todo stamp my-feature --prd-approved"
And refuses to advance until that approval Stamp is recorded
```

```
Given a Todo with prd_approved whose architecture_drafting authored design directly into the affected domain-spec / architecture-v2 snippets plus a thin architecture index Artifact
When the orchestrator calls "telec todo prepare my-feature"
Then the machine derives lifecycle_phase=architecture_review
And dispatches the next-review-architecture worker via a verbatim tool-call instruction
And the orchestrator is told to call "telec todo prepare my-feature" again when the reviewer idles
And the architecture-review verdict (approve | needs_work | needs_decision) drives the next derivation
```

```
Given a Todo whose architecture is intentionally not needed for this work
When the orchestrator stamps "telec todo stamp my-feature --architecture-skipped '<reason>'"
Then on the next prepare call the machine treats architecture as resolved without an Artifact
And advances past the architecture phases straight to plan_drafting on the next derivation
```

#### UC-WPS7: An artifact rewritten after review approval is re-reviewed before the gate advances

```gherkin
Given a reviewer-approved Artifact (implementation-plan, architecture, or legacy requirements) whose review verdict is approve with approved_digest bound to the reviewed content
When that Artifact is rewritten so its live digest no longer equals approved_digest
And the orchestrator calls "telec todo prepare my-change"
Then the machine does NOT treat the stale approval as satisfying that Artifact's review gate
And it derives the Artifact's review phase (plan_review, architecture_review, or prd_human_approval for legacy requirements) so the rewritten Artifact is re-reviewed
And only an approve verdict whose approved_digest equals the current digest advances past that gate
```

#### UC-WPS8: A PRD rewritten after human approval is re-approved before the gate advances

```gherkin
Given a feature Todo whose prd_approved Stamp is human-approved with approved_digest bound to the approved prd
When the prd Artifact is rewritten so its live digest no longer equals approved_digest
And the orchestrator calls "telec todo prepare my-feature"
Then the machine does not advance past the PRD gate
And it derives lifecycle_phase=prd_human_approval
And only a human approval whose approved_digest equals the current prd digest advances past that gate
And an approval with no bound approved_digest keeps satisfying the PRD gate for legacy state
```

#### UC-WPS9: A pending substantive upstream drift re-opens the PRD gate even for a legacy approval

```gherkin
Given a feature Todo whose prd_approved Stamp is human-approved
And the prd Artifact's live digest still equals the approved content, including the legacy case where the approval bound no approved_digest
And a substantive upstream-artifact drift on the prd — its recorded input digest no longer equals the current input — supersedes the approval, because the approval carries no approved_at or the drift was stamped after approved_at
When the orchestrator calls "telec todo prepare my-feature"
Then the machine does not advance past the PRD gate
And it derives lifecycle_phase=prd_human_approval so the intent-level input change re-derives and re-approves the prd
And a substantive verdict driven only by the prd's downstream evidence, with the input digest unchanged, does not re-open the gate
And a cosmetic drift verdict does not re-open the gate
And a human re-approval whose approved_at is at or after the drift stamp advances past the gate
```

#### UC-WPS10: A plan-drafting re-entry carries an explicit dispatch reason

```gherkin
Given a Todo at lifecycle_phase=plan_drafting whose implementation-plan Artifact is present
When the orchestrator calls "telec todo prepare my-bug" and the re-entry is a substantive-drift clear (plan_review.cleared_by_substantive_drift)
Then the loaded plan-drafting procedure dispatch carries the header "Dispatch reason: substantive-drift"
And when instead the present plan is a --plan seed (implementation_plan.seeded) the header reads "Dispatch reason: seeded"
And when no implementation-plan Artifact is present the header reads "Dispatch reason: fresh"
And a non-plan drafting phase (e.g. diagnose) dispatch carries no dispatch-reason header
```

#### UC-WPS6: Task todos bypass the prepare machine

```gherkin
Given a Todo has kind="task" at lifecycle_phase="task_plan_drafting"
When an operator runs `telec todo prepare my-task`
Then the prepare state machine does not own task preparation
And it routes the operator to the task lane (`/next-prepare-task`, dispatched by the lifecycle runner)
And it requires no PRD, architecture, implementation-plan, or reviewer verdict for the task
```

```
Given an entrypoint slug is a structural holder with direct children child-a and child-b
When the orchestrator calls "telec todo prepare holder-slug"
Then the machine resolves the runnable children and returns an instruction listing "telec todo prepare child-a" and "telec todo prepare child-b"
And the machine never writes lifecycle state for the holder
And if every direct child is already prepared or delivered, the instruction explains which terminal state the holder reached
```

#### UC-WPS11: A manual invocation on an unclaimed slug claims in-process (bindable caller) or spawns an orchestrator (unbound operator START)

```gherkin
Given a Todo with no live holder (active_runner is empty)
And an operator invokes "telec todo prepare my-todo" from a bindable live session that is not already bound to my-todo
When the lifecycle operation runs
Then the invoking session claims my-todo as its live active-runner in-process
And the prepare state machine runs in the invoking session
And no separate orchestrator session is dispatched for my-todo
```

```gherkin
Given a Todo with no live holder (active_runner is empty)
And an unbound operator START invokes "telec todo prepare my-todo" from a caller that does not resolve to a bindable live session
When the lifecycle operation runs
Then it spawns a `/next-prepare` orchestrator session for my-todo, writing active_runner and manually_started with the spawn
And the spawned session — not the unbound caller — becomes the live driver
```

```
Given a Todo at lifecycle_phase=plan_review with an approved plan
And any tracked artifact's per-class drift derivation (see @spec/feature/workflow/drift-detection) collapses to pending or substantive
When the orchestrator calls "telec todo prepare my-feature"
Then the machine derives a blocking drift status for the affected artifact
And dispatches the next-drift-analyze worker with the pending classes named per artifact
And requires a "--drift-reviewed" stamp for every pending artifact before the Todo may reach prepared
And on substantive verdict clears the affected artifact's review verdict and every downstream review verdict, then routes back to that artifact's drafting phase
And on cosmetic verdict records the evidence anchor at which the verdict was made so the verdict expires lazily when current evidence moves past the anchor
```

```
Given a Todo whose state has somehow accumulated a contradictory phase that the machine cannot resolve
When the orchestrator calls "telec todo prepare my-feature"
Then the loop iterates up to the prepare loop limit and exits with a non-recoverable instruction
And the instruction tells the operator to inspect via "telec todo show my-feature" and surface the issue to the user
```

#### UC-WPS12: A manual prepare invocation releases a held unclaimed slug

```gherkin
Given a Todo with `hold=true`
And no live holder owns the Todo
When an operator invokes "telec todo prepare my-todo" from a bindable live session
Then the lifecycle operation clears hold as part of the successful claim/start path
And the invoking session claims my-todo as its live active-runner in-process
```

#### UC-WPS13: A manual prepare invocation refuses a held slug with a live holder

```gherkin
Given a Todo with `hold=true`
And a live holder owns the Todo
When an operator invokes "telec todo prepare my-todo"
Then the lifecycle operation is refused
And the live holder remains the active runner
And hold remains intact
```

### Auto-continue

Auto-continue is the PREPARED transition behavior that dispatches prepare for newly unblocked dependent children. The executable scenarios are `UC-WPS1` and `UC-WPS2`.

PREPARED does not dispatch dependent children
from inside the prepare state machine. The prepare machine's responsibility at
PREPARED is to persist/emit the phase transition and return its own cleanup
instruction. Dependent child selection and dispatch belong to the lifecycle
runner. In v1, PREPARED currently has no runner wake-up emission; this delivery
wires the existing phase-transition seam (the same seam that currently emits
finalize-ready only) to publish or bridge the target `workflow.todo.phase_advanced`
wake-up for PREPARED and other eligibility-changing prepare/work transitions.
The runner then evaluates the full eligible project set and dispatches children
only after acquiring `(project, child_slug, prepare)` claims.

This supersedes parent-worker reuse for child prepare. A prepare session must
not send a new `/next-prepare` instruction to itself, must not rebind a parent
worker to a child slug, and must not rely on the parent worker's live context as
the child's execution substrate. The child's context is recovered from frozen
artifacts/snippets and normal docs retrieval.

### Use cases

#### UC-WPS1: PREPARED auto-continues into unblocked child prepare

```gherkin
Given "parent" reaches lifecycle_phase=PREPARED and "child" has edge {child: [parent]} and child's prepare gate is now satisfied
When the orchestrator calls "telec todo prepare parent" and the machine derives PREPARED
Then the machine, in addition to emitting parent's prepared-cleanup, derives the now-unblocked dependent children (prepare gate satisfied for every dep)
And for each such child it emits a CONCRETE auto-continue operation — not a human-in-the-loop suggestion
And the emitted operation reuses an open prepare worker: it locates the parent's live prepare worker via the slug+command match and emits "telec sessions send <parent_worker> '<drive prepare for child>'" so the child's prepare builds on the parent's just-frozen design held in that worker's context
And when no live parent prepare worker exists it falls back to a fresh "telec sessions run --command /next-prepare --args child"
And when auto-continue reuses the parent worker, that worker is NOT ended by prepared-cleanup; only other live parent sessions (e.g. reviewers) are ended
```

#### UC-WPS2: PREPARED cleanup is unchanged without unblocked children

```gherkin
Given "parent" reaches PREPARED but has no dependent children whose prepare gate it satisfies
When the machine derives PREPARED
Then it emits the normal prepared-cleanup (end all live parent sessions, including the orchestrator) with no auto-continue operation
```

#### UC-WPS5: PREPARED emits a runner wake-up, not a child dispatch

```gherkin
Given "parent" reaches lifecycle_phase=PREPARED
And "child-a" and "child-b" may now have their prepare gates satisfied
When the orchestrator calls "telec todo prepare parent" and the machine derives PREPARED
Then the v1 phase-transition seam emits or bridges the target `workflow.todo.phase_advanced` wake-up for "parent"
And returns only "parent" cleanup/terminal instructions
And it does not emit `telec sessions send <parent_worker>` for any child
And it does not emit a fresh `/next-prepare` run for any child
And the lifecycle runner handles child eligibility and dispatch from the event wake-up
```

### Selector

The slugless selector skips kind-less Todos until `/analyze-todo-input` assigns a concrete kind. The executable scenario is `UC-WPS3`.

#### UC-WPS3: Slugless prepare skips kind-less Todos awaiting classification

```gherkin
Given a kind-less Todo exists with kind unset and no lifecycle_phase
When the orchestrator runs "telec todo prepare" without an explicit slug
Then the prepare selector skips that Todo because it is awaiting /analyze-todo-input classification
And it reports that no ready prepare items exist instead of raising a lifecycle_phase error
```

#### UC-WPS4: Explicit prepare rejects unknown slugs without creating roadmap rows

```gherkin
Given no active or iceboxed Todo exists for "unknown-prepare"
When the orchestrator runs "telec todo prepare unknown-prepare"
Then the prepare machine returns TODO_NOT_FOUND with a concrete todo-create next step
And no roadmap row is created for "unknown-prepare"
```

### Cross-context references

- `agent_runtime` — drafting Phases load procedures into the orchestrator session inline; reviewer Phases (architecture-review, plan-review) and the drift-analyzer dispatch a worker session.

- `integration` — when an Artifact's anchored evidence (origin/main HEAD, upstream-artifact digests, owned/upstream snippet digests) moves past the recorded anchor on any applicable class, the drift derivation flips that artifact's collapsed status to pending and the machine refuses to advance to `prepared`. See `@spec/feature/workflow/drift-detection` for the full class taxonomy and the evidence anchor semantics.

- `session_ledger` — the resolved session principal for each Stamp is recorded so the PRD-approval gate can refuse approvals authored by a non-human principal.
- `identity` — the `--prd-approved` Stamp requires the caller's principal to resolve to a real human; orchestrator-emulated PO sessions cannot satisfy this gate.
- `knowledge` — drafting procedures and reviewer briefings pull doc snippets so the worker is grounded against the same canonical docs the architecture invariants reference.

## Known caveats

- Prepare runs on `main` with no worktree. The machine itself does not branch; the work-state machine is the first stage that materializes a per-slug worktree.
- A holder entry cannot itself enter prepare. The orchestrator is always routed to its direct, runnable children — even when the holder is the explicit slug argument.
- A `change` created with `--plan` enters prepare at plan-drafting with the supplied `implementation-plan` Artifact as a seed (dispatch reason `seeded`). The planner grounds the supplied plan against the blast radius, reflects the affected doc snippets, and the plan is reviewed before `prepared`. The flag accelerates drafting; it does not bypass plan-draft or plan-review.
- A plan re-entered after a substantive code-drift verdict enters plan-drafting with the existing `implementation-plan` Artifact present (dispatch reason `substantive-drift`). The planner re-grounds the existing plan against the drifted code and preserves the tasks whose grounding still holds; it does not produce the plan from scratch. The plan-drafting procedure-load dispatch carries the computed dispatch-reason header (`fresh` when no plan exists, `seeded` for a supplied seed, `substantive-drift` for this re-derivation) so the planner never mistakes a re-entry for a first draft.
- A plan re-entered after a `--kickback` stamp follows the same substantive-drift path: the stamp sets `plan_review.cleared_by_substantive_drift`, so the machine derives plan-drafting with dispatch reason `substantive-drift`. The derivation is unchanged from a drift-driven re-entry; only the trigger and the payload differ — the kickback is an authored work-orchestrator stamp rather than a derived drift verdict, and it carries its reason in a delimited block appended to `input`, which the planner reads as authoritative re-derivation context.

- The PRD gate is the only mandatory human approval. Architecture and plan advance on the reviewer Worker's verdict; `--architecture-skipped` exists precisely so that not every Todo has to pay the architecture phase. There is no separate test-specs phase — Gherkin acceptance scenarios are authored into the feature spec snippet during intake.
- A PRD authored in standin / emulated-PO mode cannot be Stamped `prd_approved`. The gate requires a real-human principal regardless of how plausible the emulated approval looks.
- The drift check is a real gate, not advisory. Any Artifact whose per-class derivation collapses to pending or substantive blocks `prepared` until the affected Artifact has been Stamped `drift-reviewed` after analysis. Cosmetic stamps are scoped to the evidence anchor they were made at and expire lazily when new evidence arrives — see `@spec/feature/workflow/drift-detection`.
- The prepare loop limit is a contradiction detector, not a workload knob. Hitting it means the derived Phase keeps changing without converging — fix the underlying state, do not raise the limit.
- The machine does not auto-add the slug to the todo list when called on a holder; auto-add happens only after holder resolution confirms the slug is a leaf prepare target.

- **Auto-continue at PREPARED is concrete, not advisory.** When a parent reaches `PREPARED` it unblocks the **prepare** gate (not the work gate) of its dependents — so the dependents' prepare auto-continues immediately, while their work still waits for the parent's delivery (see `@spec/feature/workflow/dependency-graph`). The continuation is dispatched, not suggested to the human.
- **Worker reuse preserves context.** Auto-continue prefers reusing the parent's open prepare worker via `telec sessions send` (the existing reuse-or-spawn dispatch keyed by parent slug + `/next-prepare`), because that worker holds the parent's just-frozen design. One worker thus carries multiple slugs in context across the dependency chain. A fresh `telec sessions run` is the fallback only when no parent worker is live; the parent's design is still recoverable from its now-frozen artifacts and snippets. No session↔slug rebinding is required: the reuse lookup is always keyed by the _parent_ slug (whose worker title is intact), and that worker then drives the child inline.

- **Runner-owned dependent dispatch supersedes PREPARED auto-continue.** The two current caveats above describe the pre-runner target. After `runner-dispatch`, the concrete dispatch still happens automatically, but it is performed by `workflow.lifecycle_runner` from the emitted wake-up event, not by the parent prepare state-machine response. Parent-worker reuse is forbidden for child dispatch; each child session is explicitly bound to its own slug.
