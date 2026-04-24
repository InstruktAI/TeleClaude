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
- Humans may enter directly at the input or requirements boundary, but prepare
  must always converge to explicit artifacts before work begins.
- Automation supplies supporting facts for judgment; it does not decide scope,
  trade-offs, or design quality on its own.

## Primary flows

### Human touchpoints

Prepare begins from a human problem impulse.

Typical patterns:

- the human provides minimal `input`, then AI develops the prepare artifacts
- the human co-drives requirements directly with AI, effectively skipping a
  separate low-fidelity input handoff

In both cases, rigor comes from converging to explicit artifacts rather than
from preserving the original shape of the handoff.

### Requirements

Goal:

- capture the real problem, intended outcome, constraints, and scope

Lead/support:

- `A` leads
- `B` supports

How rigor is preserved:

- `A` keeps intent and meaning honest
- `B` pressure-tests ambiguity, contradiction, and feasibility

Automation supplies:

- structural context where available
- codebase facts, dependency facts, and other mechanically derivable support

Human/AI touchpoint:

- humans may directly shape requirements here
- AI carries most drafting and refinement work once the handoff is explicit

Exit condition:

- the requirements artifact is concrete enough that downstream acceptance can be
  specified without relying on implicit memory or conversational residue

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

Automation supplies:

- structural and test-adjacency context where available
- supporting evidence about touched boundaries, known contracts, and existing
  test surfaces

Human/AI touchpoint:

- AI does most of the specification work
- humans enter when acceptance itself requires judgment, clarification, or
  reprioritization

Exit condition:

- the acceptance boundary is explicit enough that implementation cannot honestly
  claim success by satisfying only a narrow or convenient subset of intent

### Implementation plan

Goal:

- turn `requirements` and `test-specs` into a buildable execution map

Lead/support:

- `B` leads
- `A` supports

How rigor is preserved:

- `B` drives sequencing, decomposition, and dependency realism
- `A` checks that execution still serves the intended outcome and value

Automation supplies:

- supporting structural context
- impact and dependency evidence where available
- freshness and scope inputs that can be computed mechanically

Human/AI touchpoint:

- AI does most plan decomposition and sequencing
- humans enter when sequencing, trade-offs, or risk acceptance need explicit
  judgment

Exit condition:

- the plan is buildable, realistic, and still faithful to both requirements and
  test specs

### Prepare emphasis matrix

| Artifact              | Main question                                     | Lead | Support | Rigor mechanism                                                        |
| --------------------- | ------------------------------------------------- | ---- | ------- | ---------------------------------------------------------------------- |
| `requirements`        | What problem are we truly solving?                | `A`  | `B`     | intent is challenged for ambiguity, contradiction, and feasibility     |
| `test-specs`          | What must be true before we can call this solved? | `A`  | `B`     | acceptance stays hot to intent and is pressure-tested for completeness |
| `implementation-plan` | How do we realize that truth in a buildable way?  | `B`  | `A`     | execution structure is challenged for fidelity to intended outcome     |

## Failure modes

- requirements stay vague and shift silently downstream
- specs become implementation-shaped rather than intent-shaped
- the plan is written from one upstream artifact and drifts from the other
- support becomes passive instead of actively challenging the artifact
- automation is mistaken for judgment and allowed to set scope or accept weak
  reasoning on its own

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md —
  operational steps for executing the prepare phase
