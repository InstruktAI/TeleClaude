---
description: "Quality rules for an item's prepared spec, the intent it starts from, and the mechanism that delivers it. Shared by authors, builders, dedicated reviewers and coordinating drivers."
visibility: 'public'
---

# Preparation Artifact Quality — Policy

## Required reads

- @~/.teleclaude/docs/sdlc/policy/domain-ownership.md

## Rules

These rules bind the author of the specification
(`sdlc/procedure/lifecycle/prepare/intake-v2`), its dedicated reviewer
(`sdlc/procedure/lifecycle/prepare/review-plan`), the builder
(`sdlc/procedure/lifecycle/work/build-v2`) and its dedicated reviewer
(`sdlc/procedure/lifecycle/work/review-build`). The preparation and work drivers
coordinate these handoffs and record the independently supported outcomes.

### Domain-context loading

Before writing or judging a spec, identify which domain specs and implementation
policies it touches and load them. Apply the relevant language, tooling,
compatibility, security and testing rules while choosing the approach, even
when the present artifact is prose. Research an integration's actual required
capabilities against primary sources and the available native libraries before
settling its transport. An authored plan cannot make a policy exception for
itself; a justified divergence from local precedent still owes policy compliance.

- Read the item's intent (or the spec, when judging) and identify the domains it
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

Before reading the item for context, discover what actually exists.

- Run `telec todo artifacts list {slug}` first. Read whichever present
  artifacts are relevant to your role's own purpose.
- `log`, when present, is always relevant regardless of role or kind — it
  carries the item's notes, reasons and decisions. Read it whenever it exists.
- Which other present artifacts matter, and why, is role-specific judgment.
  Only the discovery mechanic is shared; the relevance judgment is not.

### Intent shaping

Preparation determines the work's authorized horizon before enriching or
constraining it. The horizon is inferred from the source intent and the
situation, then stated in the spec the reviewer judges; it is not selected from a
hard kind lookup.

Preparation uses six design focuses before selecting a mechanism:

1. **Outcome:** What is authorized to improve, for whom, and what observable
   result makes the work useful? Which proposed improvements actually serve it?
2. **Context:** What do the actual scale, trust boundary, current behavior and
   operating and maintenance costs require, rather than a hypothetical system?
3. **Existing solutions:** How is this class of outcome already achieved here
   and in established practice? What can be reused, and what concrete gap earns
   construction or a departure from it?
4. **Ownership and composition:** Who owns each decision, state and effect,
   and how do the boundaries compose into the complete outcome?
5. **Consequences:** Which failure, recovery, security and performance concerns
   arise in this use case, and which guarantees can their actual owners support?
6. **Delivery:** What is the smallest complete change, how will the existing
   verification path assess it, and what remains outside that evidence?

These focuses direct attention, not artifact structure. Record the conclusions
that change the design in the existing artifact's natural sections, at the level
that artifact owns. Scale the depth to the work; a focus earns no extra feature,
research project, report, or not-applicable catalogue. Author and challenger
derive their own reading before reconciling it (`general/policy/leadership`).

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

The spec carries the choosing reasoning in its natural sections: the authorized
horizon, why consequential scope belongs here, exclusions that bound the
outcome, assumptions, and observable outcomes; the author's inference record
carries what the spec says beyond the literal input. The driver re-runs the
questions to probe for omissions and checks the reasons that survived into the
spec.

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
spec names the conflict and explains why the target requires adaptation,
replacement, retirement, or a genuinely different shape. Conformance to the
current implementation is not correctness by itself, and novelty is not value
by itself.

Verify state claims against code and loaded domain specs. Verify solution
claims against authoritative external evidence when they matter. Before choosing
new construction, assess established implementations and compositions for the
same outcome as well as the comparable in-system path. Name what is reused and
the concrete gap that remains; interface familiarity or a list of references is
not an assessment of existing solutions (`general/principle/grounding`). This
applies to designs carried by specifications and completed implementation rationales as well as architecture
artifacts. For unfamiliar infrastructure or a security boundary, the artifact
names the reference implementations, current vendor documentation and a
comparable production architecture behind its adopt-or-build judgment.
A grounded spec neither
invents a mechanism from memory nor lets the present codebase veto a better,
approved target without examination.

### Intent quality

The intent at the top of an item's body is the human's — or the filer's —
statement of WHAT is wanted and WHY. It does NOT prescribe WHERE durable docs
land; the author decides that when it authors the spec's durable contract
changes.

Concrete signals of leakage in the intent — each is a defect:

- **Naming specific feature-spec, domain-spec, or design-doc paths.** An intent
  that says "author `docs/local/spec/feature/<x>/<y>.md`" prescribes doc
  routing its filer may have classified wrong. Especially toxic when the path
  contains the item's slug, because an author that takes the string literally
  creates a slug-named non-feature snippet — exactly the failure
  `sdlc/principle/documentation-first-development` (§3a, §3b) exists to prevent.
- **Naming specific implementation paths or file locations.**
- **Prescribing specific event names, schema fields, CLI verb names, or config
  keys** that aren't directly observable user behavior. These are settled when
  the spec is reconciled with the system, not in the intent capture.

The discriminator: could the author classify and route this work freely, or
has the intent already foreclosed the routing decision by naming specific docs?
If foreclosed, it's leakage.

What an intent SHOULD contain instead of doc paths:

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
- **An explicit note that this is not behavioral work** when the filer knows
  nothing an observer experiences changes.

### Consuming upstream intent — HOW is a hypothesis, not a directive

The rules above keep mechanism out of intent where possible. This rule is the
consumer-side backstop for when it leaks through anyway — and it is the
stronger of the two, because the consumer is the party standing in front of the
code.

Any mechanism named upstream — a function, module, event, CLI verb, schema
field, or sequence of calls in the intent, or in a carried artifact such as a
`prd`, `architecture` or `implementation-plan` — is a **hypothesis to verify
against the codebase, never a directive to execute**. The author or builder
consuming it owns the HOW.

- **Treat every named mechanism as a grounding lead, not a settled decision.**
  Open the code it points at and confirm the mechanism actually does what the
  upstream text assumes. An upstream HOW that was never opened against the
  source is unverified regardless of how confident it reads.
- **When the verified HOW diverges from the suggestion, reality wins** — follow
  the verified mechanism and **record the divergence** in what you produce (one
  line: "input suggested X; using Y because <code reality>"). The record is the
  feedback signal that the upstream guess was wrong; without it the same wrong
  mechanism silently re-propagates downstream.
- **A mechanism divergence is the steward's call, taken without stopping the
  human.** Surface to the human only when correcting the HOW forces a change in
  scope or intent — and that is an intent-level change, handled in preparation,
  not by quietly widening the current work.
- **An acceptance-shape statement is never a mechanism hint.** What the intent
  says is delivered, what an observer experiences, or what kind of thing the
  work produces is WHAT, even when a mechanism word appears in it. A divergence
  from it is not recorded and proceeded on; the author stops and states the one
  question that would change the intent. Recording such a divergence as HOW,
  however well argued, is the invention this policy exists to catch.
- **Intents are never rejected for carrying HOW.** The lead is kept and tested,
  not gated away — the mechanism hint is signal even when it is wrong.

A specification or completed change description that adopts an upstream mechanism it never verified
against the code is defective **even when the mechanism happens to be correct**:
the defect is the unverified adoption, because the next wrong guess rides the
same unchecked path.

### Implementation is the builder's within the prepared spec

Everything the prepared spec settles binds the builder as it states it: the
outcome, scope, bounded-context ownership, the contracts it references,
invariants, the risk it accepted, and applicable quality gates. A placement,
name, or decomposition that one of these itself decides — an ownership
boundary, a layering rule, an invariant — binds as that decision.

Within those bounds the builder decides mechanism, placement, names, and
decomposition from the code in front of it, including splitting a module to
meet a quality limit, and never lowers the quality floor to do so. A placement,
name, or decomposition a carried plan forecast is a hypothesis, not a bound. The
spec is not edited to match the build.

Review judges the actual diff. A difference from a forecast is neither a finding
nor a spec defect by itself: a finding cites the contract the difference
violates and establishes the contradiction (`sdlc/procedure/lifecycle/review`),
and a kickback rests on the spec being wrong or unbuildable
(`sdlc/procedure/lifecycle/work/overview-v2`), never on the difference.

### The mechanism is checked as a whole

The builder self-checks the complete implementation as one composition. After
that handoff, the reviewer independently judges the same composition under
`sdlc/procedure/lifecycle/review`, rather than approving its parts in an early
design conversation.

- **Changes are checked against each other.** Two changes may each deliver
  their part of the spec faithfully and destroy one another when applied to the
  same code. Any two that change or newly call into the same function,
  predicate, or record are read together, in the order they apply, against the
  question: after both land, does each still do what the spec says?
- **A discriminator that gains a caller is enumerated at that caller.** When a
  change reuses an existing predicate, filter, matcher, or classifier at a site
  that did not call it before, the change description states the complete set of inputs that
  discriminator matches at the new site — not what it was written for, and not
  who else already calls it. Adding a filter to a call site exposes everything
  that flows through that site.
- **A rationale rests on a contract, never on a precedent.** A past commit shows
  what was done once; it authorizes nothing. A step a precedent suggests is
  checked against the contract that governs that act before it is adopted.
- **A remediation carries its premise through the whole artifact.** When a fix
  changes something the spec or the mechanism stands on — a mechanism or a scope
  boundary — every statement that depends on it is brought into line in the
  same revision, and the disposition names the changed premise and what was
  carried through.

### Missing upstream intent — reconstruct before you invent or escalate

The section above governs when a mechanism is named. This is its mirror. When the
upstream intent a downstream artifact needs is **missing or underspecified** — a
contract snippet that should exist and does not, an intent the item never made
explicit — the author neither fills the gap by inference nor reflexively escalates
it. Both are the same failure: acting without having gone to the source.

- **Reconstruct from what went before.** The originating change, the prior
  contract, the established cause, the git history — read them and rebuild the
  intent. A missing snippet whose content is recoverable from source is
  recovered, not invented and not bounced to the human.
- **Author on earned confidence.** Contract-level text is the highest-blast-radius
  output preparation produces, and nothing downstream catches it wrong; earning
  the confidence means having touched the concrete prior state, not
  pattern-matched it.
- **Escalate only the irreducible residue** — the judgment genuinely the human's to
  make — and escalate by holding, not by forcing a decision the source could have
  settled. See `general/principle/autonomy` (ground before you infer or escalate).

### Scope is bounded — the intent is the whole horizon

The spec states what outcome the work is authorized to change. That horizon is
derived from intent and situation, not from the todo kind alone:

- Restorative work is anchored by the observed wrong behavior and, for a bug,
  the established causal mechanism. Betterment may make the restoration coherent
  and durable; it does not smuggle adjacent product scope into the fix.
- Implementation-internal work stays within the contract it preserves.
- Product-shaping work may enrich sparse input with situation-specific domain
  intelligence, provided every consequential addition explains why it belongs
  here and the inference record carries it for the driver's judgment.

The spec carries the horizon into independent review. If shaping discovers a
product outcome beyond the authority of the intent, that outcome is a question
for the person who owns it; the spec never launders that expansion into
implementation scope.

Inside the authorized horizon, the author owns mechanism within each affected
bounded context's ownership contract. A decision that changes the horizon, a
documented product contract, or a context boundary returns to the authority
that owns that decision. A future concern appears in present scope only when it
constrains today's coherent choice; otherwise it is dropped or recorded with a
meaningful trigger.

### Evidence does not reallocate ownership

A risk, defect, omission, or unknown discovered in an adjacent capability, or a
prerequisite an upstream clause places on that capability, is evidence about
that capability; it is not authority for the current work to
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

In the document layer the same bound holds for findings on feature and domain
specs: a finding never asks a consumer context's use case to be extended,
completed, or made symmetric with the owner's rule. A use case or clause whose
predicate another context decides closes by removal or by a one-sentence
pointer to the owner (`general/policy/snippet-value-contract`, Consumer
restatement); a remediation that elaborates the duplicate instead is a new
finding against the remediation, not a closure.

### Separate production and judgment

The producer completes its own approach and self-checks it against these rules;
the reviewer then evaluates the finished target independently under
`sdlc/procedure/lifecycle/review`. The driver coordinates their completed-artifact handoffs and preserves the
reviewer's independent verdict. Readiness requires both a
coherent outcome and compliance with its governing rules; neither a polished
rationale nor prior approval establishes the other.

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

### Acceptance scenario quality

Feature specs state their behavioral contracts in prose. User goals admitted
under `sdlc/procedure/feature-spec-authoring` are written as Gherkin use cases
with stakeholder actors, behavior-level language and immutable identities.
That admission precedes the scenario-quality checks below; observability alone
does not admit a use case. Preparation creates no executable tests. Quality rules:

- **Behavioral focus**: scenarios encode observable behavior (inputs, outputs,
  side effects), not implementation structure. A scenario that asserts a
  specific internal function call is implementation leakage. Every scenario
  sentence survives any behavior-preserving refactor.
- **Owner-local**: every `Then` clause asserts a decision the spec's own
  context owns. A clause asserting another context's outcome, or a scenario
  that exists only to re-observe another context's rule through this
  context's surface, is consumer restatement
  (`general/policy/snippet-value-contract`) and is removed before review, with
  the owner cited once by id.
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

## Rationale

- Sequential, isolated judgment prevents shared commitment to a chosen solution
  from substituting for policy conformance.

- Domain intelligence adds value only when it can widen the candidate target
  before scope is chosen, while inspectable premises and an independent judge
  prevent a generic recital from acquiring intent authority.
- Separating target formation from implementation reconciliation prevents the
  present codebase from becoming an accidental product veto while preserving
  the economy and safety of established patterns.
- Domain-context loading prevents the most common failure mode: validating
  structure without substance. Checking "grounding" without loading the
  actual specs is checking against air.
- Artifact discovery replaces a fixed prose enumeration, which goes stale the
  moment the artifact vocabulary grows and silently omits whatever it was
  never updated to name, with a live check of what is actually present.
- Shared quality rules between authors and judges ensure the author targets the
  same bar the judge enforces. The judge is a safety net, not the first line of
  defense.
- HOW must align with code reality, not up-front guesswork. Upstream intent is
  authored before the code is examined, so its mechanism hints are
  cache-of-a-guess, not source of truth (`general/principle/grounding`). An
  agent that treats them as directives propagates errors no later gate catches.
  Verifying and overriding at the point of consumption — rather than rejecting
  the input at its boundary — puts the decision where the knowledge is, and
  keeps the useful lead instead of discarding it.
- A forecast of placement, names, or decomposition is written before the
  implementation exists, so the implementation can falsify it
  (`general/principle/grounding`). Binding what the delivery must preserve keeps
  kickback for a spec that is wrong, and keeps the diff, not a forecast of it,
  as what review judges.
- Changes that are each correct can collide where they meet, and a reused
  predicate knows nothing of its new caller; only a check of the composition and
  of the new call site sees either.
- A precedent records an act, not whether it was right or whether it holds in
  the role and environment the work assigns. Copied without its contract, it
  carries an unchecked act that every later gate then reads as settled.
- A fix applied only where a finding points leaves every other statement that
  relied on the old premise asserting it. Each leftover surfaces as the next
  pass's finding, so work remediated spot by spot converges one leftover per
  review round.

## Scope

- Applies to an item's intent, its prepared spec and the pending contracts the
  spec references, and to the builder's completed implementation that delivers it.
- Applies to the author, builder, dedicated reviewers and coordinating drivers
  wherever the specification or implementation is authored or assessed.

## Enforcement

- The author self-checks against this policy before reporting the spec ready
  for challenge; the builder does the same for the complete implementation before handoff.
- Dedicated preparation and work reviewers assess finished targets against it;
  drivers coordinate the handoffs and record the independent verdicts. Each
  finding meets `sdlc/procedure/lifecycle/review`, including isolation and its
  causal evidence and bounded-closure requirements.

## Exceptions

- Emergency hotfixes may skip formal preparation with explicit follow-up.
