---
description: 'Quality rules for preparation artifacts (PRD, architecture, and plans). Shared by creators and reviewers.'
visibility: 'public'
---

# Preparation Artifact Quality — Policy

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

### Grounding

PRD, architecture, and plans reference codebase patterns, existing APIs, or
documented conventions — not invented abstractions.

- If the codebase has an established way to do X, the artifact says "using
  the existing X pattern" rather than inventing a new one.
- Verify grounding against the domain specs loaded above, not against general
  knowledge. If an artifact references a taxonomy, schema, config surface, or
  API — confirm it matches the actual spec.
- Artifacts that prescribe approaches contradicting codebase patterns or
  documented specs are defective.

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

### PRD quality

The PRD states what and why, never how. Architecture and plans state how. The
boundary is clear: PRD constrains the solution space; downstream artifacts fill it.

Concrete signals of leakage in PRD — each is a defect:

- Enumerating specific directory paths, file names, or file locations.
- Naming specific config field names, YAML keys, or database columns.
- Prescribing specific function signatures, class names, or module structure.
- Specifying counts, minimums, or thresholds that aren't user-facing.
- Listing specific taxonomy types, schema fields, or internal identifiers when
  the PRD could instead reference the governing spec.

The discriminator: could the builder satisfy the PRD criterion using a different
implementation approach? If the PRD forecloses valid alternatives
without justification, it's leakage.

Exception: constraints that narrow the solution space are PRD content, not
leakage. "Must conform to the snippet authoring schema" constrains. "Place
files under `docs/project/design/`" prescribes.

### Architecture artifact quality

Architecture bridges PRD intent to code reality. It must be technical enough to
guide specs and plan tasks, but it must not smuggle in product scope that the PRD
does not contain.

Quality rules:

- References the PRD sections it derives from by `prd#section-header`. No
  verbatim copy.
- Names affected services, modules, events, surfaces, and state ownership when
  they apply; marks non-applicable sections as N/A rather than omitting them.
- Grounds claims in existing codebase patterns and loaded domain specs.
- Names architectural defaults followed or intentionally diverged from, with
  reason.
- Records open architectural questions explicitly instead of hiding them in
  implementation-plan tasks.

### DoD-driven review-awareness

PRD, architecture, and plans must anticipate what the code reviewer will check.
This is an evidence-producing rule, not a mental check.

For each PRD criterion, produce a **DoD-implications block** naming the DoD
gates triggered and the concrete evidence artifact for each. "PRD criterion
implies tests" is not compliance; "Test X at file Y, line Z pins behavior W"
is compliance. An agent satisfies this rule by producing the block; an agent
who "considered" DoD mentally has not satisfied it.

Evidence must be specific:

- CLI changes → name the help-text location and the config surface section.
- New behavior → name the test file and the specific assertion.
- Browser-based frontend or web UI behavior → name the Playwright smoke path.
- New config → name the wizard entry, the sample line, and the spec section.
- Security boundaries → name the validation point and the auth check.
- Documentation changes → name the doc file and the section updated.
- User-visible behavior → name the observable outcome and where it is verified.

A PRD criterion without a concrete evidence statement per triggered gate is
incomplete. A plan task without a named deliverable per triggered gate is
incomplete.

### Acceptance scenario quality

Feature-spec acceptance scenarios authored during intake are prose behavioral
contracts. They do not create source files or executable tests during prepare.
Quality rules:

- **Behavioral focus**: scenarios encode observable behavior (inputs, outputs,
  side effects), not implementation structure. A scenario that asserts a
  specific internal function call is implementation leakage.
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
- The implementation plan declares exactly one `` ```referenced-paths `` fenced
  contract block listing every file the work creates or modifies. This block is
  the authoritative code drift surface. Per-task prose may still name files for
  builder grounding, but prose path mentions are not part of the drift contract.

## Rationale

- Preparation artifacts flow through a chain: creator → reviewer → gate →
  builder → code reviewer. Quality failures in early stages compound
  downstream. A PRD that prescribes implementation detail confuses the builder.
  A plan that misses a DoD gate produces review findings that cost more to fix
  than to prevent.
- Domain-context loading prevents the most common failure mode: validating
  structure without substance. Checking "grounding" without loading the
  actual specs is checking against air.
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
