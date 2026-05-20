---
description: 'Prepare phase design: one driving session loads phase-scoped procedures in sequence, produces the prepare artifacts (PRD, architecture doc-snippet edits + thin index, implementation plan), and submits each derived artifact to a cross-model reviewer. PRD is the only human approval gate.'
domain: 'software-development'
id: 'software-development/design/sdlc/prepare'
scope: 'global'
type: 'design'
visibility: 'public'
---

# Prepare — Design

## Required reads

- @~/.teleclaude/docs/software-development/design/sdlc/overview.md

## Purpose

Define how the prepare phase produces the aligned artifacts that downstream
work must consume.

Prepare exists to turn a problem impulse into build-ready truth. One session
drives the whole prepare lifecycle. The session loads a phase-scoped procedure for
each step in the chain — intake, architecture, plan — and does the
work for that step itself. Each derived artifact is verified by a cross-model
reviewer running in a separate dispatched session. The PRD is verified by the
human, who is the sole authority on intent.

## Inputs/Outputs

**Inputs**

- whatever the todo carries: a brain dump (`input`), existing artifacts, or
  any other starting state — all treated as input to the process
- the codebase (ground truth)
- the roadmap (signal about project direction and adjacent work)
- applicable documentation and domain context
- session `additional_context` carrying `human_in_loop: true | false`

**Outputs**

- `prd` (intake) — plus the feature spec snippet with Gherkin for Category A work
- architecture: domain-spec / architecture-v2 design-doc snippet updates plus a thin `architecture` index artifact (when not skipped)
- `implementation-plan`

## Invariants

- One session drives the whole prepare lifecycle. The same session loads
  each phase's procedure, does the phase's work, advances the state machine, and
  loads the next procedure when the state machine routes there.
- Each phase has its own focus, sharpened by a hat. Intake = BA hat
  (`~/.teleclaude/commands/next-prepare-intake.md`). Architecture = Architect hat
  (`~/.teleclaude/commands/next-prepare-architecture.md`). Plan = Planner hat (`~/.teleclaude/commands/next-prepare-plan.md`). The
  hat is the loaded procedure; the lifecycle awareness underneath persists
  across hats.
- Reviewers are cross-model and dispatched. Each derived artifact
  (architecture, plan) is reviewed by a separately-dispatched
  cross-model session. The active procedure dispatches the reviewer,
  tails it, and reads its findings and verdict on the next state-machine
  advance.
- The PRD is the only human approval gate. The human reviews the PRD and
  stamps `prd_approved`. Architecture and plan advance on
  reviewer verdict alone.
- The architecture phase may be skipped when it doesn't earn its place.
  During intake, the BA stamps `architecture_skipped` with
  reason when the work doesn't warrant the phase. Plan and PRD are
  non-skippable.
- Each phase grounds in the prior phase's output. Human refinement at any
  layer invalidates downstream approvals and re-enters the affected phase.
- Automation supplies supporting facts for judgment; it does not decide
  scope, trade-offs, or design quality on its own.
- **Gherkin (`Given / When / Then`) belongs in the feature spec snippet, not in `prd`.**
  PRD success criteria are outcome-shaped in the product owner's language —
  observable indicators of success without pre-imposing the test author's
  grammar. For Category A work, intake authors the Gherkin behavioral
  contract directly into the feature spec snippet (derived from those
  outcome-shaped criteria); for Category B/C work there is no Gherkin
  artifact. Carrying Gherkin in the PRD pushes the PO into a downstream
  author's format.

## Primary flows

### The chain

The state machine drives a deterministic phase chain. Each phase is one focus
turn of the same driving session.

| Phase        | Procedure                                             | Hat       | Authority gate                          |
| ------------ | ----------------------------------------------------- | --------- | --------------------------------------- |
| Intake       | `~/.teleclaude/commands/next-prepare-intake.md`       | BA        | `prd_approved` (real human only)        |
| Architecture | `~/.teleclaude/commands/next-prepare-architecture.md` | Architect | `architecture_review` verdict `approve` |
| Plan         | `~/.teleclaude/commands/next-prepare-plan.md`         | Planner   | `plan_review` verdict `approve`         |

Each phase ends by calling `telec todo prepare {slug}`. The state machine
routes the next action — load the next procedure, dispatch a reviewer, pause for
human approval, or terminate at `PREPARED` / `BLOCKED`.

### Intake

The BA interviews the Product Owner (real human, or a dispatched PO emulator
in standin mode) and fills the PRD template via elicitation. PRD success
criteria are outcome-shaped, in PO language. For Category A work the BA also
authors the feature spec snippet's Gherkin acceptance scenarios. When the
work warrants it, the BA stamps `architecture_skipped` with reason. The BA
writes the PRD and presents it to the human for review and approval. The
human is the sole authority on PRD correctness because only the human owns
intent.

In standin mode, the BA writes the PRD but cannot stamp `prd_approved`. The
chain pauses at the approval gate until the real human re-engages with the
slug.

### Derivation phases (architecture, plan)

For each derivation phase, the same session loads the phase's procedure, grounds
in upstream artifacts, produces the phase artifact, and advances the state
machine. The state machine then dispatches a cross-model reviewer. The
active procedure tails the reviewer; on `approve` the chain advances; on
`needs_work` the active procedure addresses the findings and advances again to
re-dispatch the reviewer.

### Standin mode

When session `additional_context` carries `human_in_loop: false`, intake
dispatches a Product Owner emulator (`/next-emulate-po`) as the BA's
interviewee. The BA writes a PRD that captures what an experienced PO would
propose given the input plus standing wishes for quality. The BA does not
stamp `prd_approved` — that gate is the real human's. The chain pauses at
PRD approval until the real human engages. Once the PRD is approved, all
other phases (architecture, plan) proceed under reviewer authority.

### Refinement

When the human refines an artifact, the change classifies into one of four
scopes:

- **Intent-level** (new thinking, scope changes) → re-enter intake with the
  delta. Downstream approvals invalidated.
- **Architecture-level** (design-snippet change) → re-enter architecture
  phase. Plan approval invalidated.
- **Plan-level** (task adjustment) → re-enter plan phase.

### Drift

When reconciliation detects that artifact-referenced paths changed since the
artifact was authored, a lean `/next-drift-analyze` worker is dispatched. It
stamps each pending artifact as `cosmetic` or `substantive`. Substantive
drift invalidates the affected phase and the active procedure re-derives. The
PREPARED terminal requires fresh grounding.

## Failure modes

- PRD success criteria stay vague because intake elicitation was shallow.
- The BA front-loads Gherkin into the PRD instead of the feature spec
  snippet, pushing the PO into a test author's grammar.
- A procedure drifts into orchestrator-shaped action (dispatching workers
  for sub-phases) instead of doing the phase work itself.
- A standin-produced PRD is auto-stamped `prd_approved` without the real
  human's review.
- Reviewer findings cannot be addressed by the active procedure, and the
  chain grinds rather than surfacing the blocker.
- Drift is detected but the affected phase isn't re-derived, leaving
  downstream artifacts grounded in stale upstream truth.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md —
  the executable procedure for driving the prepare lifecycle
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
