---
description: 'Plan review phase. Validate implementation-plan against PRD, optional architecture, feature-spec scenarios, policies, DoD gates, and review lane expectations.'
visibility: 'public'
---

# Review Plan — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md

## Goal

Validate `implementation-plan` against approved PRD, optional architecture,
in-scope feature-spec scenarios, policies, Definition of Done gates, and review lane expectations. The plan must be good enough that a builder can execute
it without guessing and a reviewer finds no surprises.

## Preconditions

- `telec todo artifacts read {slug} implementation-plan` exists.
- The approved intent artifact exists (see
  `software-development/concept/approved-intent-artifact`): `prd` for a `feature`,
  `input` for a `change`. For a `change`, the absence of a PRD is the intended
  design — do NOT treat it as a defect or raise a finding for it.
- For a `bug`, the approved intent is `input` (the reported symptom) and a
  `diagnosis` artifact is present carrying the verified, code-grounded root cause —
  the causal mechanism. The plan must derive its fix and verification from that root
  cause; the diagnosis's absence on a `bug` is a blocker, not an approvable state.

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

### 1. Read context

- `telec todo artifacts read {slug} implementation-plan` — the artifact under review.
- The approved intent artifact — `prd` for a `feature`, `input` for a `change` — the contract the plan must satisfy.
- `telec todo artifacts read {slug} architecture` — when present.
- `telec todo artifacts read {slug} diagnosis` — when present (a `bug` carries
  this; it holds the verified, code-grounded root cause — the causal mechanism —
  the plan's fix must remove).
- `telec todo artifacts read {slug} input` — compatibility fallback only when PRD is absent.
- Relevant codebase files referenced in the plan.
- The code review procedure — to understand what the reviewer will check.
- Apply the domain-context loading rule from the preparation artifact quality
  policy: identify which specs the plan touches and load them before
  validation begins.

### 2. Substantive delivery analysis

Structural coverage ("a task exists for this requirement") is not sufficient.
Produce a `Delivery analysis` section in `plan-review-findings.md` with one
entry per requirement success criterion.

For each success criterion in the approved intent artifact (`prd` for a `feature`, or each goal/outcome stated in `input` for a `change`):

1. Reference the criterion by `@prd#section-header` — do not copy its text.
2. Reference the task body (or multiple tasks' bodies) that delivers it by
   `@implementation-plan#task-header` — do not copy task text.
3. State, in one sentence, how the referenced task delivers the referenced
   criterion — naming the specific file edits, config changes, test
   additions, or other concrete deliverables the task prescribes.

If any upstream criterion or task lacks a stable markdown header to point at,
that is itself a finding: the upstream author must add a header so the
reference contract works. Do not work around it by quoting prose.

Findings:

- Criterion not addressed by any task -> **Requirement-Violation** (the
  highest severity; see `work/review` for the severity schema). A task bearing
  the requirement's name whose body narrows the criterion is a
  Requirement-Violation regardless of whether the task exists.
- Task references criteria it does not deliver -> Critical.
- Orphan task (no PRD criterion, architecture constraint, or feature-spec scenario) -> Important (gold-plating risk).
- Task contradicts PRD, architecture, or in-scope feature-spec scenarios -> Critical.
- Task copy-pastes upstream text instead of referencing it by
  `@artifact#section-header` -> Important (per
  `policy/preparation-artifact-quality` §Referencing upstream intent).

The reviewer cannot approve the plan while any criterion lacks a Delivery
analysis entry that names concrete deliverables.

### 3. Scope & size

Validate DOR Gate 2 (Scope & size). The plan must fit one builder session.
Apply the splitting heuristics from the Definition of Ready policy against
the plan's actual task list, not just the PRD prose.

- Plan spans multiple independently shippable workstreams -> Critical.
- Plan requires multiple phases that could be delivered separately without
  creating a half-working codebase -> Critical.

This is not auto-remediable — scope splits require the drafter, not the
reviewer. If scope fails, mark `needs_work`.

### 4. Plan-specific quality

Apply the plan-specific quality rules from the preparation artifact quality
policy:

- Every task has a rationale explaining _why_ this approach. Task with no
  rationale -> Important. Rationale that contradicts codebase patterns or
  loaded domain specs -> Critical.
- Every task has a verification step. Task with no verification -> Important.
  Verification that doesn't prove the task is done -> Important.
- Referenced file paths are explicit in the plan tasks for grounding review.
  Missing or incomplete -> Important.

### 5. Grounding

Apply the grounding rule from the preparation artifact quality policy. Verify
plan tasks against the domain specs loaded in step 1. Plans that reference
non-existent APIs, wrong schema fields, or incorrect directory structures are
defective — the builder will discover the error at build time, wasting a
session.

### 5a. Diagnosis validation (only when a `diagnosis` artifact is present)

Applies only when the todo carries a `diagnosis` artifact (a `bug`). **Skip this
section entirely otherwise** — it does not apply to a `feature` or `change`. This
is the gate that substitutes for a separate diagnosis review: the diagnosis is
scrutinized here, in the same cross-model pass, against the code.

Read `telec todo artifacts read {slug} investigation` and
`telec todo artifacts read {slug} diagnosis` and validate:

- **The root cause is a causal mechanism, not a located symptom.** The root-cause
  section must explain _why_ the code produces the wrong behavior, traced to where
  the bad value or state originates, with the evidence chain that grounds it. Two
  distinct failures are both Critical: a root cause that is _ungrounded_ (plausible
  but not tied to code), and one that is _code-grounded but symptom-shaped_ — it
  names where the error surfaces or is thrown, not where it originates. A relocated
  symptom is not a root cause; approving it builds the fix on an unverified premise
  (the exact "delivered yet ineffective" failure this lane exists to stop).
- **The root cause is grounded in the investigation.** The `diagnosis` is a thin
  conclusion over the `investigation` substrate; each root-cause claim must trace to
  a recorded observation there. A root cause that asserts a mechanism the
  investigation does not evidence — or a `diagnosis` written with no investigation to
  cite — is Critical: an unsubstantiated conclusion, regardless of how plausible it
  reads.
- **The plan's fix removes the cause, not the symptom.** The plan's fix tasks must
  trace to the diagnosed root cause and eliminate it. A fix that leaves the cause in
  place and handles its consequences — a fallback, default substitution, or
  workaround that masks the symptom — does not address the diagnosis and is Critical
  (the fallback-policy check in §7 still applies on top).
- **The plan's verification proves the cause is gone.** The plan derives its own
  verification from the root cause and credibly proves the reported `input` symptom
  is resolved. Where the bug is hard to reproduce, the plan must carry a concrete
  task to build the functional/e2e coverage that captures it; a hand-waved or absent
  verification is Critical.

### 6. Review lane anticipation

Apply the DoD-driven review-awareness rule from the preparation artifact
quality policy. Produce a `Lane anticipation` section in
`plan-review-findings.md` with one entry per requirement, per triggered lane.

The authoritative lane set is the review-lanes catalog
(`software-development/policy/definition-of-done-lanes`) — anticipate every lane
it lists that this work triggers. Each entry names the specific artifact the
build-review lane will validate and the plan task that produces it; the key lanes
to pre-satisfy:

- **Tests**: name the test file and the specific behavior each task observes at
  a meaningful boundary. "Tests" as a category is not compliance. Logger,
  metric/trace, config/model/native-shape, private-helper, constructor-wiring,
  and mock-call-echo assertions are not acceptable deliverables.
- **Security**: name the validation point, the auth check, and the task that
  adds them.
- **Documentation (hard gate)**: name the doc snippet id, the section, and the
  task that updates it as a pending snippet (`delivered_by`). A `change` is the
  high-risk case — it has no PRD, so its doc reflection lives only here: a
  behavioral delta with neither a snippet update nor an explicit
  `doc_impact_none: <reason>` is a Requirement-Violation (blocking), not a soft
  finding. The reviewer does not approve the plan until the delta is reflected
  or justified.
- **ADR discipline (hard gate)**: any ADR the plan schedules, or that prepare
  authored on `main`, is held to `general/policy/adr-discipline` and
  `general/procedure/adr-authoring`. It must record one real, contestable
  architectural fork — reject design or current-state cast as an ADR, a
  non-decision (cleanup or alignment that carries no fork — the default is none),
  work/slugs in the body, or an ADR pre-authored for undelivered work. A
  scheduled or authored ADR that fails this bar is a Requirement-Violation
  (blocking); the reviewer does not approve until it is dropped or corrected.
  This bar is the plan reviewer's: the build reviewer never assesses ADRs, because
  the doc layer is authored on `main` during prepare, never in the worktree.
- **Config surface**: name the config key, the wizard entry, the sample line,
  and the spec section — each with the task that delivers it.
- **Browser-based frontend or web UI**: name the Playwright smoke path and
  the task that records evidence for build and review.

A lane triggered by any requirement but not addressed by a named deliverable
per that requirement is an Important finding. Auto-remediate by inserting the
missing task when the gap is localized; otherwise mark `needs_work`.

### 7. Policy compliance

Check the plan against:

- **Code quality policy**: does the plan prescribe patterns consistent with
  existing codebase conventions?
- **Testing policy**: are test expectations aligned with testing standards?
- **Fallback policy**: does the plan introduce unjustified fallback paths?
  Every fallback must be justified by UX necessity.
- **Intelligence boundaries** (per `principle/intelligence-boundaries`):
  reject plan tasks that prescribe regex / classifier / scorer / auto-fixer
  code on free-text content. Patterns: hardcoded vocabulary tables;
  word-count thresholds for "is this meaningful?"; `is_*` / `should_*`
  predicates on natural language; auto-rewriters that edit agent artifacts
  to match structural rubrics. The defining test: would the task be
  unnecessary if the agent's briefing said the right thing? If yes, the
  task belongs in the briefing, not the plan. Critical — these accumulate
  silently and corrupt the codebase faster than coupling violations
  because every implementation looks "well-typed and narrow."

Policy violations are Critical findings.

### 8. Auto-remediate localized findings

Default behavior is to act in place. If a finding is localized, high-confidence,
and does not change intent, the reviewer should fix the plan directly in this
same pass instead of handing it back.

Localized means all of the following are true:

- No requirement intent changes.
- No new architectural decision is introduced.
- Scope stays within the reviewed planning artifacts and related grounding metadata.
- The reviewer can fully validate the fix from current context.

Not allowed — route via `needs_work` instead:

- Adding new tasks not traceable to PRD, architecture, or feature-spec scenarios.
- Changing scope or splitting the todo.
- Inventing architectural decisions not grounded in PRD, architecture, or codebase.

### 8a. Forbidden reviewer moves

The schema has two tiers for plan review: Critical, Important. There is no
fourth tier. There is no Suggestion bucket.

- **Inventing a fourth tier.** No "Suggestion", "nit", "polish",
  "non-blocking", or "follow-up" tier exists.
- **Pre-existing-pattern dodge.** The reviewer evaluates the plan's
  resulting state, not how it differs from a prior version. If the current
  text violates a cited rule, the finding stands.
- **Uncited findings.** If you cannot name the rule, you have an opinion,
  not a finding. Drop it.
- **Severity-softening to reach approve.** Words like "minor", "cosmetic",
  or "nice to have" are demotion language. Stop, re-cite, re-evaluate.

When the dispatch comes with a digest-mismatch header (the message includes
a `telec todo artifacts diff` command with old and new digests), the plan
changed since the last approval. Run the diff command to see what changed
and re-validate against the requirements and specs.

### 9. Write verdict

Stamp the review verdict:

```bash
telec todo stamp {slug} --verdict approve --phase plan_review
# or
telec todo stamp {slug} --verdict needs_work --phase plan_review
```

Verdict rules:

- `approve` only when unresolved Critical and unresolved Important findings are both zero.
- `needs_work` when any unresolved Critical or Important finding remains.

If unresolved findings exist, write them via `telec todo artifacts write {slug} plan-review-findings <content>`
with severity levels (Critical, Important) following the same format as code review
findings, including the policy citation requirement defined in `lifecycle/work/review` §6.

If no unresolved findings remain, do not write a new findings artifact.

### 10. Commit and report

Commit all files in the worktree. Report:

```
PLAN REVIEW: {slug}

Verdict: [APPROVE | NEEDS WORK]
Findings artifact: plan-review-findings when NEEDS WORK
```

## Outputs

- Verdict stamped with `telec todo stamp`.
- `telec todo artifacts read {slug} plan-review-findings` if findings exist.
- Commit containing review artifacts.

## Recovery

- If unresolved Critical or Important findings remain after auto-remediation,
  mark `needs_work`. The state machine will dispatch the plan drafter again
  with the findings.
- If upstream artifacts themselves are the problem (plan is correct but PRD,
  architecture, or in-scope feature specs are wrong), flag as blocker — the affected
  upstream artifact must be re-reviewed first.
