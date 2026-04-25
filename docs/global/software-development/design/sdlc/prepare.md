---
id: 'software-development/design/sdlc/prepare'
type: 'design'
domain: 'software-development'
scope: 'global'
description: 'Prepare phase design: pair-based discovery, turn-based artifact production, and human approval boundaries.'
---

# Prepare — Design

## Required reads

- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define how the prepare phase produces the aligned artifacts that downstream work
must consume.

Prepare exists to turn a problem impulse into build-ready truth. It does this
through a persistent pair of workers who explore the problem together and then
produce artifacts in turns.

## Inputs/Outputs

**Inputs**

- whatever the todo carries: a brain dump (`input`), existing `requirements`,
  or any other starting state — all treated as input to the process
- the codebase (ground truth)
- the roadmap (signal about project direction and adjacent work)
- applicable documentation and domain context

**Outputs**

- `requirements`
- `test-specs`
- `implementation-plan`

## Invariants

- `requirements` and `test-specs` remain in the same hot scope.
- `implementation-plan` is derived from both `requirements` and `test-specs`.
- Each artifact is only considered ready when the other pair member has reviewed
  and accepted it.
- The human approves requirements before downstream work begins.
- Prepare must not hand downstream work a cold reinterpretation of upstream
  truth.
- Automation supplies supporting facts for judgment; it does not decide scope,
  trade-offs, or design quality on its own.

## Primary flows

### The pair

Prepare is done by a persistent pair of two workers. They stay together across
the full prepare flow.

Each worker naturally brings a different lens:

- `A`: intent, scope, meaning, outcome fidelity
- `B`: rigor, precision, structure, execution realism

The lenses describe who they ARE, not a role they are assigned. During
discovery, there are no roles — both explore freely through their natural
perspective. Roles (writer, reviewer) are assigned only when it is time to
produce an artifact.

### Discovery (pair-based)

Both workers explore the problem together. No roles, no assignments. They read
the input, check the codebase, check the roadmap, surface hidden assumptions,
challenge each other's thinking, and converge on understanding.

This is how humans work: they discuss first. The quality comes from two
perspectives seeing what one would miss.

Discovery is the only pair-based step. It produces shared understanding, not an
artifact. The artifact comes after.

### Artifact production (turn-based)

After discovery, artifacts are produced in turns: one writes, the other reviews.

The writer records what was discussed and agreed on. The reviewer checks whether
the recording is complete and accurate. The review is lightweight because the
reviewer was present during discovery — it is confirmation, not cold evaluation.

| Artifact              | Writer | Reviewer | What is checked                                     |
| --------------------- | ------ | -------- | --------------------------------------------------- |
| `requirements`        | `A`    | `B`      | Did the writer capture the full discussed intent?   |
| `test-specs`          | `A`    | `B`      | Do the specs cover what was agreed on?              |
| `implementation-plan` | `B`    | `A`      | Is the execution plan faithful to intent and specs? |

### Human approval

The human approves requirements before downstream work begins. This is explicit
and non-optional.

After the pair writes and reviews requirements, the human reads them. The human
may talk directly to the writer to add or correct things. When the human is
satisfied, the orchestrator stamps approval and the machine continues.

The human is part of the loop, not an afterthought.

### Gate (pair self-assessment)

After all artifacts are produced and reviewed, the pair checks their own work
against Definition of Ready. This is self-assessment — the pair evaluates
whether what they produced is actually ready to build. It is not an external
audit by a third party.

## Failure modes

- requirements stay vague because discovery was shallow or cut short
- the writer misses something from the discussion and the reviewer does not
  catch it
- specs become implementation-shaped rather than intent-shaped
- the plan drifts from requirements and specs because it was written without
  the full upstream context
- human approval is skipped or treated as a rubber stamp
- automation is mistaken for judgment and allowed to set scope or accept weak
  reasoning on its own

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md —
  the actual process steps for executing prepare
