---
description: 'Quality rules for preparation artifacts (PRD, architecture, and plans). Shared by creators and reviewers.'
visibility: 'public'
---

# Preparation Artifact Quality — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/domain-ownership.md

## Rules

### Referencing upstream intent

Downstream artifacts reference upstream intent — they do not copy it.
Architecture, plans, and reviews point at the upstream source by
artifact path and markdown section header. The reference IS the contract; the
upstream artifact is the single source of truth for its own text.

- Reference form: `@{artifact-name}#{section-header}` (e.g.
  `@prd#success-criteria`, `@architecture#state-ownership`,
  `@implementation-plan#task-3-rename-with-dependents`). When pointing at a whole
  artifact rather than a section, drop the `#`-suffix.
- Markdown headers in upstream artifacts are the anchor surface. Authors of
  referenced artifacts (PRD, architecture, implementation-plan) MUST give
  each addressable unit — every success criterion, every architectural
  decision, every plan task — its own stable header so downstream artifacts
  can point at it.
- Verbatim copy-paste, block-quoting, embedding, or paraphrasing of upstream
  text into the downstream artifact is defective. The source text lives in
  one place; duplicating it creates drift and turns mismatches into a
  judgment call.

When the reviewer or builder needs the upstream text, they read the cited
artifact at the cited header. Tooling (e.g. `telec todo artifacts read`)
makes the dereference cheap.

### Domain-context loading

Before creating or reviewing a preparation artifact, identify which domain
specs the artifact touches and load them.

- Read the artifact (or input, if creating) and identify the domains it
  affects: documentation system, CLI surface, config surface, messaging,
  session infrastructure, etc.
- Run a filtered `telec docs index --areas spec` (add `--domains <domain>` to narrow further)
  and load the relevant specs via `telec docs get`.
- Examples: work involving doc snippets → load the snippet authoring schema.
  Work involving CLI changes → load the CLI surface spec. Work involving
  config → load the teleclaude-config spec.

Domain specs are the ground truth. Grounding, leakage detection, and
review-awareness cannot be evaluated without them.

### Artifact discovery

Before reading artifacts for context, discover what actually exists.

- Run `telec todo artifacts list {slug}` first. Read whichever present
  artifacts are relevant to this phase's own purpose.
- `log`, when present, is always relevant regardless of phase or kind — the
  one artifact that carries factual FYI context (a related todo noticed, a
  record correction owed) no other artifact captures. Read it whenever it
  exists.
- Which other present artifacts matter, and why, is still phase-specific
  judgment — a procedure names that judgment locally (e.g., "`diagnosis`
  holds the verified root cause and nothing more"). Only the discovery
  mechanic is shared; the relevance judgment is not.

### Intent shaping

Preparation determines the work's authorized horizon before enriching or
constraining it. The horizon is inferred from the source intent and the
situation, then stated in the artifact the human or reviewer will consume; it
is not selected from a hard kind lookup.

Intent shaping asks four open questions:

1. What outcome is this work authorized to change?
2. Given that horizon, what would improve the target beyond the input alone,
   and why in this situation?
3. Against the current system and credible intended state, what must change for
   the better target to survive?
4. How is the world observably different when the outcome is achieved?

The questions invite domain intelligence; they do not prescribe answer
categories. Route attention through whichever perspectives the situation
earns, without a standing panel, framework sequence, coverage matrix, or
not-applicable catalogue.

Every consequential inclusion and exclusion explains why it belongs here. Its
reason rests on an inspectable premise or names the assumption that remains.
Inference beyond the evidence is permitted when the additional premise stays
visible; evidence, inference, and human-ratified intent never collapse into one
authority claim.

Target formation uses the human's intent, observable product reality, scale and
trajectory, credible intended state, and applicable domain knowledge. Internal
module shapes and implementation conventions enter when the target is
reconciled with the system; they do not silently bound what the product is
allowed to become.

The accepted artifact carries the choosing reasoning in its natural sections:
the authorized horizon, why consequential scope belongs here, exclusions that
bound the outcome, assumptions, meaningful deferrals and their triggers, and
observable outcomes. It carries no transcript appendix or requirement-by-
requirement metadata form. Independent review re-runs the questions to probe
for omissions and checks the reasons that survived into the artifact.

### Grounding

Preparation grounds two different questions without merging them:

- **State truth:** what users can do now, what the running code and current
  contracts implement, and what approved pending work credibly intends.
- **Solution truth:** how this class of problem is understood in the relevant
  domain, including authoritative prior art when the situation warrants it.

Current and intended state remain distinguishable. Prior art may originate a
proposal but holds no authority over product intent. An inference may extend
the evidence only when its additional premise is visible as an assumption.

Existing APIs, patterns, conventions, and scaffolds are assessable defaults.
Use them when they serve the approved target. Departures are permitted when the
artifact names the conflict and explains why the target requires adaptation,
replacement, retirement, or a genuinely different shape. Conformance to the
current implementation is not correctness by itself, and novelty is not value
by itself.

Verify state claims against code and loaded domain specs. Verify solution
claims against authoritative external evidence when they matter. A grounded
artifact neither invents a mechanism from memory nor lets the present codebase
veto a better, approved target without examination.

### Input artifact quality

The `input` artifact is the human's intent dropped into the workflow before
intake. It describes WHAT the human wants and WHY. It does NOT prescribe
WHERE durable docs land — that's intake's classification job
(see `software-development/procedure/lifecycle/prepare/intake` step 1.5).

Concrete signals of leakage in `input` — each is a defect:

- **Naming specific feature-spec, domain-spec, or design-doc paths.** Inputs
  that say "author `docs/project/spec/feature/<x>/<y>.md`" are prescribing
  doc routing the author may have classified wrong. Especially toxic when
  the path contains the todo slug, because the intake worker takes the
  string literally and creates a slug-named non-feature snippet — exactly
  the failure that
  `documentation-first-development` section 8a/8b exists to prevent.
- **Naming specific implementation paths or file locations.** Same leakage
  shape as PRD-quality rules below; input is upstream of PRD, so the rule
  applies harder.
- **Prescribing specific event names, schema fields, CLI verb names, or
  config keys** that aren't directly observable user behavior. These belong
  in the architecture phase (after classification + grounding), not in the
  intent capture.

The discriminator: could intake classify this work into Category A/B/C
freely, or has the input already foreclosed the routing decision by naming
specific docs? If foreclosed, it's leakage.

What inputs SHOULD contain instead of doc paths:

- **Intent in user/operator language** — "agents should be able to rename a
  todo without losing dependency edges," not "add `telec workflow todo
rename` in `crates/telec-cli/src/todo.rs`".
- **Affected actors and surfaces** at the level of "which audience" — "this
  is for agents preparing todos," "this is for end users in the dashboard,"
  "this is internal cleanup with no user-facing surface."
- **Acceptance shape** — what observably needs to be true for the work to
  count as done.
- **Brownfield context** — what code/docs already exist that the work
  touches, named for grounding (not for prescribing destinations).
- **An explicit note that this is NOT a feature** when the author knows the
  work is Category B (contract/surface refinement) or Category C
  (implementation-only). Saves intake from misclassifying.

A correctly-shaped input lets intake classify and route. An input that
prescribes doc paths skips classification and bakes in the author's
(possibly wrong) routing guess.

The input is an agent-authored intent capture, not proof that every sentence was
said or decided by the human. A clause claiming human authorization is grounded
in the artifact version's `updated_by` authoring session under
`general/policy/grounding`; lineage, `human_involved`, emphatic wording, and the
artifact's position upstream do not turn agent prose into human intent.

### Consuming upstream intent — HOW is a hypothesis, not a directive

The producer-side rules above keep mechanism out of intent where possible. This
rule is the consumer-side backstop for when it leaks through anyway — and it is
the stronger of the two, because the consumer is the party standing in front of
the code.

Any mechanism named in an upstream artifact — a function, module, event, CLI
verb, schema field, or sequence of calls in an `input`, `prd`, or `architecture`
— is a **hypothesis to verify against the codebase, never a directive to
execute**. The author consuming it owns the HOW.

- **Treat every named mechanism as a grounding lead, not a settled decision.**
  Open the code it points at and confirm the mechanism actually does what the
  upstream artifact assumes. An upstream HOW that was never opened against the
  source is unverified regardless of how confident it reads.
- **When the verified HOW diverges from the suggestion, reality wins** — follow
  the verified mechanism and **record the divergence** in the artifact you
  produce (one line: "input suggested X; using Y because <code reality>"). The
  record is the feedback signal that the upstream guess was wrong; without it the
  same wrong mechanism silently re-propagates downstream.
- **A mechanism divergence is the steward's call, taken without stopping the
  human.** Surface to the human only when correcting the HOW forces a change in
  scope or intent — and that is an upstream-layer change, handled by re-entering
  that layer, not by quietly widening the current artifact.
- **Inputs are never rejected for carrying HOW.** The lead is kept and tested,
  not gated away — the mechanism hint is signal even when it is wrong.

A plan or architecture that adopts an upstream mechanism it never verified
against the code is defective **even when the mechanism happens to be correct**:
the defect is the unverified adoption, because the next wrong guess rides the
same unchecked path.

### Missing upstream intent — reconstruct before you invent or escalate

The section above governs when a mechanism is named. This is its mirror. When the
upstream intent a downstream artifact needs is **missing or underspecified** — a
contract snippet that should exist and does not, an intent the `input` never made
explicit — the author neither fills the gap by inference nor reflexively escalates
it. Both are the same failure: acting without having gone to the source.

- **Reconstruct from what went before.** The originating change, the prior
  contract, the diagnosis, the git history — read them and rebuild the intent. A
  missing snippet whose content is recoverable from source is recovered, not
  invented and not bounced to the human.
- **Author on earned confidence.** Contract-level text is the highest-blast-radius
  output prepare produces, and nothing downstream catches it wrong; earning the
  confidence means having touched the concrete prior state, not pattern-matched it.
- **Escalate only the irreducible residue** — the judgment genuinely the human's to
  make — and escalate by holding, not by forcing a decision the source could have
  settled. See `general/principle/autonomy` (ground before you infer or escalate).

### Scope is bounded — the intent is the whole horizon

The artifact states what outcome the work is authorized to change. That
horizon is derived from intent and situation, not from the todo kind alone:

- Restorative work is anchored by the observed wrong behavior and, for a bug,
  the diagnosed causal mechanism. Betterment may make the restoration coherent
  and durable; it does not smuggle adjacent product scope into the fix.
- Implementation-internal work stays within the contract it preserves.
- Product-shaping work may enrich sparse input with situation-specific domain
  intelligence, provided every consequential addition explains why it belongs
  here and remains a proposal until the product-intent gate accepts it.

For a feature, the PRD carries the horizon into independent review and human
approval. For change or bug work without a PRD, the plan's _Intent & scope_
carries the horizon and the existing plan review applies the same shaping
contract. If shaping discovers a product outcome beyond the authority of the
input, the work re-enters the product-intent path; a plan never launders that
expansion into implementation scope.

Inside the authorized horizon, the author owns mechanism within each affected
bounded context's ownership contract. A decision that changes the horizon, a
documented product contract, or a context boundary returns to the authority
that owns that decision. A future concern appears in present scope only when it
constrains today's coherent choice; otherwise it is dropped or recorded as a
deferral with a meaningful trigger.

### Evidence does not reallocate ownership

A risk, defect, omission, or unknown discovered in an adjacent capability is
evidence about that capability; it is not authority for the current work to
implement, strengthen, validate, or prove the adjacent owner's behavior. At an
existing boundary, the current artifact states the handoff it owns and
references the downstream contract for everything after that handoff.

If the adjacent contract cannot support the authorized outcome, the artifact
records a dependency or blocker, or returns an explicit scope-change proposal
to the intent owner. It never converts the concern into current acceptance
criteria, runtime-specific branches, new success detection, duplicated policy,
or a proof obligation inside the wrong context.

This applies equally to review findings. A finding identifies a defect against
the governing contract; it carries no authority to enlarge the horizon or
assign another context's behavior to the artifact under review. Remediation
re-checks both scope authority and domain ownership before changing an upstream
artifact.

### PRD quality

The PRD states what and why, never how. It is a product contract whose natural
sections make the scope choice reviewable:

- the authorized outcome horizon;
- the better target and why it matters here;
- consequential inclusions and exclusions, each grounded in an inspectable
  premise or a named assumption;
- meaningful deferrals with triggers;
- observable success outcomes;
- unresolved decisions that genuinely belong to the human.

The PRD does not prove that a prescribed process was followed. It preserves the
semantic outcomes of shaping so an independent reader can audit the choices and
re-run the questions for omissions.

Concrete signals of implementation leakage remain defects:

- Enumerating specific directory paths, file names, or file locations.
- Naming specific config field names, YAML keys, or database columns.
- Prescribing specific function signatures, class names, or module structure.
- Specifying implementation counts, minimums, or thresholds that are not
  observable product constraints.
- Listing internal taxonomy fields or identifiers when the governing contract
  can be referenced instead.

The discriminator is whether a different sound implementation could satisfy
the outcome. A real product constraint may narrow the solution space; an
unverified mechanism suggestion may not.

### A contract clause is checked against the decision it came from

Reviewing an artifact for internal coherence cannot detect a clause that reads
perfectly and says something the deciding party never agreed to. An absolute
ruling silently acquires a qualifier, the qualified version is self-consistent,
and every later reader treats the weakened form as the contract.

So when a clause carries a decision — a human's ruling, an approved intent, a
prior contract it restates — review compares the clause to that source, not only
to the artifact around it. The comparison is against what the source actually
says; a paraphrase that "captures the spirit" is precisely the failure mode,
because it always does, to the author.

A qualifier that appears where the source stated none, or a condition attached
to something the source stated unconditionally, is a defect regardless of how
reasonable it reads.

### Owner-directed literal PRD corrections

An exact correction supplied by the human owner in a live conversation does
not require a fresh independent PRD review when all of the following hold:

- the human names the precise value, order, label, or sentence to replace and
  its exact replacement;
- the active prepare claimant applies only that bounded replacement, with no
  inferred companion edits, new scope, or agent-authored interpretation; and
- the human explicitly directs the claimant to approve the corrected digest.

In that case the claimant may stamp `prd_review=approve` against the new digest
on the human's authority without dispatching `/next-review-prd`. The session
transcript is the authority record; the stamp's caller remains the claimant and
never impersonates or names the human. If applying the correction requires
synthesis, reconciliation, or judgment beyond the exact replacement, the
exception does not apply and normal independent review remains mandatory.

### Architecture artifact quality

Architecture bridges PRD intent to code reality. It must be technical enough to
guide specs and plan tasks, but it must not smuggle in product scope that the PRD
does not contain.

Quality rules:

- References the PRD sections it derives from by `prd#section-header`. No
  verbatim copy.
- Preserves the approved target while reconciling it with current code and
  credible intended state. Existing implementation is evidence and a default,
  never a silent veto.
- Names affected services, modules, events, surfaces, and state ownership when
  they apply.
- Names current patterns reused, adapted, replaced, or retired when that
  relation matters, with the reason tied to the approved target.
- Keeps state evidence, solution evidence, inference, and assumptions
  distinguishable.

- For unfamiliar infrastructure or a security boundary, includes a
  Prior-art & adopt-vs-build section: the reference implementations, current
  vendor documentation, and at least one comparable production architecture
  surveyed, plus the adopt-vs-build decision with its reason. Bespoke
  infrastructure or a custom security mechanism with no prior-art evidence is
  defective (`general/principle/grounding`).
- Records open architectural questions explicitly instead of hiding them in
  implementation-plan tasks.

### DoD-driven review-awareness

Plans anticipate what delivery review will check. The PRD owns observable
outcomes; architecture owns the technical reconciliation needed to preserve
them; the plan owns concrete proof under the project's applicable verification
contract.

For each outcome and architectural constraint, the plan identifies the task
that delivers it and the evidence by which a builder and reviewer can observe
completion. Evidence may be an executable test, a live-system probe, a browser
walk, a configuration surface, a documentation contract, or another
project-sanctioned verification source. The plan names the concrete boundary
and observation; “tests” or “verify it works” is not compliance.

Arrive at that evidence by asking, per outcome: **what plausible wrong outcome
must this check distinguish from success, and where would that difference be
observable?** The answer yields both the failure the probe has to catch and the
boundary where it is caught. The task records that wrong outcome beside its
evidence line, so a reviewer can judge whether the named boundary actually
distinguishes it. A check that would pass whether or not the work is correct is
not evidence, however concretely it is named — specificity is not discriminating
power.

**Executable by the receiving role, from where it runs.** Evidence and the act
that produces it must be executable by the role and phase the task is assigned
to, within that role's authority and execution environment — location is one
input to that judgment. A verification the assigned role cannot legally or
physically perform from its environment is not evidence for that task, however
discriminating it would be if it could run. A later phase's established
obligation may be cited as the downstream evidence that discharges an outcome;
it is never authored as a task for a role that cannot execute it. Where the
project's verification contract declares a class of live evidence unreachable
from the work phase's environment, the plan cites that contract's downstream
discharge instead of inventing a probe.

Evidence is specific to the work:

- CLI behavior names the command surface and observable invocation.
- Browser behavior names the changed flow and live smoke path.
- Configuration names the public configuration surface and effective behavior.
- Security boundaries name the validation and authorization observations.
- Documentation names the affected contract snippet.
- User-visible behavior names the observable outcome and where it is exercised.

A plan task without a concrete deliverable and applicable proof is incomplete.
The PRD remains mechanism-free and carries no DoD-implications block.

### Observation map — the plan wires behavior to runtime evidence

For behavioral work, the plan carries an **observation map** binding every
in-scope use case to the runtime evidence that will prove it, per
`software-development/spec/observation-map`. The planner authors it; the plan
reviewer recomputes its denominator independently — the use cases the spec
delta delivers plus the unchanged use cases the change's blast radius places at
risk — and judges whether each entry's predicate would actually distinguish
compliant from broken behavior. A map checked only against the plan's own
inventory is self-consistency dressed as coverage.

Plan approval freezes the map under the approved artifact digest. A builder who
discovers the map is wrong kicks preparation back; it never revises the map it
implements. Delivery requires the map's instrumentation to be independently
reviewed as present and correctly placed (**armed**); it never waits for
runtime observation.

### Tasks are checked against each other, not only against their scenarios

A plan is not a list of independently correct tasks. Two tasks may each deliver
their referenced scenario faithfully and destroy one another when applied to the
same code, and tracing each to its own scenario cannot see that — the check runs
per task, and the collision lives between them.

So a plan states, and its review verifies, how the tasks compose where they
touch the same surface. Any two tasks that change or newly call into the same
function, predicate, or record are read together, in the order the plan applies
them, against the question: after both land, does each still do what its
scenario says?

### A discriminator that gains a caller is enumerated at that caller

When a task reuses an existing predicate, filter, matcher, or classifier at a
site that did not call it before, the plan states the **complete set of inputs
that discriminator matches at the new site** — not what it was written for, and
not who else already calls it. Reuse is not evidence of safety: the predicate
was correct for its original callers and knows nothing of the new one.

The related blast-radius question is asked about the right object. Adding a
filter to a call site exposes everything that flows through that site;
computing the radius over "who else calls the predicate I did not modify"
answers a different question and returns a reassuring empty set.

<!-- planned-change:review-verdicts-bind-evidence -->
### Review findings artifacts

A preparation review artifact — `plan-review-findings`, `architecture-review-findings`,
`prd-review-findings` — is a point-in-time record of what one review pass found,
never the current verdict. Those reviews write findings only when findings
exist, so an approving pass leaves the previous artifact in place: an artifact
stating unresolved work can sit beside an approval that supersedes it, and that
is the contract working rather than an inconsistency. Read the stamp for the
outcome and the artifact for what a pass found; never infer the verdict from the
artifact alone.

Build review differs and is not covered by this rule: it persists
`review-findings` on every pass, so that artifact tracks its own latest review.
<!-- change:review-verdicts-bind-evidence -->
### Review report artifacts

Every preparation and build review pass writes its complete report before it
stamps a verdict: `prd-review-findings`, `architecture-review-findings`,
`plan-review-findings`, or `review-findings`. A clean pass writes the same
complete lane and verdict structure as a rejecting pass, so the current report
always describes the pass that produced the current stamp.

The verdict state binds the reviewed target digest and the report artifact's
current digest. An absent report, a target rewrite, or a later report rewrite
leaves the verdict non-current and the lifecycle routes through review again.
The report remains evidence, not authority: read its content for the analysis
and the stamp for the workflow decision, and never infer one from the other.
<!-- /planned-change:review-verdicts-bind-evidence -->

### Acceptance scenario quality

Feature-spec acceptance scenarios authored during intake are prose behavioral
contracts, authored per
`software-development/procedure/feature-spec-authoring` — facing-typed actors,
behavior-level language, immutable use-case identity. They do not create source
files or executable tests during prepare. Quality rules:

- **Behavioral focus**: scenarios encode observable behavior (inputs, outputs,
  side effects), not implementation structure. A scenario that asserts a
  specific internal function call is implementation leakage. Every scenario
  sentence survives any behavior-preserving refactor; the mechanism that proves
  it lives in the plan's observation map, never in scenario text.
- **Forbidden assertion targets**: scenarios must not prescribe logger-call,
  log-level, metric/trace, config/model/native-shape, private-helper,
  constructor-wiring, or mock-call-echo assertions. Logs are diagnostic evidence,
  not feature behavior. Config and native models are tested through accepted and
  rejected external inputs, wire/API payloads, or effective runtime behavior.
- **No source code**: scenarios may name existing test surfaces or expected
  assertions, but must not include executable test code, helper function bodies,
  or expected-failure markers. The builder writes or updates tests during work.
- **No implementation leakage in scenario structure**: test organization, helper
  names, and fixture details must not prescribe internal architecture. Test what
  the code does, not how it is structured.
- **Grounding against existing test patterns**: new scenario-derived tests must follow the
  existing test conventions in the codebase (naming, fixtures, assertion style).
  A scenario that requires a novel testing pattern without justification is defective.

### Plan-specific quality

Plans must provide enough detail for a builder to execute without guessing:

- **Every task begins with references to the upstream items it delivers** —
  by artifact path and section header, e.g.
  `Delivers: prd#criterion-a, prd#criterion-b, architecture#event-naming,
docs/project/spec/feature/workflow/todo-rename#scenario-rename-conflict`. The task body then describes the work
  and must name each referenced item in its delivery description — showing
  which change satisfies which reference. A task that references items it
  does not deliver, or delivers work not traceable to any referenced upstream
  item, is defective. Copy-pasting the upstream text into the task is
  defective; the reference is the contract.
- Every task has a rationale explaining _why_ this approach, not just _what_.
- Every task has a verification step that references specific feature-spec scenarios,
  existing tests, or direct checks: a test to satisfy, behavior to observe, or check to run.
  "Tests" as an abstract category is not compliance — name the specific test
  file and the behavior observed at a meaningful boundary. Do not name
  logger/config/native-shape/private-helper/wiring assertions as deliverables.
- Tasks trace to PRD, architecture, or feature-spec scenarios. No orphan tasks
  (gold-plating) and no orphan PRD criteria (coverage gaps).
- Referenced file paths are explicit in the plan tasks for grounding and
  staleness review.
- The implementation plan declares exactly one ` ```referenced-paths ` fenced
  contract block listing every file the work creates or modifies. This block is
  the authoritative code drift surface. Per-task prose may still name files for
  builder grounding, but prose path mentions are not part of the drift contract.

## Rationale

- Domain intelligence adds value only when it can widen the candidate target
  before scope is chosen, while inspectable premises and independent review
  prevent a generic recital from acquiring intent authority.
- Separating target formation from implementation reconciliation prevents the
  present codebase from becoming an accidental product veto while preserving
  the economy and safety of established patterns.
- Keeping observable outcomes in the PRD and concrete proof in the plan lets
  each artifact answer one question without embedding implementation detail in
  the product contract.

- Preparation artifacts flow through a chain: creator → reviewer → gate →
  builder → code reviewer. Quality failures in early stages compound
  downstream. A PRD that prescribes implementation detail confuses the builder.
  A plan that misses a DoD gate produces review findings that cost more to fix
  than to prevent.
- Domain-context loading prevents the most common failure mode: validating
  structure without substance. Checking "grounding" without loading the
  actual specs is checking against air.
- Artifact discovery replaces a fixed prose enumeration, which goes stale the
  moment the artifact vocabulary grows and silently omits whatever it was
  never updated to name, with a live check of what is actually present.
- Shared quality rules between creators and reviewers ensure the creator
  targets the same bar the reviewer enforces. The reviewer is a safety net,
  not the first line of defense.
- HOW must align with code reality, not up-front guesswork. Upstream intent is
  authored before the code is examined, so its mechanism hints are
  cache-of-a-guess, not source of truth (`general/principle/grounding`). An
  agent that treats them as directives propagates errors no later gate catches.
  Verifying and overriding at the point of consumption — rather than rejecting
  the input at its boundary — puts the decision where the knowledge is, and
  keeps the useful lead instead of discarding it. See
  `project/adr/0020-upstream-how-is-a-hypothesis-not-a-gate` for why a
  creation-time gate was rejected.

## Scope

- Applies to all preparation artifacts: `prd`, `architecture`,
  `implementation-plan`, and readiness reports.
- Applies to all agents creating or reviewing these artifacts: intake,
  architecture, plan, reviewers, and gate assessors.

## Enforcement

- Creators self-check against this policy before delivering artifacts.
- Reviewers validate against this policy and flag violations as findings.
- The DOR gate verifies cross-artifact coherence assuming individual
  artifacts meet this quality bar.

## Exceptions

- Emergency hotfixes may skip formal preparation with explicit follow-up.
