---
id: 'software-development/procedure/lifecycle/prepare/overview'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Prepare stage overview. The orchestrator drives a four-step derivation chain (PRD → Architecture → Test specs → Plan) with human approval gates, skip-when-warranted, and standin mode for autonomous intake.'
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/stewardship.md
- @~/.teleclaude/docs/general/principle/calibration.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md

## Goal

Drive a todo through the prepare phase from initial intent capture to a state where the work is ready for the build phase. The chain has four derivation steps, each producing an artifact, each gated by reviewer verdict and human approval. Phases that don't earn their place for a specific work item are skipped explicitly with reason; phases that do earn their place run with the same shape every time.

The orchestrator drives. The state machine reports current state and recommends the next step. The orchestrator loads the skill for that step (which carries the skill's required reads), does the work, and stamps the appropriate progress. Phase boundaries are deterministic; the work within each phase is adaptive to the specific intent.

## Preconditions

- Slug exists in the roadmap, or is created during the session at the moment intent is concrete enough.
- Session was invoked via `/next-prepare [slug]` (direct human invocation) or auto-spawned by the daemon (dump-mode entry).
- Session `additional_context` carries `human_in_loop: true | false`. Default `true`.

## Steps

### 1. Orient

Call `telec todo prepare {slug}` (or query the state machine equivalently). The machine returns the current state — what stamps exist, which artifacts are present, what's outstanding, and a recommended next step with required reads.

The orchestrator reads the recommendation and decides whether to act on it. The recommendation is advisory, not prescriptive. If a fresh human question takes priority, answer that first; come back to the recommendation when ready.

### 2. Run the recommended next step

The recommendation maps to one of the phase skills. The orchestrator loads the relevant skill, which inlines its required reads. Phase skills:

| Phase | Skill / command loaded |
| --- | --- |
| Intake | `/next-prepare-intake` (loads `prepare/intake.md` procedure) |
| Architecture | `/next-prepare-architecture` (loads `prepare/architecture.md`) |
| Test specs | `/next-prepare-specs` (loads `prepare/prepare-specs.md`) |
| Plan | `/next-prepare-plan` (loads `prepare/plan-draft.md`) |
| Reviewer dispatch | `/next-review-architecture`, `/next-review-specs`, `/next-review-plan` |

The orchestrator runs the phase to completion (artifact written, reviewer verdict, human approval) before calling the state machine again for the next recommendation.

### 3. Honor the approval gates

Each artifact has a human approval gate. The orchestrator stamps the approval only after the real human (not a standin) confirms. In standin mode, the orchestrator may produce artifacts but cannot stamp human-approval — the chain pauses at the approval gate until the real human engages.

When the real human re-engages a standin-paused todo via `/next-prepare {slug}`, the state machine recognizes the situation and recommends presenting the standin-produced artifact for approval. Standard refinement loop applies from there.

### 4. Skip phases that don't earn their place

At intake, and at each phase boundary thereafter, the orchestrator assesses whether the next phase earns its place for this specific work. When it doesn't, the orchestrator stamps the skip with reason:

- `architecture_skipped: <reason>` — e.g., "single-file change, no cross-service implications."
- `test_specs_skipped: <reason>` — e.g., "trivial behavior change covered by existing tests."

The state machine respects skips when deriving the current layer.

### 5. Handle drift

When the state machine reports drift (codebase changed in artifact-referenced paths since the artifact was authored), the orchestrator dispatches a lean drift-analysis worker:

```
telec sessions run --command /next-drift-analyze --agent codex --args {slug} --detach
```

The worker reads the diffs scoped to referenced paths, assesses impact per affected artifact, and reports findings. The orchestrator integrates: substantive drift triggers re-derivation of the affected layer; cosmetic drift is noted but doesn't invalidate approval.

### 6. Handle refinement

When the human refines (proposes changes to an artifact at any layer), the orchestrator classifies the refinement scope:

- **Intent-level** (new thinking, scope changes) → re-enter intake with the delta. Downstream approvals invalidated.
- **Architecture-level** (technical brief change) → re-enter architecture phase. Specs and plan approvals invalidated.
- **Specs-level** (behavior contract change) → re-enter specs phase. Plan approval invalidated.
- **Plan-level** (task adjustment) → re-enter plan phase. No further downstream to invalidate.

The orchestrator clears the relevant approval stamps and re-runs the affected phases.

### 7. Terminal state

When all required phases have approval stamps and grounding is fresh, the state machine derives `PREPARED`. The orchestrator reports to the user and hands off to the work phase.

If reviewer verdicts cannot be resolved through normal revision rounds, or if drift cannot be cleanly re-derived, the state machine derives `BLOCKED`. The orchestrator surfaces the blocker to the human for direction.

## Outputs

- `prd` artifact, human-approved.
- `architecture` artifact, human-approved (unless skipped).
- Test specs, human-approved (unless skipped).
- `implementation-plan` artifact, human-approved.
- Grounding stamps reflecting fresh codebase reference.
- The state machine reports `PREPARED` (or `BLOCKED` with reasons).

## Recovery

- **State machine returns an unfamiliar recommendation.** Orchestrator surfaces this to the user; doesn't improvise.
- **Phase skill loading fails.** Orchestrator reports the failure; doesn't proceed without the skill loaded.
- **Reviewer dispatch fails repeatedly.** Surface as a blocker; don't grind without reviewer verification.
- **Human disengages mid-flow.** State machine retains current state; next session resumes where things were left.
- **Conflict between standin-produced artifact and real human's intent.** When the human refines a standin-produced artifact substantially, the orchestrator treats the refinement as authoritative and re-derives downstream — even if downstream had already been auto-produced in standin mode. The human's stamp is the source of truth.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
