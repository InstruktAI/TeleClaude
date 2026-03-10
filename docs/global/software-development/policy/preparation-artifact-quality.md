---
id: 'software-development/policy/preparation-artifact-quality'
type: 'policy'
scope: 'domain'
description: 'Quality rules for preparation artifacts (requirements and plans). Shared by creators and reviewers.'
---

# Preparation Artifact Quality — Policy

## Rules

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
Use the Definition of Done gates as the systematic checklist:

- Walk each DoD section (functionality, code quality, testing, linting,
  security, documentation, commit hygiene, observability).
- For each requirement or plan task, identify which DoD gates it triggers.
- Verify those implications are reflected — either as explicit success
  criteria (in requirements) or as task verification steps (in plans).

Common gaps:

- Requirement implies CLI changes → help text and config surface updates.
- Requirement implies new behavior → test expectations.
- Requirement implies new config → config wizard, sample, and spec updates.
- Requirement implies security boundaries → validation and auth expectations.
- Requirement implies documentation changes → doc update expectations.
- Requirement implies user-visible behavior → demo coverage.

### Plan-specific quality

Plans must provide enough detail for a builder to execute without guessing:

- Every task has a rationale explaining *why* this approach, not just *what*.
- Every task has a verification step: a test to write, behavior to observe,
  or check to run.
- Tasks trace to requirements. No orphan tasks (gold-plating) and no orphan
  requirements (coverage gaps).
- Referenced file paths are listed in `state.yaml.grounding.referenced_paths`
  for staleness detection.

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
  `implementation-plan.md`, `demo.md`, and `dor-report.md`.
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
