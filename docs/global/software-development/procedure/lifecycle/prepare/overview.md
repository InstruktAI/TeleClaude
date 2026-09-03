---
description: 'Prepare-stage orchestration. Audit intent, enter the kind-specific preparation lane, and drive its state-machine-owned derivation and review cycle to PREPARED or BLOCKED.'
activation_trigger: 'Use when asked to prepare a todo, become its prepare orchestrator, or drive telec todo prepare for a slug.'
visibility: 'public'
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/domain-baseline-bundle.md
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

Route a todo into the preparation lane defined by its kind and drive that lane
from initial intent capture to its ready state. Feature, change, and bug work
use the prepare state machine; task work diverts to its non-SDLC task-plan
procedure. One session retains ownership while each routed phase loads its
focused procedure and advances through the machine-owned transitions.

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

<!-- planned:review-round-cap-all-loops -->
   Each PRD, architecture, and plan review phase admits reviewer passes through
   `DEFAULT_MAX_REVIEW_ROUNDS`. The machine persists the count before returning each
   reviewer instruction, and neither target nor report rewrites reset it. At
   the limit it returns `REVIEW_ROUND_LIMIT`, emits no reviewer instruction,
   and leaves the active prepare session as the beacon. Only a direct human
   `--review-round-override <phase>` stamp admits the next pass; every pass
   beyond the current allowance requires another human stamp.
<!-- /planned:review-round-cap-all-loops -->

4. **Human PRD approval belongs to the feature lane only.** A drafted feature
   PRD first passes `prd_review`; the human then judges product intent and
   stamps `prd_approved`. Architecture and implementation plans advance on
   reviewer verdict alone. Task-plan authorization follows the separate task
   procedure and is not a PRD approval.

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
  `telec todo create <slug> <content> --kind <kind> --hold --reason "<why this waits, or the gate or owner it waits on>"`.
  The `--hold` keeps the runner from claiming the new todo before you continue,
  while the reason records why the brake exists. Then continue as the owning
  prepare orchestrator from Step 1.
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

### 0a. Audit the creation record and input

Before deriving intent or calling the state machine, audit the todo against the
current `input` and its mechanically recorded creation record. The creation
record establishes how the todo entered the system and which session lineage
carried it; it does not establish what a human decided, and this audit never
inspects the creating session's transcript to find out. Whether the creator
faithfully relayed the human is the human's own audit, out of prepare's scope.

1. Read the creation record and the current `input`.
2. Take the `input` as the authorized basis for derivation. Its content is the
   creating agent's shaping of the work, which is trusted like any agent's; a
   clause carried under a `HUMAN-DECISION:` marker relays the human's own word
   and is likewise taken as given. Do not investigate either.
3. Derive the work from that basis by kind — the outcome and constraints for
   `feature` and `change`; the reported concern, symptom, and
   expected-versus-observed behavior for `bug`, where causal and scope claims
   remain hypotheses diagnosis still tests; the action boundary, result,
   recipient, and timing for `task`; and the same for a kind-less todo before
   classification.
4. A technical choice needed for safe and correct delivery is plan and build's
   to make; it is not enlarged into product or business intent merely because
   the input mentions it. This is a scope discipline on derivation, not a test
   of whether the human said it.
5. Establish the owning project, repeat the bounded overlap check when its
   evidence is absent, apply the governing creation and process-authority
   contracts, and confirm that functionality work carries its required pending
   documentation.
6. If the input changes later in the prepare flow, repeat this audit before
   deriving from the revision.

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
- **The current process-layer doc contract already binds every implied
  behavior** → proceed to Step 2. The input may point to that contract as
  implementation scope; a `HUMAN-DECISION:` marker is neither required nor
  process authority.
- **Delivering the input requires process behavior beyond the current doc
  contract** → **refuse to prepare.** Do not advance the state machine or carry
  the change through the todo under a marker. Surface the exact missing snippet
  delta under the policy's escalation shape so it can be decided and authored
  in a human-present session; resume only after that contract is live.

### 1b. Route by todo kind

Read the todo's recorded kind and enter only the lane it owns. Kind determines
which preparation artifacts exist; the feature chain is not a universal
template.

| Kind      | Entry route                                                                                                | Preparation outputs                                                                                  |
| --------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `feature` | Intake → PRD review and human approval → optional architecture and review → implementation plan and review | `prd`, behavioral feature-spec reflection, optional `architecture`, `implementation-plan`            |
| `change`  | Implementation-plan drafting and review                                                                    | `implementation-plan`; no PRD or feature intake                                                      |
| `bug`     | Independent diagnosis → implementation-plan drafting and review                                            | `diagnosis`, `implementation-plan`; no PRD or feature intake                                         |
| `task`    | Load `software-development/procedure/lifecycle/task/prepare-task` and leave this SDLC flow                 | `task-plan` plus human authorization; no PRD, architecture, implementation plan, or reviewer verdict |

If the recorded kind does not match the intent, reclassify it with `telec todo
update {slug} --kind <feature|change|bug|task>` before deriving artifacts. Never
force an intent through the wrong lane to preserve an already chosen kind.

### 2. Call the state machine

For `feature`, `change`, and `bug`, call `telec todo prepare {slug}`. The
machine returns a verbatim execution script for the current phase. The script
describes either a procedure load (load
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

| Phase               | Kind(s)              | Procedure                                             | Focus                       |
| ------------------- | -------------------- | ----------------------------------------------------- | --------------------------- |
| Intake              | Feature              | `~/.teleclaude/commands/next-prepare-intake.md`       | BA                          |
| PRD review          | Feature              | `~/.teleclaude/commands/next-review-prd.md`           | Reviewer                    |
| Diagnose            | Bug                  | `~/.teleclaude/commands/next-prepare-diagnose.md`     | Diagnoser (dispatched peer) |
| Architecture        | Feature              | `~/.teleclaude/commands/next-prepare-architecture.md` | Architect                   |
| Architecture review | Feature              | `~/.teleclaude/commands/next-review-architecture.md`  | Reviewer                    |
| Plan                | Feature, change, bug | `~/.teleclaude/commands/next-prepare-plan.md`         | Planner                     |
| Plan review         | Feature, change, bug | `~/.teleclaude/commands/next-review-plan.md`          | Reviewer                    |

Intake's focused work includes situating the premise against the existing todo
landscape — reconciling overlap and undeclared dependencies with sibling todos
before scoping (intake procedure, step 1.6).

### 4. Honor the feature PRD approval gate

In the feature lane, the PRD is the only SDLC artifact gated by human approval, and internal review
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

In feature intake, the BA assesses size and stamps a skip with reason when warranted:

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

Doctrine drift is not machine-detected. On resuming a todo whose artifacts
were reviewed before a change to applicable doctrine — a principle, policy, or
procedure the artifact is judged against — re-read the artifact against the
doctrine changed since its last review. Doctrine drift alone never invalidates
an approval; only a material conflict between the artifact and current doctrine
triggers kickback and re-review of the affected phase.

### 7. Handle refinement

When the human refines (proposes changes to an artifact at any layer),
classify the refinement scope and re-enter the appropriate phase:

- **Intent-level** (new thinking, scope changes) → repeat kind routing. A
  feature re-enters intake; a change re-enters plan; a bug re-enters diagnosis
  or plan according to whether the causal conclusion changed. Invalidate the
  affected downstream approvals.
- **Architecture-level** (design-snippet change in a feature) → re-enter
  architecture. Plan approval invalidated.
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

- Every lane begins from the `input` as its authorized basis, with any
  `HUMAN-DECISION:` marker taken as given.
- Feature: digest-bound `prd_review`, human-approved `prd`, behavioral feature
  spec reflection, optional reviewer-approved `architecture`, and a
  reviewer-approved `implementation-plan`.
- Change: reviewer-approved `implementation-plan`, with no PRD or feature
  intake artifacts.
- Bug: independently authored `diagnosis` followed by a reviewer-approved
  `implementation-plan`, with no PRD or feature intake artifacts.
- Task: a `task-plan` and human authorization request from the task procedure;
  no SDLC prepare-state-machine output.
- SDLC lanes carry fresh grounding stamps and end in `PREPARED` or `BLOCKED`.

## Recovery

- **Creation record is absent or incomplete.** Derive from the input and prior
  artifacts directly; never solicit an attestation from the creator.
- **The input is too thin to derive from.** Recover intent from the input, the
  creation record, and prior artifacts; do not manufacture product detail. If no
  defensible basis remains, stop before kind-specific derivation and surface the
  gap — never by inspecting the creating session.
- **A bug concern is faithfully recovered but not yet proven.** Proceed to
  diagnosis. Filing fidelity establishes what was reported, not whether the
  report is correct or what caused it.
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
  artifact with the human's elaboration, then repeat the authority and kind
  gates before entering the routed lane.
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
