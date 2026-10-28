---
description: Shared review execution contract for lanes, evidence, citations, severity, verdict arithmetic, and reviewer separation.
---

# Review — Procedure

## Required reads

- @~/.teleclaude/docs/sdlc/policy/definition-of-done-lanes.md
- @~/.teleclaude/docs/sdlc/policy/process-change-authority.md
- @~/.teleclaude/docs/general/policy/human-involvement-recording.md
- @~/.teleclaude/docs/sdlc/policy/quality-predicate-registry.md
- @~/.teleclaude/docs/sdlc/procedure/lifecycle/work/principle-violation-hunt.md
- @~/.teleclaude/docs/sdlc/procedure/lifecycle/work/silent-failure-audit.md
- @~/.teleclaude/docs/sdlc/principle/module-depth.md
- @~/.teleclaude/docs/sdlc/policy/substrate-anchoring.md
- @~/.teleclaude/docs/sdlc/policy/definition-of-done.md
- @~/.teleclaude/docs/sdlc/concept/defect-evidence.md

## Goal

Apply one review contract to every review target. The invoking procedure owns
target resolution, the contextual contract available for scope review, and where
the result is delivered. This procedure owns the review lanes, evidence standard,
citation rules, severity schema, verdict arithmetic, and reviewer separation.

## Preconditions

- The invoking procedure has resolved the exact review target.
- The invoking procedure has named the applicable intent or governing contract.
- The target's complete changed-file surface is available.

## Steps

### 0. Ground the target and reuse relevant assessment evidence

Establish the invoking procedure's target, scope and applicable contracts
independently, then reconcile supplied censuses, classifications, plans and
earlier assessments with that target. Distinguish governing contracts from
recommendations and evidence. Reuse cited source evidence after checking that
it supports the relevant claim at the reviewed revision; an earlier conclusion
or approval alone supplies no proof (`general/principle/grounding`).

Judge whether the reviewed artifact carries its authorized decisions correctly
and preserves the affected requirements. Extend investigation to the dependencies
needed to judge that target; review does not restart an unrelated census of
unchanged material. Record reused evidence and gaps requiring fresh grounding.
The invoking phase's independent derivation and every applicable lane's proof
obligations remain required (`sdlc/policy/definition-of-done-lanes`).

Challenge an assessed decision when the target, its sources or its governing
contract establishes a concrete contradiction, missing requirement or invalid
premise. Apply the finding-validity and convergence rules below; a different
preferred classification or design alone does not reopen a decision.

### 1. Execute every applicable review lane

**Build the lane set.** It has two sources, and every entry in it receives a
disposition: applicable, or `N/A` with its reason.

- The general lanes of `sdlc/policy/definition-of-done-lanes`. The catalog owns
  each lane's focus, severity guidance, trigger conditions, and the Definition
  of Done gate or requirement contract it answers to. Scope and ownership
  always apply. The invoking procedure determines whether the scope lane has a
  requirements contract to trace. The doc-hygiene lane runs whenever a doc
  snippet changes. The doc-first paradigm lane runs for an ad-hoc commit review
  with no prepare artifacts.
- The project's focus points: walk the project's fixed entry points to its
  governing contracts (`sdlc/policy/preparation-artifact-quality`, Governing
  contracts) and take every contract that bears on the target. Each is carried
  in the brief of the general lane it sharpens, or runs as a lane of its own
  when no general lane covers it. An entry point the project lacks is recorded
  as a gap, never as nothing found.

**Run each applicable lane in its own native subagent.** Dispatch the lanes to
the harness's own subagents, in parallel (`general/principle/parallel-work`).
Each starts fresh, with the brief as its only context from you: use the
harness's fresh-subagent form, never a fork of your own conversation. A lane's
brief carries the lane and the address of its catalog section; the exact target
and how to read it; the intent basis this review established, with its source
addresses; the project focus points that bear on the lane, with theirs; the
finding rules of step 4; and the result it returns: findings in the step 4
format, or clean-pass evidence, plus any gap it could not close. The brief
states no preferred verdict. The subagent reads beyond its brief wherever its
lane requires and reports missing context as a gap. Where the harness offers no
native subagents, run the lanes as separate passes yourself.

For the tests lane, independently re-prove every triggered `TQ-*` predicate.
Record evidence for each triggered predicate or a reasoned `N/A`. Evidence
supplied by the author directs attention but never substitutes for review proof.

**Reconcile, then assess the whole.** A lane's result is evidence you judge. A
missing or unsupported lane result is re-run, not filled in by you. Route a
contradiction or a dependency between lanes back to the lanes it concerns. Then
make your own assessment of the whole target: coverage, that every changed file
and every decision the target introduces appears in some lane's evidence; and
fit, that the target as a whole serves the intent. A coverage hole goes back to
a lane; a fit defect you can establish is your own finding under step 4.

Each executed lane produces a findings section, even when it has no findings.
A missing section means the review is incomplete: execute the missing lane
before producing a verdict.

### 2. Apply the quality gates

If the review produces no Important-or-higher findings, include a
`Why No Issues` section containing:

1. Evidence of paradigm-fit verification.
2. Evidence that the applicable contract was met: the prepared success criteria
   for a lifecycle build review, or the resulting behavior against its governing
   contracts for an ad-hoc commit review.
3. Evidence that copy-paste duplication was checked.
4. Evidence that security was reviewed.

For user-facing changes, record the observable behavior verified and the
evidence that confirms it. For browser-based changes, follow the applicable
Playwright smoke path when the environment allows it and record the observation.
When lifecycle build evidence exists, inspect the builder's recorded smoke path
as well. An unverified user-facing requirement is a finding.

### 3. Preserve reviewer separation

Reviewers evaluate; they do not author fixes. A reviewer does not edit source,
tests, documentation, configuration, generated files, or preparation artifacts.
The only writes a reviewer owns are the result surfaces explicitly named by the
invoking procedure.

Missing test coverage is reported, not patched by the reviewer. A finding that
shows prepared intent or a plan is wrong returns through the invoking
procedure's correction path; the reviewer never edits the prepared artifact.

### 4. Cite and classify every finding

Review attempts to falsify the target's claims against its governing contract.
It does not brainstorm risks, maximize findings, improve the design, or
prescribe speculative defenses.

The review result carries findings, investigation leads, and the verdict. It
names no owner, destination, or decision for another party: what follows a
review is the dispatching orchestrator's (§6, `general/procedure/orchestration`).

A finding is valid only when all four hold:

1. it cites the specific policy, Definition of Done line, principle, or spec it
   violates — a principle is a citeable clause;
2. it establishes, from current authoritative sources and the reviewed
   artifact, that the cited clause applies here — including that no more
   specific contract on the same subject decides the case otherwise, such as a
   project policy that settles what a general spec leaves open
   (`general/policy/conflict-resolution`), or, for a bug, the bug-fix lane's
   scope authority (`sdlc/policy/definition-of-done-lanes`);
3. it explains the contradiction causally — what the target introduces and why
   that conflicts with the clause. Every factual premise the contradiction rests
   on is shown by an observation of current substrate — the file, the command
   output — never asserted (`general/principle/grounding`). A condition the
   target leaves as it was, or restores to its previously delivered behavior,
   is not introduced by the target;
4. it states the closure condition as a state of the target within the frozen
   scope, without prescribing implementation. A closure that waits on a
   decision or an authorization names no state of the target.

A finding that claims a defect establishes, from current sources, that a
reachable condition triggers it (`sdlc/concept/defect-evidence`); a defect claim
on an unreachable condition is an investigation lead.

An observation missing any one of these is an **investigation lead**, not a
finding: it cannot block, never enters remediation, requires no producer
response, and cannot enlarge current work. Report it under its own heading in
the review result; the session that dispatched the review decides what follows
from it. A lead that silently becomes remediation is the failure this contract
exists to prevent.
Absence of a specific prohibition is never a finding's basis when a principle
covers the case; "the design feels wrong" is not a finding under any citation.

An observation without a causal relationship to the reviewed target is outside
the review, not an investigation lead.

Use this format:

```text
Severity — Policy: <citation>
Location: <file:line>
Violation: <one sentence stating what the target does that the cited rule forbids>
Evidence: <each factual premise of the violation, with the observation that shows it>
Closure: <the state of the target that resolves it, within the frozen scope, stated without prescribing implementation>
```

Use exactly three severity tiers:

- **Requirement-Violation**: a stated success criterion is absent, narrowed,
  partially delivered, or weakly verified.
- **Critical**: a bug, fallback violation, security issue, significant
  unrequested behavior, or weakened prepared assertion.
- **Important**: scope gold-plating, missing non-requirement coverage, paradigm
  or policy violation, or maintainability violation of a cited rule.

There is no fourth tier. Do not invent non-blocking, accepted, deferred,
suggestion, nit, or polish categories.

### 5. Derive the verdict arithmetically

- Any unresolved Requirement-Violation, Critical, or Important finding yields
  `REQUEST CHANGES`.
- Zero unresolved findings yields `APPROVE`.

Overall quality, prior patterns, merge state, review-round count, or the absence
of a fix loop never overrides this arithmetic. A count decreases only when
evidence establishes that the finding is invalid or resolved.

Write the complete structured report to the review artifact named by the
invoking procedure on every pass, including a clean pass, before stamping the
verdict. The report is the durable audit record for that pass: it includes every
executed lane, the arithmetic verdict, and the `Why No Issues` evidence when
required. The verdict stamp binds the current review target digest and the
current report digest; neither the transcript nor an earlier report substitutes
for that artifact.

### 6. Bound the convergence

Scope is frozen before review begins: the authorized intent, and the
independently reviewed architecture or plan where one exists, form the fixed
denominator every finding is judged against. When the target is an
implementation, the plan's file placement, helper names, and decomposition are
not part of that denominator (`sdlc/policy/preparation-artifact-quality`).
Remediation closes valid findings
within that scope; a valid omission finding may add material, but scope growth
is semantic and line count proves nothing either way. A remediation changes the
target, not its authority; every addition remains answerable to the same frozen
denominator.

The first review of a target is one complete discovery pass over the frozen
digest. A remediation review closes existing findings and inspects the
remediation delta. A new finding on a remediation review is admissible only
when it is remediation-induced, or newly observable because the target changed.
A finding that was observable in the discovery pass and is raised later is the
reviewer's incompleteness: it pauses continuation for reassessment and is not
appended to the producer's work. The finding and the current verdict are
preserved. A replacement reviewer, when reassessment calls for one, derives
independently before reconciling the existing findings and dispositions, and
resets neither the frozen scope nor the review history.

A further finding in previously remediated work is compared with the earlier
finding, its disposition, and the change that answered it. Repeated failure to
establish the same invariant, or a remediation chain that introduces another
defect while leaving its premise unresolved, requires re-derivation of the
affected unit before another pass: a remediation applied only where a finding
points converges one leftover per pass
(`sdlc/policy/preparation-artifact-quality`). The re-derivation begins at the
criterion the failing invariant serves: it is traced to the authorized intent
before the mechanism is rebuilt, and a criterion the intent does not carry is
taken out rather than defended by further mechanism. A second edit to the same
region establishes neither by itself.

Review passes are counted within a review cycle. A valid substantive-drift stamp
ends the current cycle for every review target it invalidates and starts a new
cycle for each replacement target, counted from zero; phase-wide counters,
reports, and verdict evidence remain cumulative. Target or report rewrites
without a substantive stamp remain inside the current cycle and reset nothing.
This keeps the admitted-pass denominator grounded in the target it governs
(`general/principle/grounding`).

The v9-to-cycle migration has one explicit initialization rule for legacy
prepare-review state that cannot carry a cycle boundary it predates. When the
current verdict and evidence bindings are empty, a retained report exists, and
the current target was written after that report, the migration records the
cumulative round total as the new cycle's offset, once, during upcycle.
Cycle-local admitted passes are that total minus the offset, so the new cycle
counts from zero while cumulative history is unchanged. Other legacy shapes keep
a zero offset. This keeps the reported cycle-local count describing the target it
governs rather than inheriting totals from a boundary that was never persisted
(`general/principle/grounding`).

When a review cycle reaches its configured threshold, the count is reported
and nothing is refused. The report names the phase, the passes admitted, and the
threshold, and points at this continuation contract. It is emitted once, on the
pass that crosses the threshold, and not again; the count keeps rendering
afterwards. The count summons no one.

The phase orchestrator owns continuation, as it owns the loop's lifecycle
execution (`general/procedure/orchestration`); the reviewer keeps verdict
authority, and the producer keeps disposition and implementation authority.
Before requesting another pass, the orchestrator establishes from the current
delta and findings what remains unresolved and why the next act can resolve it
within the frozen scope. Either party may halt continuation by identifying a
grounded defect in continuing; the orchestrator resolves or routes that defect
before requesting another pass.

When continuation stops, the phase orchestrator records the grounded cause and
routes the next contribution under the invoking phase's correction procedure.
The target returns to drafting only when the evidence requires re-deriving a
prepared artifact. Reviewer incompleteness stays a review correction; an
implementation defect within the approved contract stays with the producer. The
findings and the current verdict are preserved. An unresolved contract dispute
returns the target to the phase that owns that contract; a review loop never
carries it to the human, and neither does the round count.

Neither elapsed rounds nor stopping authorizes approval, scope growth, or a
weakened finding.

Findings and their dispositions persist with the reviewed work. A fresh reviewer
derives independently before reading prior dispositions, then reconciles; a
continuing reviewer works from its own ledger. A disposition reopens only on
changed substrate or material new evidence; re-filing it otherwise is reviewer
incompleteness.

## Outputs

- A complete, current review artifact covering every applicable lane, even when
  the pass is clean.
- An arithmetic `APPROVE` or `REQUEST CHANGES` verdict bound to that artifact
  and the reviewed target.

### Report format

```text
REVIEW COMPLETE: <target>

Requirement-Violations:
- <finding with citation>

Critical:
- <finding with citation>

Important:
- <finding with citation>

Verdict: APPROVE | REQUEST CHANGES
```

## Recovery

If the target, applicable contract, or required evidence cannot be resolved,
report the blocker to the invoking procedure and stop. Do not narrow the review
to what happens to be available.
