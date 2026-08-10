---
description: 'Prepare stage overview. Lifecycle scaffolding for the one session that drives the derivation chain (PRD → Architecture → Plan) with PRD-only human approval, reviewer-gated derivation artifacts, and standin mode for autonomous intake.'
visibility: 'public'
needs_domain_baseline: true
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/general/concept/orchestrator.md
- @~/.teleclaude/docs/general/procedure/orchestration.md
- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md
- @~/.teleclaude/docs/general/policy/human-involvement-recording.md

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

4. **Human approval is on the independently reviewed PRD only.** A drafted PRD
   first passes `prd_review`; the human then judges product intent and stamps
   `prd_approved`. Architecture and plan advance on reviewer verdict alone.

The bug lane is the one named exception to the first default, and it is narrow: a
dispatched peer authors the `diagnosis`, investigating and concluding in one act, while
the driving session triages before that peer is spent, interrogates the written mechanism
after as a skeptical examiner rather than a second diagnostician, stamps the cause once
every causal transition is evidenced and the strongest rival is eliminated, and resumes as
planner from a conclusion it did not write. The driver stays alive while its peer is active and does not poll it;
normal completion or material communication wakes the next action. See
`software-development/procedure/lifecycle/prepare/diagnose`.

## Preconditions

- Slug exists in the todo list, or is created during the session at the moment
  intent is concrete enough.
- Session was invoked via `/next-prepare [slug]` (direct human invocation) or
  auto-spawned by the daemon (dump-mode entry).
- Session `additional_context` carries `human_in_loop: true | false`.
  Default `true`.

## Steps

### 0. Resolve the entry mode

Before doing anything else, resolve which of three live-entry modes this session
is in — the slug's presence and the human's presence determine the posture:

- **No slug + human present.** The conversation itself is the source for
  `@input`. Shape a concrete todo with the human, and once the intent is
  concrete create it held with the hidden specialist control
  `telec todo create <slug> <content> --kind <kind> --hold`. The `--hold`
  keeps the runner from claiming the new todo before you continue, so you keep
  ownership of prepare. Then continue as the owning prepare orchestrator from
  Step 1.
- **Slug + human present and no `human_in_loop: false`.** Treat this as the
  human reassessing or refining that todo, not autonomous continuation. Do not
  call `telec todo prepare {slug}` before assessing the conversation and the
  human's intent for the slug; advance only once that intent is clear, then
  proceed from Step 1.
- **Slug + `human_in_loop: false`.** Daemon standin path: proceed directly
  from the artifacts through the prepare state machine (Step 1 onward).

`--hold` is the create-time dispatch brake reserved for this orchestration
context; release it with `telec todo update <slug> --release` once the todo is
ready to enter its normal lane.

### 0a. Audit the creation record

Before deriving intent or calling the state machine, audit the todo against the
current `input` and its mechanically recorded creation evidence. The audit is
about the record, not the identity of whoever created it.

1. Read the creation record and the current `input`.
2. Inspect the actual source consultations and todo queries retained from the
   creating context. Never ask the creator to attest that a step occurred.
3. Establish the owning project, repeat the bounded overlap check when its
   evidence is absent, apply the governing creation and process-authority
   contracts, and confirm that functionality work carries its required pending
   documentation.
4. Reconcile the `input` when the evidence narrows, corrects, or completes what
   the creation record claimed. Correct the record and proceed whenever the
   intent remains defensible.
5. Continue from the reconciled input. If it changes later in the prepare flow,
   repeat this audit before deriving from the revision.

Retire only a confirmed duplicate, work whose owning project cannot be repaired
in place, unauthorized process intent, or a todo for which no defensible intent
remains. `hold` and scheduling are not changed by this audit. A task performs
the same bounded audit before entering its task-specific preparation lane.

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
if short) pass the gate and proceed to Step 1a.

### 1a. Process-change authority gate

Apply `software-development/policy/process-change-authority` before any
artifact work. Assess the input's intent against the process-layer contracts:
does delivering it require a behavioral delta to a process-layer snippet (a
`Given / When / Then` changes meaning in a lifecycle procedure, the integration
or workflow specs, the review-lane catalog, or gate composition)?

- **No process change implied** (including descriptive doc edits and restoring
  code to the current contract) → proceed to Step 2.
- **Process change implied and the intent traces to a human decision** — the
  input describes the change as the human's call and the creation record
  (`human_involved`, lineage) is consistent with that → proceed to Step 2.
- **Process change implied and no human decision behind it** → **refuse to
  prepare.** Do not advance the state machine. Escalate per the policy's
  escalation shape — the implied snippet delta, why the work demands it, the
  blast radius — and go idle as a beacon. Never self-approve, never re-derive
  approval from plausibility, never prepare "just the non-process part" of an
  intent whose core is the process change.

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

| Phase               | Procedure                                             | Focus                       |
| ------------------- | ----------------------------------------------------- | --------------------------- |
| Intake              | `~/.teleclaude/commands/next-prepare-intake.md`       | BA                          |
| PRD review          | `~/.teleclaude/commands/next-review-prd.md`           | Reviewer                    |
| Diagnose            | `~/.teleclaude/commands/next-prepare-diagnose.md`     | Diagnoser (dispatched peer) |
| Architecture        | `~/.teleclaude/commands/next-prepare-architecture.md` | Architect                   |
| Architecture review | `~/.teleclaude/commands/next-review-architecture.md`  | Reviewer                    |
| Plan                | `~/.teleclaude/commands/next-prepare-plan.md`         | Planner                     |
| Plan review         | `~/.teleclaude/commands/next-review-plan.md`          | Reviewer                    |

Intake's focused work includes situating the premise against the existing todo
landscape — reconciling overlap and undeclared dependencies with sibling todos
before scoping (intake procedure, step 1.6).

### 4. Honor the PRD approval gate

The PRD is the only artifact gated by human approval, and internal review
precedes that gate. When intake writes or rewrites the PRD, the state machine
routes to a dispatched PRD reviewer. `needs_work` returns the findings to
intake; `approve` binds the verdict to the current PRD digest and opens human
approval.

Present only the reviewed PRD, its stated horizon, and genuine human-owned
decisions. On confirm, stamp `prd_approved`. On refinement, capture the delta,
rewrite the PRD, and let the machine invalidate and rerun `prd_review` before
presenting it again.

In standin mode, agents can draft and review but cannot stamp
`prd_approved`; the chain waits for the human at the same gate.

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
state machine derives `PREPARED` and returns a terminal script whose only
action is ending this session — Step 2's "execute the script verbatim" rule
applies here too. Report `PREPARED` to the human, then end per
`general/principle/session-lifecycle`. Hand-off means ending, never calling
`telec todo work {slug}` yourself.

If reviewer verdicts cannot be resolved through normal revision rounds, or if
drift cannot be cleanly re-derived, the state machine derives `BLOCKED`.
Surface the blocker to the human for direction.

## Outputs

- An `input` reconciled to the creation evidence before derivation begins.

- A digest-bound `prd_review` verdict and `prd-review-findings` when the draft
  needs work, before human PRD approval.

- `prd` artifact, human-approved.
- `architecture` — domain-spec / architecture-v2 design-doc snippet updates
  plus a thin index artifact logging them, reviewer-approved (unless skipped).
- `implementation-plan` artifact, reviewer-approved.
- Grounding stamps reflecting fresh codebase reference.
- The state machine reports `PREPARED` (or `BLOCKED` with reasons).

## Recovery

- **Creation evidence is absent or incomplete.** Perform the missing grounding
  directly and reconcile the input; never solicit an attestation from the
  creator.
- **Input changed after creation audit.** Repeat Step 0a before deriving or
  re-deriving preparation artifacts.

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
