---
id: 'software-development/procedure/lifecycle/prepare/review-specs'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Test-spec review phase. Validate prose test specifications against the PRD, optional architecture, and preparation artifact quality rules.'
---

# Review Test Specs — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md

## Goal

Validate the `test-specs` artifact as a prose behavioral contract. The artifact
must pin approved PRD success criteria and optional architecture constraints
without writing source code, test code, helper functions, or implementation
structure.

## Preconditions

- `telec todo artifacts read {slug} prd` exists and is approved.
- `architecture` is approved or explicitly skipped.
- `telec todo artifacts read {slug} test-specs` exists unless the test-specs
  phase was skipped.

## Steps

### 1. Read context

- `telec todo show {slug}`.
- `telec todo artifacts read {slug} prd`.
- `telec todo artifacts read {slug} architecture` when present.
- `telec todo artifacts read {slug} test-specs`.
- Relevant codebase tests and fixtures only as grounding examples; do not create
  or edit code in this phase.
- Apply the domain-context loading rule from the preparation artifact quality
  policy before validating.

### 2. Validate behavioral coverage

For each PRD success criterion, verify that `test-specs` names the observable
behavior that would prove it. Each spec entry must include:

- the verbatim PRD criterion it pins;
- the scenario or assertion in prose;
- the expected observable result;
- the existing test pattern or test surface the builder should use later.

Missing coverage for a non-skipped PRD criterion is an Important finding. A spec
that narrows or contradicts the PRD is Critical.

### 3. Validate no-code boundary

Reject source-code-like test specs. The artifact may name existing test files or
fixtures as grounding examples, but it must not contain:

- executable test code;
- helper function implementations;
- concrete module/class/function structure that forces an implementation shape;
- expected-failure markers or instructions to edit files during prepare.

The builder owns executable test edits during work. Prepare owns the prose
contract.

### 4. Validate grounding and review awareness

Apply the grounding and DoD-driven review-awareness rules from the preparation
artifact quality policy. The specs must match the codebase's existing testing
style without inventing a new harness, fixture pattern, or assertion language.

### 5. Write verdict

Stamp the review verdict:

```bash
telec todo stamp {slug} --verdict approve --phase specs_review
# or
telec todo stamp {slug} --verdict needs_work --phase specs_review
```

If unresolved findings remain, write them via:

```bash
telec todo artifacts write {slug} spec-review-findings <content>
```

## Outputs

- Verdict stamped with `telec todo stamp`.
- `telec todo artifacts read {slug} spec-review-findings` when findings exist.

## Recovery

- If the test-specs phase was skipped but the PRD clearly requires a bespoke
  behavioral contract, mark `needs_work` and ask the orchestrator to clear the
  skip stamp.
- If architecture is absent because it was skipped, validate specs against PRD
  and existing code/test patterns only.
