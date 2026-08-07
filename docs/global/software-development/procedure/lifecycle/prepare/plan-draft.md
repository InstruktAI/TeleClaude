---
description: 'Plan drafting phase for next-prepare. Produces implementation plans from human-approved PRD and the optional reviewer-approved architecture (thin index artifact plus the doc snippets it points at).'
visibility: 'public'
---

# Prepare Plan Draft — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/policy/regression-zero-tolerance.md
- @~/.teleclaude/docs/software-development/procedure/blast-radius-discovery.md
- @~/.teleclaude/docs/software-development/policy/quality-predicate-registry.md

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

A feature PRD also carries an approved `prd_review` verdict for its current
digest before human approval.

2. `architecture` is either reviewer-approved or explicitly skipped.
3. Slug is active (not icebox, not delivered).

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

### 1. Read and ground

Apply the artifact-discovery rule from `preparation-artifact-quality`
(`telec todo artifacts list {slug}`) before assuming the list below is
everything present — read `log` when it exists, and any other artifact this
todo's history left behind that bears on grounding.

Read the full context before writing anything:

- The resolved approved intent artifact. For a feature, read the independently
  reviewed and human-approved `prd`; for a change or bug, read `input`; for a
  planned change with no input, read the plan's existing _Intent & scope_.

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

### 1c. Situate the premise in the existing todo landscape (`fresh` only)

Applies on the `fresh` re-entry reason only, for `change` and `bug` — a
`feature` already does this at intake step 1.6 before it ever reaches this
phase. Before drafting, compare this premise against the existing todo
landscape: the same collecting discipline as intake step 1.6, pointed at the
todo list instead of the domain, and distinct from a `bug`'s diagnose Step 1
(which retires an exact-defect duplicate earlier in the lifecycle, before this
phase runs) — this step catches broader scope overlap with _unrelated_ todos,
not same-defect duplicates.

**Scan** the active and prepared-unclaimed todos (`telec todo list`). Keep it
bounded: that set only — delivered, removed, and iceboxed todos are out of
scope. Read cheap signals first (slug, then `input`), reaching for a
candidate's deeper artifacts only when it looks genuinely related.

**Judge the relation and its direction** — precedence is default, intent is
the override:

- **This premise yields** — redundant with an existing todo. Descope the
  overlapping portion and note the boundary in the plan's _Intent & scope_;
  for a true duplicate of intent, surface it to the human rather than
  silently proceeding or dropping.
- **This premise supersedes** — replaces, broadens, or obsoletes an existing
  todo. Act by that todo's state: a living orchestrator gets a best-effort
  informational message (`telec sessions send`) plus a surface to the human;
  a dormant todo gets surfaced and optionally frozen (`telec todo freeze`,
  reversible); a todo already claimed and building is halted only on
  certainty — below that bar, surface to the human and let it proceed.
- **Undeclared dependency** — this premise needs another todo's deliverable
  never declared as `after`. Record the edge:
  `telec todo update {slug} --after {dep}`.

**Fold the findings into the plan**: overlap into _Intent & scope_, declared
dependencies alongside the edges recorded. This step produces no artifact of
its own — its output is the plan's scope boundary and any recorded `after`
edges.

### 1d. Make no-PRD intent reviewable

For a `change` or `bug`, the plan is the first prepared artifact where intake-
quality scope reasoning can survive. Its _Intent & scope_ section therefore
states:

- the outcome horizon authorized by `input` and, for a bug, sharpened by the
  diagnosed root cause;
- what makes the present outcome coherent in this situation;
- consequential inclusions and exclusions with inspectable premises or named
  assumptions;
- future concerns retained only when they constrain today's design or carry a
  meaningful deferral trigger;
- the observable outcome the plan will later bind to concrete proof.

Apply the same four open shaping questions used for a PRD, but never use the
plan to acquire product authority the input does not carry. A discovered
product outcome beyond the authorized horizon returns to the feature intent
path. For a bug, betterment may make the root-cause removal coherent and
durable; it does not add adjacent hardening or capability.

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

Follow `software-development/procedure/blast-radius-discovery` for every file
this plan intends to change. Ground the plan's change surface and test
adjacency in the verified candidate set it produces — if the procedure reports
the baseline missing or stale, state the gap in the plan and fall back to
manual exploration; never silently skip the step.

### 2d. Reserve the scenario bindings on main

Before drafting the tasks, reserve every feature-spec scenario the plan will bind
so a concurrent prepare cannot bind the same scenario in its own worktree. Read the
current scenario inventory on `main` for each feature spec the plan touches — the
live scenarios via `telec docs get <id>`, and any pending claims via
`telec docs index --target <slug>` and `telec docs get <id> --target <slug>`.

For each scenario the plan will bind:

- **A scenario this todo authors** carries the claim as its own `planned:<slug>`
  block under the feature spec's `### Use cases`; the delivering todo is its binder.
- **An existing live-and-unbound scenario this todo will bind** is claimed by
  wrapping its `#### UC-…` block in a `planned-change:<slug>` that restates the
  scenario unchanged; the delivery fold clears the wrap and the test binding becomes
  the permanent record.
- **A scenario already reserved by another in-flight todo** — enclosed by that todo's
  pending marker on `main` — is not claimed again: reuse it by reference with no
  second binding, or author a distinct scenario. When both todos must author the same
  region, serialize with `telec todo update <this-slug> --after <owning-slug>` so this
  plan drafts against the owner's approved scenarios.

A scenario enclosed by no pending marker and bound by no test is unclaimed and free
to reserve. The plan's declared bindings are what the plan-review reservation check
validates against these on-`main` claims.

### 3. Draft the implementation plan

Apply the plan-specific quality rules from the preparation artifact quality
policy. Structure the plan as an ordered task list. Each task must include:

- **What**: the concrete change (file, function, component).
- **Why**: the rationale for the approach. This prevents the builder from taking shortcuts.
  If the plan says "use adapter pattern" but doesn't say why, the builder may inline the
  logic instead. The "why" is the guard against drift.
- **Verification**: how the builder confirms the task is done (test to write, behavior to

observe, or other proof sanctioned by the project's verification contract).
Each task references the observable outcome or architectural constraint it
proves and names the concrete boundary at which the evidence is gathered.
Tests, live-system probes, browser walks, logs where the project contract
sanctions them, and documentation checks are possible evidence sources—not a
universal hierarchy. Do not prescribe logger/config/native-shape/private-
helper/wiring assertions as substitutes for behavior.

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

### 3c. Bug-scope clamp (kind == bug)

A bug plan delivers exactly two things: the smallest change that removes the
diagnosed root cause (`diagnosis#root-cause`), and the verification that proves
the reported symptom gone. Every task traces to one of those two. A task that
traces to neither — hardening, extra validation layers, defensive defaults,
fallbacks, adjacent refactors, new capability, or any scenario beyond the single
regression scenario below — is a scope violation to strike before the plan is
written, regardless of how prudent it looks. Tracing a task to a scenario or
snippet this same prepare pass authored does not create scope; the `diagnosis`
and the `input` symptom are the only scope authorities for a bug
(`regression-zero-tolerance`: a bug fix touches the bug).

Structural work the investigation surfaced but the fix does not require is
routed out: record it as a deferral or file a new todo for the human's call — it
never rides the fix.

**Regression scenario — the only scenario authoring a bug plan owns.** When the
reproduction test has no bindable scenario in the owning feature spec, author
exactly one pending scenario encoding the reported symptom as
`Given / When / Then` — nothing adjacent, nothing speculative. When a bindable
scenario already exists, the plan binds it and authors nothing. When the fix is
a contract-defining declaration with no bindable scenario
(`software-development/policy/testing`), there is correctly no test and no
scenario.

**Doc reflection for a bug defaults to none — the regression scenario excepted.**
The single regression scenario above is the one snippet addition a bug plan may
carry without further justification. Beyond it, a fix that restores code to the
documented contract has no behavioral delta; record
`doc_impact_none: fix restores documented contract` in step 4b instead of
authoring new contract text. Only when the diagnosed cause is that the
documented contract itself is wrong does any other snippet change enter the
plan — bounded to correcting that contract.

An ambiguous or stale symptom is resolved by the `diagnosis` or escalated to the
human — never by interpretation (Recovery 1 does not apply to a `bug`).

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
- The tests line names every `TQ-*` predicate triggered by the planned test
  delta and the task/evidence that will satisfy it. Every other `TQ-*` ID is
  marked `N/A` with a reason; a generic "tests" line is not coverage.
- Lanes that produce no artifact — `code` Duplication, `paradigm` Component
  reuse, and `simplify` — are ticked against the plan's own `referenced-paths`:
  confirm no task re-derives, mirrors, or re-implements logic an existing cited
  symbol already provides; where shared logic is needed, one task extracts it
  once and the others call it. A task that duplicates an existing symbol instead
  of reusing it is a defect to fix before the plan is complete.

A plan that does not tick every lane will produce review findings that cost more
to fix than they cost to prevent. Ticking a lane never means adding work: for a
scoped change most lanes resolve to `N/A` with a reason, and an `N/A` line is
full compliance. A task added only to mark a lane satisfied is gold-plating —
the defect, not the cure.

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
- For a `bug`, apply the doc-reflection default from step 3c: the single
  regression scenario is the one sanctioned snippet addition; beyond it, a fix
  that restores the documented contract records `doc_impact_none` and authors no
  new contract text.

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
   most likely interpretation. Mark it `[inferred]` in the plan. This applies to
   `feature`/`change` intent only — for a `bug`, ambiguity resolves through the
   `diagnosis` or escalates to the human, never by inference (step 3c).
2. If planning reveals the parent is not atomic, group or split it into children rather than stretching one
   builder plan past the session-size limit.
3. If a file referenced in an upstream artifact does not exist, verify whether it should be
   created or whether the upstream artifact is stale.
