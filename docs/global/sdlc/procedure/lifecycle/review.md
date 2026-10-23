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

<!-- planned:issue-128 -->

### Sequential review isolation

The producer completes a coherent target before technical review begins. The
reviewer establishes intent, governing policies, applicable language/tooling
rules and relevant existing solutions independently, before reading the
producer's rationale. A proposed contract or an earlier approval does not
supply its own policy exception (`general/principle/grounding`,
`general/policy/conflict-resolution`). Preparation review applies the policies
of the proposed implementation as well as artifact-quality and readiness rules;
waiting for code to exist would approve a design that its language forbids.

The phase driver coordinates a producer child and a dedicated reviewer child.
The reviewer has no delivery responsibility and has neither authored the target
nor chosen, directed or negotiated its solution. The driver's stake in delivery
does not qualify it as that reviewer. The review brief supplies the completed
target, authorized intent, governing source pointers and factual evidence, not
the producer's conversation or a preferred verdict. The reviewer grounds those
sources independently before reconciling the producer's recorded rationale
(`general/policy/leadership`, Adversarial peer invocation).

Review follows each completed coherent commit and, separately, the completed
whole delivery. A commit is one intelligible change with a stated purpose,
boundaries and checks; it need not implement the whole feature. Review tests
the obligations that apply at that step and preserves planned later work as
later work. An enabled broken path or policy violation is a present defect;
an explicitly deferred feature step is not one merely because it is unfinished.
The machine knows source identity, not semantic completeness. The producer's
handoff identifies the unit, and the reviewer judges whether it is reviewable.
An incoherent unit returns for coherent completion, not speculative expansion.

Authoring and review alternate. The producer hands off the exact revision and
stops editing it; the driver dispatches or continues the reviewer through normal
session messages, without a direct conversation link between producer and
reviewer. The reviewer returns one complete report and verdict to the driver.
Only then does the driver deliver that verdict to the producer for independent
remediation or evidence-backed rejection. Findings are not streamed during
review, and the next unit starts after the current unit's blocking findings are
resolved and its verdict is recorded. The same reviewer continues subsequent
units and final review while its independence holds. Final review covers the
resulting whole delivery and cross-unit interactions; per-commit approvals do
not replace it. The producer retains responsibility for the smallest compliant
remedy, and a finding's closure condition conveys no implementation or scope authority
(`sdlc/policy/preparation-artifact-quality`, Evidence does not reallocate ownership).

The driver arbitrates continuation, scope and procedure: it can require a
missing citation, distinguish an unmet obligation from a preference, and return
an unsupported finding for correction. It records the independent report with
its reviewer and target; it cannot change the verdict or waive a valid policy
violation to advance delivery. A reply is not a resolution until the reviewer
has evaluated it and recorded the resulting finding status.

A genuine unresolved dispute about a finding's validity, applicability or scope
is assessed by one isolated adjudicator who did not design the target or form
the disputed finding. The invoking coordinator supplies the exact target,
authoritative intent and sources; the adjudicator derives the governing
obligations before examining both recorded positions. Its result determines
which cited obligation and evidence hold, not a new implementation. The
responsible reviewer incorporates that evidence and records the resulting
finding status and arithmetic verdict. A missing contract decision returns to
its owner. Scope, prior findings and review history survive; an adjudicator's
presence supplies no approval and no permission to weaken a valid finding
(`general/policy/leadership`, Uncertainty stays with its owner).
<!-- /planned:issue-128 -->

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

Run every applicable lane defined in
`sdlc/policy/definition-of-done-lanes`. The catalog owns each
lane's focus, severity guidance, and the Definition of Done gate or requirement
contract it answers to.

The invoking procedure determines whether the scope lane has a requirements
contract to trace. All other lanes run according to the catalog's trigger
conditions. The doc-hygiene lane runs whenever a doc snippet changes. The
doc-first paradigm lane runs for an ad-hoc commit review with no prepare
artifacts.

For the tests lane, independently re-prove every triggered `TQ-*` predicate.
Record evidence for each triggered predicate or a reasoned `N/A`. Evidence
supplied by the author directs attention but never substitutes for review proof.

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
review is the dispatching orchestrator's (§6, `general/concept/orchestrator`).

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

<!-- planned-change:issue-128 -->

Write the complete structured report to the review artifact named by the
invoking procedure on every pass, including a clean pass, before stamping the
verdict. The report is the durable audit record for that pass: it includes every
executed lane, the arithmetic verdict, and the `Why No Issues` evidence when
required. The verdict stamp binds the current review target digest and the
current report digest; neither the transcript nor an earlier report substitutes
for that artifact.

<!-- change:issue-128 -->

Deliver the complete structured report on every pass, including a clean pass,
before the verdict is recorded. The report is the audit record for that pass: it
includes every executed lane, the arithmetic verdict, and the `Why No Issues`
evidence when required. The invoking procedure names where the report goes and
how its verdict is recorded and bound: a commit review prints the report and
stamps the verdict on the reviewed commits
(`sdlc/procedure/lifecycle/work/review-commits`); the work driver's lane report
is the text of its stamp at the reviewed commit
(`sdlc/procedure/lifecycle/work/overview-v2`). Neither the transcript nor an
earlier report substitutes for the current pass's report.

<!-- /planned-change:issue-128 -->

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
(`sdlc/policy/preparation-artifact-quality`). A second edit to the same region
establishes neither by itself.

<!-- planned-change:issue-128 -->

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
execution (`general/concept/orchestrator`); the reviewer keeps verdict
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

<!-- change:issue-128 -->

The phase orchestrator owns continuation, as it owns the loop's lifecycle
execution (`general/concept/orchestrator`); the reviewer keeps verdict
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
carries it to the human.

<!-- /planned-change:issue-128 -->

Neither elapsed rounds nor stopping authorizes approval, scope growth, or a
weakened finding.

Findings and their dispositions persist with the reviewed work. A fresh reviewer
derives independently before reading prior dispositions, then reconciles; a
continuing reviewer works from its own ledger. A disposition reopens only on
changed substrate or material new evidence; re-filing it otherwise is reviewer
incompleteness.

## Outputs

<!-- planned-change:issue-128 -->

- A complete, current review artifact covering every applicable lane, even when
  the pass is clean.
- An arithmetic `APPROVE` or `REQUEST CHANGES` verdict bound to that artifact
  and the reviewed target.

<!-- change:issue-128 -->

- A complete report of the current pass covering every applicable lane, even
  when the pass is clean, delivered where the invoking procedure names.
- An arithmetic `APPROVE` or `REQUEST CHANGES` verdict, recorded and bound to
  the reviewed target as the invoking procedure records it.

<!-- /planned-change:issue-128 -->

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
