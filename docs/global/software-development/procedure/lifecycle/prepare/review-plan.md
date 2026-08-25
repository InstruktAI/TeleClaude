---
description: 'Plan review phase. Validate implementation-plan against PRD, optional architecture, feature-spec scenarios, policies, DoD gates, and review lane expectations.'
visibility: 'public'
---

# Review Plan — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review-build.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md
- @~/.teleclaude/docs/general/policy/human-involvement-recording.md
- @~/.teleclaude/docs/software-development/policy/quality-predicate-registry.md

## Goal

For no-PRD change and bug work, also review the plan's _Intent & scope_ as the
place where the authorized horizon and its situation-specific shaping become
inspectable. This is preparation-quality review, not a Definition-of-Done lane.

Validate `implementation-plan` against approved PRD, optional architecture,
in-scope feature-spec scenarios, policies, Definition of Done gates, and review lane expectations. The plan must be good enough that a builder can execute
it without guessing and a reviewer finds no surprises.

## Preconditions

- `telec todo artifacts read {slug} implementation-plan` exists.
- The approved intent artifact resolves (see
  `software-development/concept/approved-intent-artifact`): `prd` for a `feature`,
  `input` for a `change`. For a `change`, the absence of a PRD is the intended
  design — do NOT treat it as a defect or raise a finding for it. A `change`
  created via `--plan` has no `input` either: its seeded `implementation-plan`
  carries an _Intent & scope_ section that is the contract to review against, and
  that missing `input` is intended — do NOT block the review or raise a finding for
  it. This exception is specific to `--plan`: a `change` with neither an `input`
  nor a self-contained _Intent & scope_ in its `implementation-plan` has no intent
  basis at all, which remains an intent-artifact defect, not an approvable state.
- For a `bug`, the approved intent is `input` (the reported symptom) and a
  `diagnosis` artifact is present carrying the verified, code-grounded root cause —
  the causal mechanism. The plan must derive its fix and verification from that root
  cause; the diagnosis's absence on a `bug` is a blocker, not an approvable state.

## Steps

First read the software-development principles as listed in the software-development baseline that apply to this work with `telec docs get`.

### 1. Read context

- Apply the artifact-discovery rule from `preparation-artifact-quality`
  (`telec todo artifacts list {slug}`) — read `log` when present, and any
  other present artifact relevant to this review.
- `telec todo artifacts read {slug} implementation-plan` — the artifact under review.
- The approved intent artifact — `prd` for a `feature`, `input` for a `change`, or (for a `--plan` `change` with no `input`) the `implementation-plan`'s _Intent & scope_ — the contract the plan must satisfy.
- `telec todo artifacts read {slug} architecture` — when present.
- `telec todo artifacts read {slug} diagnosis` — when present (a `bug` carries
  this; it holds the verified, code-grounded root cause — the causal mechanism —
  the plan's fix must remove).

- `telec todo artifacts read {slug} input` — the intent authority for change
  and bug work. Artifact presence does not create fallback authority across
  kinds.

- When the creation record shows `entry_point=agent`, `human_involved=true`,
  and a creating session in lineage, resolve that session and inspect its
  transcript. Review the plan against the verified filing basis rather than
  treating the whole agent-authored input, a seeded plan, lineage, or the
  participation flag as evidence of a human decision.

- Relevant codebase files referenced in the plan.
- The code review procedure — to understand what the reviewer will check.
- Apply the domain-context loading rule from the preparation artifact quality
  policy: identify which specs the plan touches and load them before
  validation begins.

### 2. Substantive delivery analysis

Structural coverage ("a task exists for this requirement") is not sufficient.
Produce a `Delivery analysis` section in `plan-review-findings.md` with one
entry per requirement success criterion.

For each success criterion in the approved intent artifact (`prd` for a `feature`; each goal/outcome stated in `input` for a `change`; or, for a `--plan` `change` with no `input`, each goal/outcome stated in the `implementation-plan`'s _Intent & scope_):

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

### 2b. Derivation fidelity and observation-map coverage (behavioral work)

The plan is a derivative of the specs plus code reality; this check judges the
derivation, not just the coverage table. Two passes, both independent of the
plan's own inventory:

1. **Recompute the denominator.** From the spec delta, independently derive the
   use cases the work delivers; from the plan's `referenced-paths` and the
   blast-radius baseline, independently derive the unchanged use cases the
   change places at risk. Compare against the plan's observation map
   (`software-development/spec/observation-map`). A use case in the recomputed
   inventory with no map entry is a **Requirement-Violation** — map coverage
   checked only against the plan's own list is self-consistency dressed as
   coverage.
2. **Judge each predicate's discriminating power.** For each map entry, ask
   what plausible broken behavior would still satisfy the stated opportunity →
   outcome predicate. An entry whose predicate passes on broken behavior —
   wrong correlation fields, an outcome record emitted before the fact it
   claims, a negative behavior mapped to silence instead of an affirmative
   decision record — is a **Critical** finding.

The check also confirms the map honors the contract's shape: lean core fields
only, facing derived from the scenarios rather than restated, defaults not
redundantly overridden.

3. **Judge each opportunity's reachability.** For each entry, ask whether its
   opportunity record would still fire if this change were wrong in the way it
   is most likely to be wrong. An opportunity the change itself can suppress
   makes its entry unfalsifiable, and every entry sharing that anchor falls
   silent together — a **Requirement-Violation** per
   `software-development/spec/observation-map`. Reject equally a pass condition
   that accepts an unresolved item being recorded as finished: a terminal
   outcome requires proof the item is unusable, not proof that something needed
   to process it was absent.

### 2c. Task composition (behavioral work)

Delivery analysis traces each task to its scenario, which cannot see a collision
between two tasks that are each individually correct. Identify every pair of
tasks that changes, or newly calls into, the same function, predicate, record,
or file region. For each pair, read both task bodies together in the order the
plan applies them and state whether each still delivers its referenced scenario
after both land. A pair that does not compose is a **Critical** finding against
the plan, not against either task alone.

Where a task reuses an existing discriminator at a call site that did not
previously use it, verify the plan enumerates the complete set of inputs that
discriminator matches **at the new site**. Its correctness for existing callers
is not evidence, and a blast radius computed over the discriminator's other
callers answers a different question than the one the change raises.

### 3. Scope & size

Validate DOR Gate 2 (Scope & size). The plan must describe one coherent,
bounded delivery. It may span builder sessions only when durable task
boundaries, completed-work evidence, and an unambiguous resumption point make
continuation possible without rediscovery. Apply the splitting heuristics from
the Definition of Ready policy against the grounded implementation surface,
not just the PRD prose or counts of files and tasks.

A size finding must cite a grounded estimate of change volume and complexity
and explain why durable execution boundaries cannot prevent context loss.
File count and task count are never sufficient evidence by themselves.

- Plan spans multiple independently shippable workstreams -> Critical.
- Plan requires multiple phases that could be delivered separately without
  creating a half-working codebase -> Critical.

This is not auto-remediable — scope splits require the drafter, not the
reviewer. If scope fails, mark `needs_work`.

Technical readiness conflicts remain between the preparer and reviewer. Never
route one to the human intent path or ask the human to waive a readiness gate.
Human input is required only when remediation would change the authorized
product outcome, priority, risk appetite, or invoke the explicit emergency
exception. Product expansion continues to use the intent path under §3a.

### 3a. Review intent shaping for change and bug work

When no PRD exists, independently re-run the preparation shaping questions
against `input`, `diagnosis` when present, observable product reality, and the
credible intended state. Compare that reading with the plan's _Intent & scope_.

Verify that:

- the horizon is explicit and no broader than its authority;
- technical derivation is richer than the input where safe, correct delivery
  requires it, while product and business scope remains within its authority;
- consequential inclusions and exclusions explain why they belong here and
  rest on inspectable premises or named assumptions;
- product expansion beyond the input is returned to the feature intent path
  rather than laundered through implementation planning;
- future concerns either constrain today's choice, carry a meaningful deferral
  trigger, or are absent;
- observable outcomes are established before the tasks select concrete proof.

For a bug, the diagnosed root cause and reported symptom clamp the horizon.
Adjacent hardening, capability, or refactoring remains out of scope even when a
domain perspective recommends it.

For a creating-session-audited filing, reject any consequential product or
business detail that is not a direct human statement, faithful restatement,
logically necessary implication, or existing authoritative product constraint.
If another reasonable implementation could satisfy everything the human said
while omitting or varying the detail, it is unspecified; technical prudence
does not make it authorized scope.

A missing or unjustified shaping outcome is a finding under the preparation
artifact quality policy. Do not add an intent-formation lane to the delivery
review catalogue; build and commit review validate delivery against already
approved intent and must not re-litigate it.

### 4. Plan-specific quality

Apply the plan-specific quality rules from the preparation artifact quality
policy:

- Every task has a rationale explaining _why_ this approach. Task with no
  rationale -> Important. Rationale that contradicts codebase patterns or
  loaded domain specs -> Critical.
- Every task names one bounded-context owner and one architectural layer inside
  that owner. A cross-context task names the published contract and separates
  each context's local change. Missing ownership is Important; shared,
  wrong-context, host-derived, or current-placement-derived ownership is
  Critical under `software-development/policy/domain-ownership`.
- Every task has a verification step. Task with no verification -> Important.
  Verification that doesn't prove the task is done -> Important.
- Every prescribed act and its verification is executable by the role and phase
  receiving it, from the execution environment that role runs in — per the
  executability rule in the preparation artifact quality policy, with the
  project's verification contract supplying the location facts. A task that
  schedules an act its assigned role cannot legally or physically perform
  (for example, a live behavioral probe of daemon code assigned to a worktree
  builder) -> Critical. A downstream phase's obligation cited as evidence is
  correct; the same obligation authored as a task for this plan's role is the
  defect.
- No work-phase task takes the doc layer's state as its subject. Authoring or
  editing under `docs/**`, folding pending markers, and confirming or verifying
  whether they are folded are the same violation: the doc layer is authored on
  `main` during prepare and folded by the integrator at delivery -> Critical.
  Judge the task's subject, not its verb — a documentation task phrased as a
  confirmation of marker state passes an executability check and is still
  invalid. Reading doc snippets as implementation input is not this violation;
  binding in-scope feature-spec scenarios and implementing against published
  contracts is required work-phase behavior.
- Referenced file paths are explicit in the plan tasks for grounding review.
  Missing or incomplete -> Important.

### 5. Grounding

Apply the grounding rule from the preparation artifact quality policy. Verify
plan tasks against the domain specs loaded in step 1. Plans that reference
non-existent APIs, wrong schema fields, or incorrect directory structures are
defective — the builder will discover the error at build time, wasting a
session.

Independently re-derive ownership from domain meaning and reason to change.
Do not accept the plan's chosen module, caller, adapter, daemon, scheduler,
storage location, todo boundary, or adjacent pattern as ownership evidence.
Verify every consumer uses the established owner's published contract and does
not duplicate its validation, defaults, recovery, or state transitions.

### 5a. Diagnosis validation (only when a `diagnosis` artifact is present)

Applies only when the todo carries a `diagnosis` artifact (a `bug`). **Skip this
section entirely otherwise** — it does not apply to a `feature` or `change`. This
is the gate that substitutes for a separate diagnosis review: the diagnosis is
scrutinized here, in the same cross-model pass, against the code.

Read `telec todo artifacts read {slug} diagnosis` — the diagnosis carries its
own evidence substrate (the reproduction, the avenues walked, the observations
recorded as re-verifiable facts) alongside its conclusion — and validate:

- **The root cause is a causal mechanism, not a located symptom.** The root-cause
  section must explain _why_ the code produces the wrong behavior, traced to where
  the bad value or state originates, with the evidence chain that grounds it. Two
  distinct failures are both Critical: a root cause that is _ungrounded_ (plausible
  but not tied to code), and one that is _code-grounded but symptom-shaped_ — it
  names where the error surfaces or is thrown, not where it originates. A relocated
  symptom is not a root cause; approving it builds the fix on an unverified premise
  (the exact "delivered yet ineffective" failure this lane exists to stop).
- **The root cause is grounded in the recorded observations.** Investigation and
  conclusion are one act by one author: the `diagnosis` records the observations
  as re-verifiable facts and the causal mechanism those observations ground. Each
  root-cause claim must trace to a recorded observation in the artifact's own
  observation record. A root cause that asserts a mechanism the recorded
  observations do not evidence is Critical: an unsubstantiated conclusion,
  regardless of how plausible it reads.
- **The plan's fix removes the cause, not the symptom.** The plan's fix tasks must
  trace to the diagnosed root cause and eliminate it. A fix that leaves the cause in
  place and handles its consequences — a fallback, default substitution, or
  workaround that masks the symptom — does not address the diagnosis and is Critical
  (the fallback-policy check in §7 still applies on top).
- **A shared-contract cause has a complete implementation denominator.** When the
  diagnosis identifies shared contract knowledge or an invariant with multiple
  implementations, independently verify that its implementation census accounts for
  every producer, entry path, and consumer within the stated system boundary. Then
  verify the plan explains every census entry: reuse the single owner, change it, or
  leave it untouched only on the diagnosis's evidence-backed independence finding.
  A missing sibling implementation is a Critical diagnosis defect; an unexplained
  census entry in the plan is a Critical derivation defect. Reviewing only the plan's
  selected `referenced-paths` is self-consistency, not completeness.
- **The plan's verification proves the cause is gone.** The plan derives its own
  verification from the root cause and credibly proves the reported `input` symptom
  is resolved. Where the bug is hard to reproduce, the plan must carry a concrete
  task to build the functional/e2e coverage that captures it; a hand-waved or absent
  verification is Critical.
- **The plan delivers the fix and nothing else.** Every task traces to removing
  the diagnosed root cause or to the verification that proves the symptom gone.
  A task that traces to neither — hardening, extra validation layers, defensive
  defaults, adjacent refactors, new capability — is Critical (scope violation),
  and tracing it to a scenario or doc snippet this same prepare pass authored
  does not cure it: self-authored artifacts create no scope; the `diagnosis` and
  the `input` symptom are the only scope authorities for a bug.
- **Scenario authoring is bounded to the regression scenario.** A bug plan
  authors at most one pending feature-spec scenario — the one encoding the
  reported symptom that its reproduction test binds (plan-draft step 3c). A
  second authored scenario, or one encoding behavior beyond the reported
  symptom, is Critical. When a bindable scenario already exists, the plan binds
  it and authors none.
- **Doc reflection matches the bug default.** The single regression scenario is
  the one sanctioned snippet addition. Beyond it, a fix that restores code to
  the documented contract carries `doc_impact_none`; other new contract text in
  a bug plan is Critical unless the diagnosed cause is that the documented
  contract itself is wrong, and then only the correction of that contract.

### 6. Review lane anticipation

Apply the DoD-driven review-awareness rule from the preparation artifact
quality policy. Produce a `Lane anticipation` section in
`plan-review-findings.md` that verdicts **every** lane in the review-lanes
catalog (`software-development/policy/definition-of-done-lanes`): one line per
lane, marking it satisfied (naming how), triggered-but-unmet (a finding), or
`N/A` (with reason). A catalog lane with no line is itself an Important finding —
silence is not coverage. For deliverable-producing lanes the line names the
specific artifact the build-review lane will validate and the plan task that
produces it; the key ones to pre-satisfy:

- **Tests**: name the test file and the specific behavior each task observes at
  a meaningful boundary. "Tests" as a category is not compliance. Logger,
  metric/trace, config/model/native-shape, private-helper, constructor-wiring,
  and mock-call-echo assertions are not acceptable deliverables.
  Independently verdict every `TQ-*` predicate: the plan names evidence for
  each triggered ID and gives a reasoned `N/A` for every other ID.
- **Security**: name the validation point, the auth check, and the task that
  adds them.
- **Documentation (hard gate)**: name the doc snippet id, the section, and the
  task that updates it as a pending snippet (`delivered_by`). A `change` is the
  high-risk case — it has no PRD, so its doc reflection lives only here: a
  behavioral delta with neither a snippet update nor an explicit
  `doc_impact_none: <reason>` is a Requirement-Violation (blocking), not a soft
  finding. The reviewer does not approve the plan until the delta is reflected
  or justified. A third disposition is
  `doc_deferred: <holding-slug> — <inline-snippet-reference>#<section>`. Accept
  it only when the named region on `main` is enclosed by that slug's pending
  marker, that slug is already in this todo's `after` set, the inline reference
  points to the held snippet using the form required by
  `general/policy/referencing-doc-snippets`, and replacement text is drafted
  directly beneath the record. The inline reference must populate the plan's
  referenced-snippet provenance, so the holder's fold raises upstream-snippet
  drift and routes the todo back to plan drafting. A `doc_deferred` record that
  fails any condition is a Requirement-Violation; do not accept an undeclared
  collision, a nested marker, or an untracked wait as deferral.
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
- **Process-change authority (hard gate)**: per
  `software-development/policy/process-change-authority`, when any plan task
  implies a behavioral delta to a process-layer contract (lifecycle state
  machines, gate composition, review lanes, lifecycle procedures, todo/state
  semantics), the intent must trace to a human decision. When the
  creating-session fidelity gate applies, that exact decision is evidenced in
  the creating transcript; the creation record only locates the evidence. A
  process-layer delta with no human decision behind it is a
  Requirement-Violation (blocking) — the reviewer does not approve regardless
  of the change's size or its apparent alignment with process intent; that
  judgment is the human's.
  Descriptive doc edits and restoring code to the current contract do not
  trigger this gate.
- **Config surface**: name the config key, the wizard entry, the sample line,
  and the spec section — each with the task that delivers it.
- **Browser-based frontend or web UI**: name the Playwright smoke path and
  the task that records evidence for build and review.
- **Reuse / duplication** (`code` Duplication #4, `paradigm` Component reuse #2,
  `simplify`): these produce no deliverable artifact, so verdict them against the
  plan's `referenced-paths` — does any task re-derive, mirror, or re-implement
  logic an existing cited symbol already provides? A task that duplicates an
  existing symbol instead of extracting it once and reusing it is an Important
  finding (it ships a duplicate code path build-review would otherwise catch a
  cycle later).
- **Domain ownership** (`ownership`): map every changed rule to its domain spec
  and layer, name each cross-context contract, and reject any task that
  implements another context's rule locally. Pattern consistency in adjacent
  code cannot satisfy this lane.

A catalog lane left without a verdict line — or triggered but unmet — is an
Important finding. Record it and mark `needs_work`; the plan drafter owns the
corrective task.

### 6a. Lane execution gate

Before stamping any `plan_review` verdict, the `Lane anticipation` section carries
one verdict line for **every** lane in the review-lanes catalog — the always-on
lanes plus each conditional lane whose trigger this todo meets (`bug-fix` when
`kind == "bug"`, `types` when the plan adds or modifies a type, `doc-first
paradigm` for an ad-hoc commit series) — each marked satisfied,
triggered-but-unmet, or `N/A` with reason. A catalog lane with no line means the
sweep is incomplete: complete the remaining lanes before the verdict. The first
blocking finding does not end the sweep — every lane is verdicted before the
verdict is stamped, and a `needs_work` findings set holds every lane's findings,
not the first found.

### 7. Policy compliance

Check the plan against:

- **Code quality policy**: does the plan prescribe patterns consistent with
  existing codebase conventions?
- **Testing policy**: are test expectations aligned with testing standards?
- **Fallback policy**: does the plan introduce unjustified fallback paths?
  Every fallback must be justified by UX necessity. A fallback rarely names
  itself: "hardening", "graceful degradation", "defensive default", "safety
  net", "best-effort recovery", and "tolerant parsing" are the usual aliases —
  judge the mechanism (a substitute path taken when the primary fails or input
  is bad), not the label.
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

### 8. Preserve reviewer separation

Plan reviewers evaluate; they do not author. A plan reviewer must not edit the
`implementation-plan`, upstream prepare artifacts, documentation snippets, source
<!-- planned-change:review-verdicts-bind-evidence -->
files, tests, config, or generated files. The only writes a plan reviewer owns
are the `plan-review-findings` artifact, when findings exist, and the
`plan_review` verdict stamp.
<!-- change:review-verdicts-bind-evidence -->
files, tests, config, or generated files. The only writes a plan reviewer owns
are the complete `plan-review-findings` artifact for every pass and the
`plan_review` verdict stamp.
<!-- /planned-change:review-verdicts-bind-evidence -->

When the plan has a localized defect, record it as a finding and stamp
`needs_work`. The plan drafter owns the corrective edit and the state machine
routes the todo back through review.

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

- The §6a lane execution gate passes first: the `Lane anticipation` section verdicts every catalog lane. A verdict is not stamped over an incomplete sweep.
- `approve` only when unresolved Critical and unresolved Important findings are both zero.
- `needs_work` when any unresolved Critical or Important finding remains.

<!-- planned-change:review-verdicts-bind-evidence -->
If unresolved findings exist, write them via `telec todo artifacts write {slug} plan-review-findings <content>`
with severity levels (Critical, Important) following the same format as code review
findings, including the policy citation requirement defined in `lifecycle/work/review` §6.

If no unresolved findings remain, do not write a new findings artifact.
<!-- change:review-verdicts-bind-evidence -->
Write the complete pass via `telec todo artifacts write {slug} plan-review-findings <content>`
before stamping, with severity levels (Critical, Important), full lane
anticipation, delivery analysis, the arithmetic verdict, and clean-pass evidence
when no findings remain. Then stamp the verdict; the stamp binds the current
implementation-plan and report digests.
<!-- /planned-change:review-verdicts-bind-evidence -->

### 10. Report

Report:

```
PLAN REVIEW: {slug}

Verdict: [APPROVE | NEEDS WORK]
<!-- planned-change:review-verdicts-bind-evidence -->
Findings artifact: plan-review-findings when NEEDS WORK
<!-- change:review-verdicts-bind-evidence -->
Review artifact: plan-review-findings
<!-- /planned-change:review-verdicts-bind-evidence -->
```

## Outputs

<!-- planned-change:review-verdicts-bind-evidence -->
- Verdict stamped with `telec todo stamp`.
- `telec todo artifacts read {slug} plan-review-findings` if findings exist.
<!-- change:review-verdicts-bind-evidence -->
- A complete `plan-review-findings` report for every pass.
- A verdict stamped with `telec todo stamp`, bound to the current implementation
  plan and report digests.
<!-- /planned-change:review-verdicts-bind-evidence -->

## Recovery

- If unresolved Critical or Important findings remain, mark `needs_work`. The
  state machine will dispatch the plan drafter again with the findings.
- If upstream artifacts themselves are the problem (plan is correct but PRD,
  architecture, or in-scope feature specs are wrong), flag as blocker — the affected
  upstream artifact must be re-reviewed first.
