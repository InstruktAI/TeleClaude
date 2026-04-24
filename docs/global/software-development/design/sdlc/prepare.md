---
id: 'software-development/design/sdlc/prepare'
type: 'design'
domain: 'software-development'
scope: 'global'
description: 'Prepare phase design: artifact production, role focus, and rigor boundaries for requirements, test specs, and implementation plans.'
---

# Prepare — Design

## Required reads

- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define how the prepare phase produces the aligned artifacts that downstream work
must consume.

Prepare exists to turn a problem impulse into build-ready truth.

## Inputs/Outputs

**Inputs**

- human-provided input and framing
- explicit structural or codebase context where available
- existing lifecycle state and artifacts

**Outputs**

- `requirements`
- `test-specs`
- `implementation-plan`

## Invariants

- `requirements` and `test-specs` remain in the same hot scope.
- `implementation-plan` is derived from both `requirements` and `test-specs`.
- Each artifact is only considered ready when the supporting lens has challenged
  it and accepted it.
- Prepare must not hand downstream work a cold reinterpretation of upstream
  truth.

## Primary flows

### Requirements

Goal:

- capture the real problem, intended outcome, constraints, and scope

Lead/support:

- `A` leads
- `B` supports

How rigor is preserved:

- `A` keeps intent and meaning honest
- `B` pressure-tests ambiguity, contradiction, and feasibility

### Test specs

Goal:

- turn intent into explicit acceptance boundaries, coverage, edge cases,
  invariants, and failure behavior

Lead/support:

- `A` leads
- `B` supports

How rigor is preserved:

- specs stay close to requirements while context is hot
- `B` pressure-tests precision, completeness, and edge coverage

### Implementation plan

Goal:

- turn `requirements` and `test-specs` into a buildable execution map

Lead/support:

- `B` leads
- `A` supports

How rigor is preserved:

- `B` drives sequencing, decomposition, and dependency realism
- `A` checks that execution still serves the intended outcome and value

## Failure modes

- requirements stay vague and shift silently downstream
- specs become implementation-shaped rather than intent-shaped
- the plan is written from one upstream artifact and drifts from the other
- support becomes passive instead of actively challenging the artifact

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md —
  operational steps for executing the prepare phase
