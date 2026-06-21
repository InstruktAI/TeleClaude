---
description: 'Prepare stage overview. Lifecycle scaffolding for the one session that drives the derivation chain (PRD → Architecture → Plan) with PRD-only human approval, reviewer-gated derivation artifacts, and standin mode for autonomous intake.'
visibility: 'public'
needs_domain_baseline: true
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/general/concept/orchestrator.md
- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md

## Goal

Drive a todo through the prepare phase from initial intent capture to a state
where the work is ready for the build phase. One session drives the whole
chain. Each phase loads its procedure, does its focused work, and advances the
state machine. The state machine decides what happens next.

### Defaults — read these once and carry them through every phase

1. **One session drives the whole prepare lifecycle.** The session you are
   in loads each phase's procedure in turn, does the work itself, advances the
   state machine, and loads the next procedure when the state machine routes
   there.

2. **Each phase has its own focus, sharpened by a hat:**
   - **BA hat** for intake — loaded by reading `~/.teleclaude/commands/next-prepare-intake.md`
   - **Architect hat** for architecture — loaded by reading `~/.teleclaude/commands/next-prepare-architecture.md`
   - **Planner hat** for plan — loaded by reading `~/.teleclaude/commands/next-prepare-plan.md`

   Putting on a hat sharpens focus for the current phase; it does not erase
   the lifecycle awareness underneath. The hat comes off when the phase ends
   and the next procedure loads.

3. **Reviewers are cross-model and dispatched.** When the state machine
   routes to a review step, dispatch the reviewer as a separate session via
   `telec sessions run` and tail it. The reviewer writes its findings to the
   findings artifact and a verdict to its review stamp; the active phase
   procedure reads them on the next state-machine advance.

4. **Human approval is on the PRD only.** The human reviews the PRD and
   stamps `prd_approved`. The human is the sole authority on intent.
   Architecture and plan advance on reviewer verdict alone.

## Preconditions

- Slug exists in the todo list, or is created during the session at the moment
  intent is concrete enough.
- Session was invoked via `/next-prepare [slug]` (direct human invocation) or
  auto-spawned by the daemon (dump-mode entry).
- Session `additional_context` carries `human_in_loop: true | false`.
  Default `true`.

## Steps

### 1. Pre-flight input viability

Before calling the state machine, read the `input` artifact and decide whether
intake can proceed at all. This gate exists because intake — especially in
standin mode — will otherwise invent scope from a sparse or accidental input,
producing artifacts that look real but encode nothing.

Read the input via `telec todo artifacts read {slug} input`. Apply the
viability check:

- **Hard-stop signals** (any one disqualifies the input as-is):
  - Input is a single short phrase or noun phrase with no goal, no actor, no
    outcome — fewer than ~10 meaningful words.
  - Slug carries a raw timestamp suffix (e.g., `…-1778958052`) indicating an
    auto-generated dump, with no companion context from a prior session.
  - Input is empty, placeholder text, or matches a known smoke-test pattern.

- **Mode-dependent resolution:**
  - `human_in_loop: false` (standin) → **hard-stop and escalate.** Do not
    dispatch intake. The PO emulator has no way to fill the gap and a human
    cannot sanity-check the result. Surface to the user: "Input too sparse
    for standin mode; needs human elaboration or removal." Stop the prepare
    flow.
  - `human_in_loop: true` → **soft-stop and elicit from the user before
    dispatch.** Point the user at `@input` (do not paste it back), name the
    gap, ask one direct question to surface the goal/actor/outcome. Update
    the input artifact with the elaborated text, then proceed.

Substantive inputs (clear intent, concrete outcome, identifiable actor — even
if short) pass the gate and proceed to Step 2.

### 2. Call the state machine

Call `telec todo prepare {slug}`. The machine returns a verbatim execution
script for the current phase. The script describes either a procedure load (load
the next phase's procedure and do its work), a reviewer dispatch (dispatch a
cross-model reviewer and tail it), an approval pause (present to the real
human and wait), or a terminal state (`PREPARED` or `BLOCKED`).

Execute the script verbatim. The script's flexibility belongs to
in-conversation moments with the user: fresh questions, refinements, scope
clarifications.

### 3. Load the recommended procedure and do the work

When the state machine routes you to a phase, load the corresponding procedure
and do its focused work. Each procedure ends by calling `telec todo prepare
{slug}` to advance — that's how the lifecycle proceeds.

| Phase        | Procedure                                             | Hat       |
| ------------ | ----------------------------------------------------- | --------- |
| Intake       | `~/.teleclaude/commands/next-prepare-intake.md`       | BA        |
| Architecture | `~/.teleclaude/commands/next-prepare-architecture.md` | Architect |
| Plan         | `~/.teleclaude/commands/next-prepare-plan.md`         | Planner   |

### 4. Honor the PRD approval gate

The PRD is the only artifact gated by human approval. When intake produces
the PRD, present it to the real human for review and approval. On confirm,
stamp `prd_approved` (only the real human can — standin cannot stamp this).
On refine, capture the delta, rewrite the PRD, present again.

In standin mode, the BA writes the PRD but cannot stamp `prd_approved` — the
chain pauses at this gate until the real human engages with the slug.

### 5. Skip phases that don't earn their place

At intake, the BA assesses size and stamps a skip with reason when warranted:

- `architecture_skipped: <reason>` — e.g., "single-file change, no
  cross-service implications."

The state machine respects the skip when deriving the current phase.

### 6. Handle drift

When the state machine reports drift (codebase changed in artifact-referenced
paths since the artifact was authored), dispatch a lean drift-analysis
worker:

```
telec sessions run --command /next-drift-analyze --agent codex --args {slug}
```

The worker reads the diffs scoped to referenced paths, assesses impact per
affected artifact, and reports findings. The `/next-drift-analyze` worker is
the sole author of `--drift-reviewed`. Substantive verdicts trigger
re-derivation of the affected phase; cosmetic verdicts allow the chain to
continue.

### 7. Handle refinement

When the human refines (proposes changes to an artifact at any layer),
classify the refinement scope and re-enter the appropriate phase:

- **Intent-level** (new thinking, scope changes) → re-enter intake with the
  delta. Downstream approvals invalidated.
- **Architecture-level** (design-snippet change) → re-enter architecture
  phase. Plan approval invalidated.
- **Plan-level** (task adjustment) → re-enter plan phase. No further
  downstream to invalidate.

Clear the relevant approval stamps and re-run the affected phases.

### 8. Terminal state

When all required phases have approval stamps and grounding is fresh, the
state machine derives `PREPARED`. Report to the user and hand off to the work
phase.

If reviewer verdicts cannot be resolved through normal revision rounds, or if
drift cannot be cleanly re-derived, the state machine derives `BLOCKED`.
Surface the blocker to the human for direction.

## Outputs

- `prd` artifact, human-approved.
- `architecture` — domain-spec / architecture-v2 design-doc snippet updates
  plus a thin index artifact logging them, reviewer-approved (unless skipped).
- `implementation-plan` artifact, reviewer-approved.
- Grounding stamps reflecting fresh codebase reference.
- The state machine reports `PREPARED` (or `BLOCKED` with reasons).

## Recovery

- **Input fails the viability gate in standin mode.** Do not dispatch intake.
  Surface the gap to the user by referencing `@input` (do not paste its
  text), and recommend either elaboration (re-dump with substance) or
  removal (`telec todo remove {slug}`). The prepare flow stops until the
  input is fixed or the todo is removed.
- **Input fails the viability gate in human-in-loop mode.** Stop before
  dispatch, reference `@input` (do not paste it), and ask one direct
  question to surface the missing goal/actor/outcome. Update the input
  artifact with the human's elaboration, then proceed from Step 2.
- **State machine returns an unfamiliar recommendation.** Surface this to the
  user; do not improvise.
- **Procedure loading fails.** Report the failure; do not proceed without the
  procedure loaded.
- **Reviewer dispatch fails repeatedly.** Surface as a blocker; do not grind
  without reviewer verification.
- **Human disengages mid-flow.** State machine retains current state; next
  session resumes where things were left.
- **Conflict between standin-produced artifact and real human's intent.**
  When the human refines a standin-produced artifact substantially, treat
  the refinement as authoritative and re-derive downstream — even if
  downstream had already been auto-produced in standin mode. The human's
  stamp is the source of truth.

## See Also

- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/plan-draft.md
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md
