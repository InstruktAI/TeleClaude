---
id: 'software-development/policy/preparation-artifact-quality'
type: 'policy'
scope: 'domain'
description: 'Quality rules for preparation artifacts (requirements and plans). Shared by creators and reviewers.'
---

# Preparation Artifact Quality — Policy

## Rules

### Quoting upstream intent

Every downstream artifact must carry the upstream requirement text verbatim.
Plans quote the requirement section(s) that each task delivers. Test specs
include the requirement criteria they pin, quoted from `requirements.md`.
Reviews quote the criteria under analysis before analyzing them.

An artifact that paraphrases or summarizes upstream intent without preserving
the verbatim source is defective: the source text is the contract, paraphrase
is a derivative that drifts. When the full upstream text sits adjacent to the
downstream artifact, mismatches are visible without judgment calls.

### Domain-context loading

Before creating or reviewing a preparation artifact, identify which domain
specs the artifact touches and load them.

- Read the artifact (or input, if creating) and identify the domains it
  affects: documentation system, CLI surface, config surface, messaging,
  session infrastructure, etc.
- Run `telec docs index` and load the relevant specs via `telec docs get`.
- Examples: work involving doc snippets → load the snippet authoring schema.
  Work involving CLI changes → load the CLI surface spec. Work involving
  config → load the teleclaude-config spec.

Domain specs are the ground truth. Grounding, leakage detection, and
review-awareness cannot be evaluated without them.

### Grounding

Requirements and plans reference codebase patterns, existing APIs, or
documented conventions — not invented abstractions.

- If the codebase has an established way to do X, the artifact says "using
  the existing X pattern" rather than inventing a new one.
- Verify grounding against the domain specs loaded above, not against general
  knowledge. If an artifact references a taxonomy, schema, config surface, or
  API — confirm it matches the actual spec.
- Artifacts that prescribe approaches contradicting codebase patterns or
  documented specs are defective.

### No implementation leakage in requirements

Requirements state what and why, never how. Plans state how. The boundary
is clear: requirements constrain the solution space; plans fill it.

Concrete signals of leakage in requirements — each is a defect:

- Enumerating specific directory paths, file names, or file locations.
- Naming specific config field names, YAML keys, or database columns.
- Prescribing specific function signatures, class names, or module structure.
- Specifying counts, minimums, or thresholds that aren't user-facing.
- Listing specific taxonomy types, schema fields, or internal identifiers
  when the requirement could instead reference the governing spec.

The discriminator: could the builder satisfy the requirement using a different
implementation approach? If the requirement forecloses valid alternatives
without justification, it's leakage.

Exception: constraints that narrow the solution space are requirements, not
leakage. "Must conform to the snippet authoring schema" constrains. "Place
files under `docs/project/design/`" prescribes.

### DoD-driven review-awareness

Requirements and plans must anticipate what the code reviewer will check.
This is an evidence-producing rule, not a mental check.

For each requirement, produce a **DoD-implications block** naming the DoD
gates triggered and the concrete evidence artifact for each. "Requirement
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

A requirement without a concrete evidence statement per triggered gate is
incomplete. A plan task without a named deliverable per triggered gate is
incomplete.

### Test specification quality

Test specifications delivered during the prepare phase define the behavioral
contract the builder must satisfy. Quality rules:

- **Behavioral focus**: test specs encode observable behavior (inputs, outputs,
  side effects), not implementation structure. A test that asserts a specific
  internal function call is implementation leakage.
- **No implementation leakage in test structure**: test organization (file names,
  class names, helper functions) must not prescribe internal architecture. Test
  what the code does, not how it is structured.
- **Expected-failure convention**: all spec-delivered tests must be marked with
  the project's expected-failure convention so they fail cleanly before
  implementation. The builder removes the marker as the first action per task.
- **Grounding against existing test patterns**: new test specs must follow the
  existing test conventions in the codebase (naming, fixtures, assertion style).
  A test spec that introduces a novel testing pattern without justification is
  defective.

### Plan-specific quality

Plans must provide enough detail for a builder to execute without guessing:

- **Every task begins with a verbatim quote of the requirement criteria it
  delivers**, sourced from `requirements.md`, including the full success-criteria
  bullet list. The task body then describes the work and must reference each
  quoted criterion in its delivery description — showing which change satisfies
  which criterion. A task that quotes criteria it does not deliver, or delivers
  work not traceable to any quoted criterion, is defective.
- Every task has a rationale explaining _why_ this approach, not just _what_.
- Every task has a verification step that references specific expected-failure
  tests it makes GREEN: a test to satisfy, behavior to observe, or check to run.
  "Tests" as an abstract category is not compliance — name the specific test
  file and assertions.
- Tasks trace to requirements. No orphan tasks (gold-plating) and no orphan
  requirements (coverage gaps).
- Referenced file paths are explicit in the plan tasks for grounding and
  staleness review.

## Rationale

- Preparation artifacts flow through a chain: creator → reviewer → gate →
  builder → code reviewer. Quality failures in early stages compound
  downstream. A requirement that prescribes implementation detail confuses
  the builder. A plan that misses a DoD gate produces review findings that
  cost more to fix than to prevent.
- Domain-context loading prevents the most common failure mode: validating
  structure without substance. Checking "grounding" without loading the
  actual specs is checking against air.
- Shared quality rules between creators and reviewers ensure the creator
  targets the same bar the reviewer enforces. The reviewer is a safety net,
  not the first line of defense.

## Scope

- Applies to all preparation artifacts: `requirements.md`,
  `implementation-plan.md` and `dor-report.md`.
- Applies to all agents creating or reviewing these artifacts: discovery
  workers, draft workers, requirements reviewers, plan reviewers, and
  gate assessors.

## Enforcement

- Creators self-check against this policy before delivering artifacts.
- Reviewers validate against this policy and flag violations as findings.
- The DOR gate verifies cross-artifact coherence assuming individual
  artifacts meet this quality bar.

## Exceptions

- Emergency hotfixes may skip formal preparation with explicit follow-up.
