---
description: 'Plan drafting phase for next-prepare. Produces implementation plans from human-approved PRD and the optional reviewer-approved architecture (thin index artifact plus the doc snippets it points at).'
visibility: 'public'
---

# Prepare Plan Draft — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md

## Goal

Your focus this turn is the plan phase: produce an `implementation-plan`
artifact from the human-approved PRD and the reviewer-approved architecture
when present (the thin index artifact plus the doc snippets it points at); or
split the todo into dependent child work items when planning shows the work is
not atomic. The wider prepare lifecycle is still yours; this phase is one
focused part of it.

### Outcome

Produce `implementation-plan` from the human-approved `prd` and the optional
reviewer-approved `architecture` (the thin index artifact plus the
domain-spec / design-doc snippets it points at); or split the todo into
dependent child work items when planning shows the work is not atomic.

The plan must be detailed enough for a builder to execute without guessing, and
review-aware enough that the reviewer finds no surprises. If that bar cannot be met
for one builder session, this phase owns the split.

## Preconditions

1. The approved intent artifact resolves — `prd` for a `feature`, `input` for a
   `change` (see `software-development/concept/approved-intent-artifact`). A
   `change` has no PRD by design; `input` is its intent. A `change` created via
   `--plan` has no `input` either — its seeded `implementation-plan` is the intent
   basis (see the `seeded` re-entry reason in step 1b). Drafts from a `feature`
   PRD are human-approved before this phase.
2. `architecture` is either reviewer-approved or explicitly skipped.
3. Slug is active (not icebox, not delivered).

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

### 1. Read and ground

Read the full context before writing anything:

- `telec todo artifacts read {slug} prd` — the human-approved product intent and success criteria.
- `telec todo artifacts read {slug} architecture` — when present, the thin
  index/log; otherwise read the skip reason. Read the domain-spec / design-doc
  snippets it points at for the actual design content.
- `telec todo artifacts read {slug} input` — the original human thinking (for intent).
- `telec todo artifacts read {slug} diagnosis` — when present (a `bug` carries
  this). It holds the verified, code-grounded root cause — the causal mechanism —
  and nothing more. For a `bug` the plan derives the fix that **removes** that
  cause and the verification that proves it gone, grounded in the root cause and
  the code — reference the diagnosis's root-cause section as the grounding rather
  than re-deriving the cause. Consume it exactly as `architecture` is consumed when
  present; no kind-specific branching beyond reading the artifact.
- `telec todo artifacts read {slug} investigation` — when present (a `bug` carries
  this). The evidence substrate behind the diagnosis: reproduction, avenues walked,
  observations. Read it for grounding context; the plan consumes the `diagnosis` root
  cause, not the investigation.
- The codebase: files that will be affected, adjacent patterns, existing implementations
  of similar functionality. Use a filtered `telec docs index --areas policy,spec` (add
  `--domains <domain>` to narrow) to surface relevant policies and specs.
- Definition of Done — every plan task must produce output that satisfies DoD gates.

Apply the domain-context loading rule from the preparation artifact quality
policy: identify which specs the PRD and the architecture snippets touch and load them before
drafting begins. Domain specs are the ground truth — grounding and
review-awareness cannot be evaluated without them.

### 1b. Re-entry classification (read the dispatch reason)

Re-entry is the base case for plan drafting — fresh production is the special
case (first time only). Every dispatch carries a `Dispatch reason: <reason>`
header. Pick your behavior from the reason:

- **`fresh`** — no prior implementation plan exists. Produce one from human-approved
  PRD and the optional reviewer-approved architecture. This is the only path that uses the full atomicity
  decision (step 2) and full draft (step 3).
- **`seeded`** — a complete implementation plan was supplied at creation (the
  `--plan` create path) and is present as the `implementation-plan` artifact at
  first entry, with no prior review. Treat the supplied plan as the **draft
  basis, not an oracle**: run the full grounding (step 1), the atomicity decision
  (step 2), and the blast-radius derivation (step 2c), and verify every supplied
  task as a hypothesis against the code and the domain specs rather than trusting
  it verbatim — record divergences per `preparation-artifact-quality`. Reflect
  the affected doc snippets (step 4b) and enrich the supplied plan with their
  references and blast-radius-informed verification, refining it in step 3
  instead of authoring from scratch. The supplied plan accelerates drafting; it
  does not skip grounding, blast radius, doc reflection, or the downstream plan
  review.
- **`substantive-drift`** — code under the existing plan's referenced paths
  drifted materially, clearing the prior plan review (`cleared_by_substantive_drift`)
  and routing back here with the plan still present. Read the existing plan via
  `telec todo artifacts read {slug} implementation-plan` and re-ground it against
  the changed code: re-derive the tasks whose grounding the drift invalidated and
  preserve every task the drift does not touch. Do not produce from scratch — the
  plan exists and most of it is still valid. Skip the atomicity decision (step 2)
  and proceed to step 5.
- **kickback context (rides `substantive-drift`)** — a `--kickback` stamp re-enters
  here with reason `substantive-drift`, but the trigger is an authored work-orchestrator
  invalidation rather than drifted code. The `input` artifact carries a delimited
  kickback block recording why the prior build could not execute the plan. Read that
  block first and treat it as authoritative re-derivation context: it names the defect
  the new plan must resolve and sets how far back the re-derivation reaches — a
  localized replan, or re-authoring the feature-spec scenarios the plan binds. Re-ground
  the plan to satisfy the kickback reason, not only the code.
- **`findings-fix`** — a `needs_work` verdict was issued. Read
  `telec todo artifacts read {slug} plan-review-findings` alongside the existing
  plan. Apply targeted fixes to address each finding. Preserve every task not
  flagged by the findings. Skip the atomicity decision (step 2) and proceed
  directly to step 5.
- **`upstream-changed`** — the plan's recorded `upstream_digests` (`prd`
  and/or `architecture`) drifted from current. Run the `Changes since` diff commands
  listed in the dispatch. Identify the plan tasks whose grounding referenced the
  changed upstream content. Update only those tasks; preserve every task whose
  grounding is unchanged. Skip the atomicity decision and proceed to step 5.
- **`provenance-missing`** — the plan exists but its upstream provenance is
  empty (legacy state). Read the existing plan via
  `telec todo artifacts read {slug} implementation-plan`. Verify each task's
  grounding against current `prd` and `architecture`. Update only
  tasks whose grounding has actually drifted; preserve tasks that still pin
  the upstream artifact correctly. Skip the atomicity decision and proceed to step 5.

- **`substantive-drift`** — a drift review judged the code under the plan's
  referenced paths to have changed materially, and the plan's `plan_review` was
  cleared by that substantive drift. The existing plan is present and
  authoritative: read it via
  `telec todo artifacts read {slug} implementation-plan`, re-ground each task
  against the changed code, and update only the tasks whose grounding the drift
  invalidates — preserve every task whose grounding still holds. This reason is
  distinct from `upstream-changed`: the trigger is drifted code under referenced
  paths, not a changed `prd`/`architecture` digest. Skip the atomicity decision
  and proceed to step 5.

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
work that will fail gate validation. Group first:

- read the parent's full approved scope (PRD and architecture artifacts)
- create each child with `telec todo create <child> "<child-content>" --kind <k> --group <slug>`, partitioning the parent's existing scope — adding no functional or business scope absent from the parent
- narrow each child's content to its own scope slice, drawing on the human-approved parent PRD and any reviewer-approved architecture-snippet slices
- add dependency ordering between the children with `telec todo update <child> --after <dep>`
- stop treating the parent as directly prepare/work-ready; it is now a structural holder

If the work passes the scope/size gate, continue to plan drafting.

### 2c. Derive the change's blast radius (before drafting)

- **Treat the result as candidates, not an oracle** — it surfaces structural candidates; the planner verifies each against the source and decides relevance.
- **Consume the integrator-maintained baseline; never generate or refresh it yourself** (generation is automation, at integrate-time). Run `telec context blueprint affected <changed-files>` to get the dependent set (callers, importers, subclasses, tests) with `file:line` — it resolves the files' symbols and checks the baseline's freshness for you. Use `graphify query` / `graphify path` against the baseline for seed discovery and reachability.
- **Bias to over-inclusion** — a missed dependent is a build-time surprise; an extra candidate is a discarded read. Prefer false positives, prune with judgment.
- **Blind-spot honesty** — the blueprint sees only parsed edges; dynamic dispatch, registry/string-keyed wiring, config-driven behavior, cross-language boundaries, and reflection are invisible — name the categories that apply and read those areas directly.
- **Ground the plan in the verified result** — the change surface and test adjacency derive from the verified candidate set. If the command reports the baseline missing or stale (recorded baseline commit ≠ current main), state the gap and fall back to manual exploration — never silently skip the step.

The blueprint's location, freshness manifest, command surface, and supported languages are specified in `project/spec/codebase-blueprint`.

### 3. Draft the implementation plan

Apply the plan-specific quality rules from the preparation artifact quality
policy. Structure the plan as an ordered task list. Each task must include:

- **What**: the concrete change (file, function, component).
- **Why**: the rationale for the approach. This prevents the builder from taking shortcuts.
  If the plan says "use adapter pattern" but doesn't say why, the builder may inline the
  logic instead. The "why" is the guard against drift.
- **Verification**: how the builder confirms the task is done (test to write, behavior to
  observe, lint to pass). Each task references the PRD success criteria and, for
  Category A work, the Gherkin acceptance scenarios in the feature spec snippet
  it satisfies. Otherwise the task states the existing test or direct
  verification that covers the behavior. Verification must target behavior at
  a meaningful boundary; do not prescribe logger/log-level, metric/trace,
  config/model/native-shape, private-helper, constructor-wiring, or mock-call-echo
  assertions.
- **Referenced files**: exact file paths that will be created or modified. These are
  used by the state machine for grounding and staleness detection.
- **Referenced paths contract**: author exactly one machine-readable
  ` ```referenced-paths ` fenced block in the plan body, listing every file
  the work creates or modifies, one path per line. This block is the only code
  drift surface the state machine reads. File paths mentioned in prose may help
  the builder, but they are not a drift contract unless they appear in this
  block.

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
policy. The plan must pre-satisfy what the reviewer will check — the reviewer's
lanes are the review-lanes catalog
(`software-development/policy/definition-of-done-lanes`). Produce a complete
lane-coverage report in the plan: one line per lane in the catalog, marking it
triggered (naming how the plan satisfies it) or `N/A` (with reason). No lane is
omitted — silence is not coverage.

- Deliverable-producing lanes (tests, security, docs, config, browser/UI, ADR)
  are ticked by naming the task and the artifact it produces (the doc lane via
  step 4b).
- Lanes that produce no artifact — `code` Duplication, `paradigm` Component
  reuse, and `simplify` — are ticked against the plan's own `referenced-paths`:
  confirm no task re-derives, mirrors, or re-implements logic an existing cited
  symbol already provides; where shared logic is needed, one task extracts it
  once and the others call it. A task that duplicates an existing symbol instead
  of reusing it is a defect to fix before the plan is complete.

A plan that does not tick every lane will produce review findings that cost more
to fix than they cost to prevent.

### 4b. Reflect the behavioral delta in doc snippets (mandatory)

Per `software-development/principle/documentation-first-development`, the prepare
phase authors the pending snippets that describe the work's intended state. A
`change` has no PRD, so this step owns that identification for the no-PRD lane
(and confirms it for a `feature` whose PRD already lists them):

- Identify every doc snippet (spec / principle / policy / concept / ADR) whose
  contract the work's behavioral delta changes or adds.
- Author or update each as a **pending** snippet carrying `delivered_by: [{slug}]`
  — in-context `<!-- planned:{slug} -->` blocks for additions, or a
  `<stem>.{slug}.md` companion for a wholesale rework (see the doc-snippet
  authoring procedure).
- Add a plan task for each snippet so the builder produces it and the
  documentation review lane has a named deliverable to validate.
- If the change genuinely has no documented-behavior impact, record an explicit
  `doc_impact_none: <reason>` note in the plan rather than silently omitting docs.

A change that alters documented behavior without a corresponding snippet update
(and without a `doc_impact_none` justification) is not plan-complete.

### 5. Write artifacts

If the todo stays atomic, write (using human-approved PRD and the optional reviewer-approved architecture — the thin index plus the snippets it points at — as inputs):

- `telec todo artifacts write {slug} implementation-plan <content>` — the full plan with tasks, rationale, and verification.
  Each task must reference which PRD criteria and, for Category A work, which feature-spec Gherkin scenarios it satisfies.

Do not write grounding fields directly. The state machine owns grounding
metadata and current worktree state.

If the todo is grouped instead:

- Create each child with `telec todo create <child> "<child-content>" --kind <k> --group <slug>`, one per independently deliverable slice.
- Treat the parent as a stateless holder once children group-reference it. Its retained input artifact is frozen source material; do not plan follow-up writes against the holder.
- Each child's content carries the relevant subset of parent PRD and reviewer-approved architecture-snippet context.
- Treat only the children as prepare/work targets. The parent is a holder and must not be prepared or worked as an implementation item.

### 6. Enforce boundaries

- Deliver exactly the intent of the approved artifact (`prd` for a feature; `input`, sharpened by `diagnosis`, for a change/bug) and preserve the existing documented and working behavior the change touches — see "Scope is bounded" in `preparation-artifact-quality`. A forced decision that stays within scope follows established behavior; one that would shift scope or spec is surfaced to the human.
- Do not rewrite approved or reviewer-approved upstream artifacts unless the plan is blocked by a genuine
  contradiction in those artifacts.
- Do not change todo status beyond the child dependency links needed for a split.
- If blocked by uncertainty, record the blocker and continue with what is known.

### 7. Final step — advance

When the implementation-plan artifact is written (or child grouping has been
executed via `telec todo create ... --group`), call:

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
   `telec todo artifacts read {slug} implementation-plan`.
2. Grouped case:
   child todos, dependency links, and a stateless holder row with frozen input only.

## Recovery

1. If the PRD is ambiguous, note the ambiguity in the plan and derive the
   most likely interpretation. Mark it `[inferred]` in the plan.
2. If planning reveals the parent is not atomic, group it into children rather than stretching one
   builder plan past the session-size limit.
3. If a file referenced in an upstream artifact does not exist, verify whether it should be
   created or whether the upstream artifact is stale.
