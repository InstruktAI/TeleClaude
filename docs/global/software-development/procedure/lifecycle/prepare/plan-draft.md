---
description: 'Plan drafting phase for next-prepare. Produces implementation plans from human-approved PRD, optional reviewer-approved architecture, and optional reviewer-approved test-specs artifacts.'
domain: 'software-development'
id: 'software-development/procedure/lifecycle/prepare/plan-draft'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Prepare Plan Draft — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Your focus this turn is the plan phase: produce an `implementation-plan`
artifact from the human-approved PRD, the reviewer-approved architecture
(when present), and the reviewer-approved test-specs (when present); or split
the todo into dependent child work items when planning shows the work is not
atomic. The wider prepare lifecycle is still yours; this phase is one focused
part of it.

### Outcome

Produce `implementation-plan` from the human-approved `prd`, optional reviewer-approved `architecture`,
and optional reviewer-approved prose `test-specs`; or split the todo into dependent child work
items when planning shows the work is not atomic.

The plan must be detailed enough for a builder to execute without guessing, and
review-aware enough that the reviewer finds no surprises. If that bar cannot be met
for one builder session, this phase owns the split.

## Preconditions

1. `telec todo artifacts read {slug} prd` exists and is human-approved.
2. `architecture` is either reviewer-approved or explicitly skipped.
3. `test-specs` is either reviewer-approved or explicitly skipped.
4. `todos.db` roadmap is readable.
5. Slug is active (not icebox, not delivered).

## Steps

### 1. Read and ground

Read the full context before writing anything:

- `telec todo artifacts read {slug} prd` — the human-approved product intent and success criteria.
- `telec todo artifacts read {slug} architecture` — when present; otherwise read the skip reason.
- `telec todo artifacts read {slug} test-specs` — when present; otherwise read the skip reason.
- `telec todo artifacts read {slug} input` — the original human thinking (for intent).
- The codebase: files that will be affected, adjacent patterns, existing implementations
  of similar functionality. Use `telec docs index` for relevant policies and specs.
- Definition of Done — every plan task must produce output that satisfies DoD gates.

Apply the domain-context loading rule from the preparation artifact quality
policy: identify which specs the PRD, architecture, and test-specs touch and load them before
drafting begins. Domain specs are the ground truth — grounding and
review-awareness cannot be evaluated without them.

### 1b. Re-entry classification (read the dispatch reason)

Re-entry is the base case for plan drafting — fresh production is the special
case (first time only). Every dispatch carries a `Dispatch reason: <reason>`
header. Pick your behavior from the reason:

- **`fresh`** — no prior implementation plan exists. Produce one from human-approved
  PRD, optional reviewer-approved architecture, and optional reviewer-approved test-specs. This is the only path that uses the full atomicity
  decision (step 2) and full draft (step 3).
- **`findings-fix`** — a `needs_work` verdict was issued. Read
  `telec todo artifacts read {slug} plan-review-findings` alongside the existing
  plan. Apply targeted fixes to address each finding. Preserve every task not
  flagged by the findings. Skip the atomicity decision (step 2) and proceed
  directly to step 5.
- **`upstream-changed`** — the plan's recorded `upstream_digests` (`prd`,
  `architecture`, and/or `test-specs`) drifted from current. Run the `Changes since` diff commands
  listed in the dispatch. Identify the plan tasks whose grounding referenced the
  changed upstream content. Update only those tasks; preserve every task whose
  grounding is unchanged. Skip the atomicity decision and proceed to step 5.
- **`provenance-missing`** — the plan exists but its upstream provenance is
  empty (legacy state). Read the existing plan via
  `telec todo artifacts read {slug} implementation-plan`. Verify each task's
  grounding against current `prd`, `architecture`, and `test-specs`. Update only
  tasks whose grounding has actually drifted; preserve tasks that still pin
  the upstream artifact correctly. Skip the atomicity decision and proceed to step 5.

### 2. Decide whether the todo is atomic

**This step is mandatory and must produce an explicit verdict before any plan
drafting begins.** Apply DOR Gate 2 (Scope & size) using the splitting heuristics
in the Definition of Ready policy. Ground in the actual code — not the prose.

Evaluate:

- Does the work contain multiple independently shippable workstreams? If yes, split.
- Count the phases, new modules, and distinct behavioral changes. A plan that spans
  more than one coherent builder behavior must be split.
- Apply the DOR coherence test, coordination cost, and detail-inverts-complexity
  heuristics from the policy.

**If the work fails the scope/size gate, stop here.** Do not draft a plan for
work that will fail gate validation. Split first:

- create focused child todos
- seed them from the human-approved parent PRD and any reviewer-approved architecture/spec slices
- add dependency ordering in `todos.db` roadmap
- call `telec todo split <slug> --into <child1> <child2> ...`
- stop treating the parent as directly builder-ready

If the work passes the scope/size gate, continue to plan drafting.

### 3. Draft the implementation plan

Apply the plan-specific quality rules from the preparation artifact quality
policy. Structure the plan as an ordered task list. Each task must include:

- **What**: the concrete change (file, function, component).
- **Why**: the rationale for the approach. This prevents the builder from taking shortcuts.
  If the plan says "use adapter pattern" but doesn't say why, the builder may inline the
  logic instead. The "why" is the guard against drift.
- **Verification**: how the builder confirms the task is done (test to write, behavior to
  observe, lint to pass). Each task references the PRD success criteria and any
  test-spec cases it satisfies. When the test-specs phase was skipped, the task
  states the existing test or direct verification that covers the behavior.
- **Referenced files**: exact file paths that will be created or modified. These are
  used by the state machine for grounding and staleness detection.

Verify plan tasks against the domain specs loaded in step 1. Plans that reference
non-existent APIs, wrong schema fields, or incorrect directory structures are
defective — the builder will discover the error at build time, wasting a session.

### 3b. Intelligence-boundary check

Per `principle/intelligence-boundaries`, scan every task you've drafted with
this question: does the task prescribe code that classifies, scores, judges,
evaluates, or auto-edits content semantics? If yes, that task is intelligence
in the wrong layer — the rule belongs in the agent's briefing, not in code
the agent wraps. Strike the task, or restate it as a briefing change.

Detection patterns to refuse in plan tasks:

- "Build a classifier / scorer / validator / checker for [free-text content]."
- "Add a regex / vocabulary table / word-count threshold that decides whether
  agent output is meaningful / actionable / complete / on-topic."
- "Auto-edit / auto-fix / auto-rewrite agent artifacts to match a structural
  rubric."
- Predicates on natural language: `is_meaningful`, `should_emit`,
  `is_actionable`, `is_ack`, `classify_*` on free text.

The defining test: would this task be unnecessary if the agent's briefing
said the right thing? If yes, the task is policy in the wrong layer — fix
the briefing instead.

### 4. Anticipate review lanes

Apply the DoD-driven review-awareness rule from the preparation artifact quality
policy. The plan must pre-satisfy what the reviewer will check. For each
PRD success criterion, identify which DoD gates it triggers and verify those implications
are reflected as task verification steps.

A plan that does not anticipate review lanes will produce review findings that cost
more to fix than they cost to prevent.

### 5. Write artifacts

If the todo stays atomic, write (using human-approved PRD, optional reviewer-approved architecture, and optional reviewer-approved test-specs as inputs):

- `telec todo artifacts write {slug} implementation-plan <content>` — the full plan with tasks, rationale, and verification.
  Each task must reference which PRD criteria and test-spec cases it satisfies.

Do not write grounding fields directly. The state machine owns grounding
metadata and current worktree state.

If the todo is split instead:

- Call `telec todo split <slug> --into <child1> <child2> ...`
- Seed each child's `input` with the relevant subset of parent PRD and reviewer-approved architecture/spec context.

### 6. Enforce boundaries

- Do not invent behavior not grounded in PRD, architecture, test-specs, or codebase patterns.
- Do not rewrite approved or reviewer-approved upstream artifacts unless the plan is blocked by a genuine
  contradiction in those artifacts.
- Do not change roadmap status beyond the child dependency links needed for a split.
- If blocked by uncertainty, record the blocker and continue with what is known.

### 7. Final step — advance

When the implementation-plan artifact is written (or the split has been
executed via `telec todo split`), call:

```
telec todo prepare {slug}
```

The state machine routes the next action. It will direct you to dispatch the
plan reviewer and tail it. On `approve` it advances toward `PREPARED`. On
`needs_work` it routes you back here to address the findings; read
`telec todo artifacts read {slug} plan-review-findings`, update the
implementation-plan to resolve each finding, then advance again.

## Outputs

1. Atomic case:
   `telec todo artifacts read {slug} implementation-plan` and updated
   `todos.db` state.
2. Split case:
   child todos, dependency links, and updated holder `breakdown`.

## Recovery

1. If the PRD is ambiguous, note the ambiguity in the plan and derive the
   most likely interpretation. Mark it `[inferred]` in the plan.
2. If planning reveals the parent is not atomic, split it rather than stretching one
   builder plan past the session-size limit.
3. If a file referenced in an upstream artifact does not exist, verify whether it should be
   created or whether the upstream artifact is stale.
