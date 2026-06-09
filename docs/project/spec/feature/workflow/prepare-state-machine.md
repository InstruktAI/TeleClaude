---
id: 'project/spec/feature/workflow/prepare-state-machine'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Phase A state machine driving a Todo from draft input through PRD → architecture → plan to prepared, returning the next orchestrator instruction on each call.'
---

# Prepare State Machine — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The prepare state machine is the workflow capability that drives a Todo through its preparation Phases — from the initial `draft` Phase, through `prd_drafting`, `prd_human_approval`, optionally `architecture_drafting` / `architecture_review`, then `plan_drafting` / `plan_review`, and finally `prepared`. Each call by the orchestrator advances exactly one logical step: it reads the persisted Todo state, derives the current Phase from artifact presence and review verdicts, and returns a verbatim instruction telling the orchestrator what to do next — load a drafting procedure inline, dispatch a reviewer worker, request a human approval Stamp, or recognize that the Todo is now `prepared`.

Preparation is local-first and runs on the project's `main` branch with no worktree, which is what authorizes it to write artifacts and snippets to the canonical doc layer. The machine itself owns no UI or worker code; it owns the invariants on transitions and the resolution of which next instruction matches the current evidence. When the entrypoint is a split holder, prepare refuses to operate on the holder directly and routes the operator to the runnable direct children instead. When tracked artifacts have drifted along any of the classes enumerated in `@spec/feature/workflow/drift-detection` (code, upstream-artifact, owned-snippet, upstream-snippet, dependency-graph, age), the machine surfaces drift as a blocker and routes to a drift-analyzer worker before the Todo may reach `prepared`; the per-artifact collapsed status follows the `substantive > pending > cosmetic > fresh` priority rule. A loop guard bounds in-call internal transitions so a misconfigured state always surfaces an explicit error rather than spinning silently.

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

```
Given an entrypoint slug is a split holder with direct children child-a and child-b
When the orchestrator calls "telec todo prepare holder-slug"
Then the machine resolves the runnable children and returns an instruction listing "telec todo prepare child-a" and "telec todo prepare child-b"
And the machine never writes lifecycle state for the holder
And if every direct child is already prepared or delivered, the instruction explains which terminal state the holder reached
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


### Auto-continue

Auto-continue is the PREPARED transition behavior that dispatches prepare for newly unblocked dependent children. The executable scenarios are `UC-WPS1` and `UC-WPS2`.

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


### Cross-context references

- `agent_runtime` — drafting Phases load procedures into the orchestrator session inline; reviewer Phases (architecture-review, plan-review) and the drift-analyzer dispatch a worker session.
- `integration` — when an Artifact's anchored evidence (origin/main HEAD, upstream-artifact digests, owned/upstream snippet digests, dep-graph snapshot) moves past the recorded anchor on any applicable class, the drift derivation flips that artifact's collapsed status to pending and the machine refuses to advance to `prepared`. See `@spec/feature/workflow/drift-detection` for the full class taxonomy and the evidence anchor semantics.
- `session_ledger` — the resolved session principal for each Stamp is recorded so the PRD-approval gate can refuse approvals authored by a non-human principal.
- `identity` — the `--prd-approved` Stamp requires the caller's principal to resolve to a real human; orchestrator-emulated PO sessions cannot satisfy this gate.
- `knowledge` — drafting procedures and reviewer briefings pull doc snippets so the worker is grounded against the same canonical docs the architecture invariants reference.

## Known caveats

- Prepare runs on `main` with no worktree. The machine itself does not branch; the work-state machine is the first stage that materializes a per-slug worktree.
- A holder entry cannot itself enter prepare. The orchestrator is always routed to its direct, runnable children — even when the holder is the explicit slug argument.
- A `change` created with `--plan` skips the prepare lifecycle entirely; it lands in `work` with an `implementation-plan` Artifact already present.
- The PRD gate is the only mandatory human approval. Architecture and plan advance on the reviewer Worker's verdict; `--architecture-skipped` exists precisely so that not every Todo has to pay the architecture phase. There is no separate test-specs phase — Gherkin acceptance scenarios are authored into the feature spec snippet during intake.
- A PRD authored in standin / emulated-PO mode cannot be Stamped `prd_approved`. The gate requires a real-human principal regardless of how plausible the emulated approval looks.
- The drift check is a real gate, not advisory. Any Artifact whose per-class derivation collapses to pending or substantive blocks `prepared` until the affected Artifact has been Stamped `drift-reviewed` after analysis. Cosmetic stamps are scoped to the evidence anchor they were made at and expire lazily when new evidence arrives — see `@spec/feature/workflow/drift-detection`.
- The prepare loop limit is a contradiction detector, not a workload knob. Hitting it means the derived Phase keeps changing without converging — fix the underlying state, do not raise the limit.
- The machine does not auto-add the slug to the todo list when called on a holder; auto-add happens only after holder resolution confirms the slug is a leaf prepare target.


- **Auto-continue at PREPARED is concrete, not advisory.** When a parent reaches `PREPARED` it unblocks the **prepare** gate (not the work gate) of its dependents — so the dependents' prepare auto-continues immediately, while their work still waits for the parent's delivery (see `@spec/feature/workflow/dependency-graph`). The continuation is dispatched, not suggested to the human.
- **Worker reuse preserves context.** Auto-continue prefers reusing the parent's open prepare worker via `telec sessions send` (the existing reuse-or-spawn dispatch keyed by parent slug + `/next-prepare`), because that worker holds the parent's just-frozen design. One worker thus carries multiple slugs in context across the dependency chain. A fresh `telec sessions run` is the fallback only when no parent worker is live; the parent's design is still recoverable from its now-frozen artifacts and snippets. No session↔slug rebinding is required: the reuse lookup is always keyed by the _parent_ slug (whose worker title is intact), and that worker then drives the child inline.
