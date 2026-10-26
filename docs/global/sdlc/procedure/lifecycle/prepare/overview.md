---
description: 'Prepare-stage orchestration. Audit intent, enter the kind-specific preparation lane, and drive its state-machine-owned derivation and review cycle to PREPARED or BLOCKED.'
activation_trigger: 'Use when asked to prepare a todo, become its prepare orchestrator, or drive telec todo prepare for a slug.'
visibility: 'public'
role: prepare-orchestrator
parameters:
  - name: slug
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: slow
---

# Prepare Overview — Procedure

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/general/procedure/orchestration.md
- @~/.teleclaude/docs/general/concept/agent-characteristics.md
- @~/.teleclaude/docs/general/policy/commits.md
- @~/.teleclaude/docs/sdlc/policy/process-change-authority.md
- @~/.teleclaude/docs/general/policy/human-involvement-recording.md
- @~/.teleclaude/docs/sdlc/policy/todo-creation-discipline.md
- @~/.teleclaude/docs/sdlc/policy/peer-invocation.md

## Goal

Route a todo into the preparation lane defined by its kind and drive that lane
from initial intent capture to its ready state. Feature, change, and bug work
use the prepare state machine; task work diverts to its non-SDLC task-plan
procedure. One session retains ownership while each routed phase loads its
focused procedure and advances through the machine-owned transitions.

### Defaults — read these once and carry them through every phase

1. **One session drives the whole prepare lifecycle.** The session you are
   in loads each phase's procedure when the machine routes there, does the work
   itself, and advances the machine.
2. **Each phase has its own focus, sharpened by a hat.** The machine names the
   phase's procedure and hat — BA for intake, Architect for architecture,
   Planner for the plan. The hat sharpens focus for that phase on top of your
   lifecycle awareness and comes off when the next procedure loads.
3. **Reviewers are independently dispatched.** A review step runs in a separate
   session the machine's script dispatches; you follow it under the orchestration
   loop (`general/procedure/orchestration`), and you own whether another review
   pass is due (`sdlc/procedure/lifecycle/review`). Escalation follows
   `general/policy/human-contract`, never the review count.
4. **Human PRD approval belongs to the feature lane only.** A drafted feature PRD
   first passes `prd_review`; the human then judges product intent and stamps
   `prd_approved`. Architecture and implementation plans advance on reviewer
   verdict alone.
5. **You alone invoke a peer** for a design judgment still uncertain after
   grounding (`sdlc/policy/peer-invocation`). Every session you dispatch reports
   to you through its own output and artifacts.

The bug lane is the one exception to the first default: a dispatched peer
authors the `diagnosis` while this session triages before it and examines the
written mechanism after it, or settles a reporter's confirmed causal account at
triage without a peer (`sdlc/procedure/lifecycle/prepare/diagnose`).

## Preconditions

- Slug exists in the todo list, or is created during the session at the moment
  intent is concrete enough.
- Session was invoked via `sdlc/procedure/lifecycle/prepare/overview [slug]`, or
  auto-spawned to work a todo already on the list.
- Either a human is in the conversation or none is. The session reads that from
  the conversation it is having; nothing declares it and nothing carries it in.

## Steps

When this procedure is your session's launch assignment, retrieve its focused
tool help with `telec -h --expand-role` before starting the assigned work. When
reading it inline, retain your current session's tool context. Use
`telec <command> -h` for individual commands.

### 0. Resolve the entry mode

The slug's presence and the human's presence determine the posture:

- **No slug + a human in the conversation.** The conversation itself is the
  source for `@input`. Shape a concrete todo with the human, and once the intent
  is concrete create it held:
  `telec todo create <slug> <content> --kind <kind> --hold --reason "<why this waits, or the gate or owner it waits on>"`.
  The hold keeps the runner from claiming the new todo before you continue;
  release it with `telec todo update <slug> --release` once the todo is ready to
  enter its normal lane. Then continue as its prepare orchestrator from Step 0a.
- **Slug + a human in the conversation.** The human is reassessing or refining
  that todo. Assess the conversation and the human's intent for the slug before
  calling `telec todo prepare {slug}`, then proceed from Step 0a.
- **Slug + no human in the conversation.** Proceed directly from the artifacts
  through the prepare state machine. A human who joins later governs only the
  acts from that point on and rewrites no involvement record already stamped.

### 0a. Audit the creation record and input

Perform the entry audit read-only under `sdlc/policy/todo-creation-discipline`
and carry the input repairs it identifies into Step 2.

1. Read the creation record and the current `input`. Take the `input` as the
   authorized basis for derivation.
2. Recover what the summary lost. `telec todo artifacts list {slug}` names each
   artifact's writers; read every writer that is not this session, including a
   writer the record does not name. A user entry outside any complete recognized
   platform envelope is a human's own turn (`general/policy/message-identity-headers`).
   Record what was compared and what came of it.
3. Derive the work from that basis by kind — the outcome and constraints for
   `feature` and `change`; the reported concern, symptom, and
   expected-versus-observed behavior for `bug`, whose causal and scope claims
   remain hypotheses diagnosis tests; and the action boundary, result,
   recipient, and timing for `task`. A technical choice needed for safe and
   correct delivery stays plan and build's to make.

A task performs the same audit before entering its task-specific lane.

### 1. Pre-flight input viability

Read the input via `telec todo artifacts read {slug} input` and decide whether
derivation can proceed at all.

- **Hard-stop signals** (any one disqualifies the input as-is):
  - a single short phrase or noun phrase with no goal, no actor, no outcome —
    fewer than ~10 meaningful words;
  - a slug carrying a raw timestamp suffix (e.g., `…-1778958052`) with no
    companion context from a prior session;
  - empty input, placeholder text, or a known smoke-test pattern.
- **No human in the conversation** → stop the prepare flow before any
  derivation. Surface the gap by referencing `@input` (never pasting it) and
  recommend human elaboration or removal (`telec todo remove {slug}`).
- **A human in the conversation** → point the human at `@input`, name the gap,
  and ask one direct question to surface the goal, actor, and outcome. Assess
  the elaborated input for viability, then carry the input update into Step 2.

Substantive input — clear intent, concrete outcome, identifiable actor, even if
short — passes and proceeds to Step 1a.

### 1a. Process-change governance gate

Before artifact derivation, assess under `sdlc/policy/process-change-authority`
whether delivery changes a process-layer contract. When it does, identify the
pending process-contract changes here and author them on `main` in Step 2,
before planning. When an underlying consequence belongs to the human, surface
only that outcome (`general/policy/human-contract`) and absorb the decision into
the owning artifact.

### 1b. Route by todo kind

Read the todo's recorded kind and enter only the lane it owns:

| Kind      | Entry route                                                                                                                      | Preparation outputs                                                                                  |
| --------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `feature` | Intake → PRD review and human approval → optional architecture and review → implementation plan and review                       | `prd`, behavioral feature-spec reflection, optional `architecture`, `implementation-plan`            |
| `change`  | Implementation-plan drafting and review                                                                                          | `implementation-plan`; no PRD or feature intake                                                      |
| `bug`     | Diagnosis, by a dispatched peer or settled at triage from a confirmed reporter account → implementation-plan drafting and review | `diagnosis`, `implementation-plan`; no PRD or feature intake                                         |
| `task`    | Load `sdlc/procedure/lifecycle/task/prepare-task` and leave this SDLC flow                                                       | `task-plan` plus human authorization; no PRD, architecture, implementation plan, or reviewer verdict |

When the recorded kind does not match the intent, reclassify it with
`telec todo update {slug} --kind <feature|change|bug|task>` before deriving
artifacts.

The kind decides the lane, not whether architecture review happens: a plan that
makes a structural decision no reviewed architecture carries — in a `change` or
`bug`, or in a `feature` whose architecture was skipped — carries that review
inside its plan phase (`sdlc/policy/preparation-artifact-quality`, Structural
decisions carry architecture review).

A `bug` keeps its lane when a current contract states the behavior its report
expected (`sdlc/policy/todo-creation-discipline`): open the contract the report
states and confirm it says that. A report that names none, about behavior a
current contract plainly states, gets that contract added to `input` and keeps
its lane. Whether the evidence shows the claimed behavior is diagnose triage's
judgment. A report whose premise is that nothing followed up is first checked
against the policy's platform-gap rule.

When no current contract states the expected behavior, the report is one of two
things:

- **A change request** — it names an outcome someone wants. Reclassify it to
  `change` before calling `telec todo prepare {slug}`.
- **An invalid bug report** — behavior its contract permits, asking for no
  outcome anyone wants. Record the reason in the todo's `log`. An
  agent-originated report is removed with `telec todo remove {slug}`, ending the
  session. A report carrying a human's request in their own words is that
  human's to withdraw: hold it with
  `telec todo update {slug} --hold --reason <reason>` and stay open with why it
  breaks no contract (`general/principle/session-lifecycle`). When they withdraw
  it, remove it and end. When they restate it as a change, record the
  restatement in `input`, release the hold, and reclassify it to `change` before
  calling `telec todo prepare {slug}`.

### 1c. Settled change

At audited entry, before drafting or review starts, a `change` that meets the
in-context criteria of `sdlc/policy/todo-creation-discipline` may be executed
here. It requires an explicit `doc_impact_none` basis, no pending documentation
or uncommitted delivery fold for the slug, and no prior build work or unresolved
review to bypass. A `bug` never takes this path.

Execute on canonical `main`, commit, and resolve independent review under
`general/policy/commits`. Record the eligibility basis, delivery commits, review
reference, and remaining publication obligation in the todo's `log`.

The integrator retains direct-main publication. Keep ownership of delivery
bookkeeping while publication is pending; use the reminder service and yield.
Before delivery, refresh remote state, confirm the recorded completion commit is
contained in `origin/main`, and re-establish that the reviewed outcome remains
delivered and that cleanup would discard no slug-owned work or pending material
and commit nothing new. Then run
`telec todo deliver {slug} --commit <recorded-completion-sha>`, verify the
terminal state, and perform terminal session cleanup.

If eligibility fails before execution, enter the ordinary change lane. If a
later finding requires preparation, retain the commits and unresolved evidence
and route the remaining work through normal recovery, leaving the todo
undelivered.

### 2. Call the state machine

For `feature`, `change`, and `bug`, make the initial `telec todo prepare {slug}`
call once the read-only entry assessment establishes settled, viable intent and
before any preparation write. The call registers the prepare role in this
session and retains its slug claim. A session holding the slug in the work lane
is refused: work returns to preparation only through a fresh prepare
orchestrator the lifecycle runner dispatches.

Receive the outcome as the orchestration loop describes
(`general/procedure/orchestration`). Entry has succeeded once it carries the
phase's execution script rather than a refusal. Then apply the input repairs and
process-contract changes identified during preflight, and execute the script
verbatim: a procedure load, a reviewer dispatch, an approval pause, or a
terminal state. Its flexibility belongs to in-conversation moments with the
human: fresh questions, refinements, scope clarifications.

### 3. Do each routed phase's work

Load the procedure the script names, do its focused work, and end by calling
`telec todo prepare {slug}` to advance.

### 4. Honor the feature PRD approval gate

In the feature lane, the PRD is the only SDLC artifact gated by human approval,
and internal review precedes that gate. When intake writes or rewrites the PRD,
the state machine routes to a dispatched PRD reviewer. `needs_work` returns the
findings to intake; `approve` binds the verdict to the current PRD digest and
opens human approval.

Present only the reviewed PRD, its stated horizon, and genuine human-owned
decisions. On confirm, stamp `prd_approved`. On refinement, capture the delta,
rewrite the PRD, and let the machine invalidate and rerun `prd_review`; the
rewritten PRD returns to the human only when the approval does not carry.

The human approves intent, not a digest. Once the human has approved a PRD, a
later revision returns to them only when it carries intent they have not
already decided. Every other revision carries their approval. The independent
PRD reviewer judges whether it does, in its report on the revised digest
(`sdlc/procedure/lifecycle/prepare/review-prd`); the claimant never classifies
its own revision. When the current `prd_review` approves and its report
concludes that the approval carries, the prepare claimant stamps `prd_approved`
without asking. A revision carries the approval when each of its changes is
one of these:

- a decision the human gave in the live conversation, applied as given;
- removal or narrowing of scope that the `input` does not carry and the human
  never asked for;
- a correction of reasoning, evidence, wording, or mechanism that leaves every
  outcome and success criterion as the human approved it.

For the first ground, the claimant records the human's direction and the
session that carries it in the todo `log` before the review is dispatched, so
the reviewer judges it against the source.

A revision that adds or widens an outcome, changes a success criterion beyond
the human's own direction, or raises a new decision in the human's closed lane
(`general/policy/human-contract`) returns to the human, and so does one whose
classification remains uncertain. A carried approval never skips
`prd_review`. Before stamping, the claimant records in the todo `log` the
approved digest it carries forward and the review report that carried it. The
human is not asked to confirm a carried approval and receives no separate
notice of it.

<!-- planned-change:github-person-decisions -->

A PRD the human has never approved is never stamped `prd_approved` by an
agent: the first approval is the human's, given directly in the live
conversation, and no signal about how the session started supplies,
withholds, or propagates it.
<!-- change:github-person-decisions -->

A PRD the human has never approved is never stamped `prd_approved` by an
agent: the first approval is the human's, given directly in the live
conversation, and no signal about how the session started supplies,
withholds, or propagates it.

For an item of a project on the GitHub workflow store, the first approval may
also be given on the item's issue, through the approval act its work record
defines, by a configured person who owns the repository or is a member of the
organization that owns it, and who holds write access to the repository;
approving intent is authority the human grants only to them
(`general/policy/human-contract`). Such an approval counts only
while the item waits for human approval of its current reviewed PRD, and the
platform records it from that act; no agent stamps it and no agent reads one
from a person's words. An approval act by anyone else, or at any other moment,
changes nothing and is answered on the issue.
<!-- /planned-change:github-person-decisions -->

### 5. Re-read against changed doctrine

The machine detects code drift and dispatches its analysis itself. Doctrine
drift it does not detect: on resuming a todo whose artifacts were reviewed
before a change to a principle, policy, or procedure they are judged against,
re-read each artifact against the doctrine changed since its last review. Only
a material conflict triggers kickback and re-review of the affected phase;
doctrine drift alone invalidates no approval.

### 6. Handle refinement

When the human refines an artifact at any layer, classify the refinement scope
and re-enter the matching phase:

- **Intent-level** (new thinking, scope changes) → repeat kind routing. A
  feature re-enters intake; a change re-enters plan; a bug re-enters diagnosis
  or plan according to whether the causal conclusion changed.
- **Architecture-level** (design-snippet change in a feature) → re-enter
  architecture.
- **Plan-level** (task adjustment) → re-enter the plan phase.

Clear the approval stamps downstream of the re-entered phase and re-run the
affected phases. A substantial human refinement of an autonomously produced
artifact is authoritative for that refinement, and downstream re-derives from
it even when downstream was already produced.

### 7. Terminal state

The machine derives `PREPARED` once every required phase is approved, grounding
is fresh, and every commit this session authored on `main` under the claim
carries an approve stamp; until then its script names the commits still owing
one (`general/policy/commits`). Deriving `PREPARED` releases this session's
claim, and the work lane takes the todo up from there. Execute the terminal
script, report `PREPARED` to the human, then assess departure under
`general/principle/session-lifecycle`; an unfinished human conversation keeps
the session, never the todo. Hand-off is the release itself; the work lane
claims the todo, not this session.

When reviewer verdicts cannot be resolved through normal revision rounds, or
drift cannot be cleanly re-derived, the machine derives `BLOCKED`. Classify the
remaining decision under `general/policy/human-contract` and record its
evidence, next contribution, and owner; review halts follow
`sdlc/procedure/lifecycle/review`. `BLOCKED` is a work state, not a declaration
that the human owns its recovery.

## Outputs

- Every lane begins from the `input` as its authorized basis.
- Feature: digest-bound `prd_review`, human-approved `prd`, behavioral feature
  spec reflection, optional reviewer-approved `architecture`, and a
  reviewer-approved `implementation-plan`.
- Change: reviewer-approved `implementation-plan`, with no PRD or feature
  intake artifacts.
- Bug: a `diagnosis` authored by a dispatched peer, or transcribed from a
  confirmed reporter account, followed by a reviewer-approved
  `implementation-plan`, with no PRD or feature intake artifacts.
- Task: a `task-plan` and human authorization request from the task procedure;
  no SDLC prepare-state-machine output.
- SDLC lanes carry fresh grounding stamps and end in `PREPARED` or `BLOCKED`.

## Recovery

- **Creation record is absent or incomplete.** Derive from the input and prior
  artifacts; never solicit an attestation from the creator. Reading a named
  session's transcript under Step 0a recovers meaning and is not solicitation.
- **The input is too thin to derive from after the audit.** Stop before
  kind-specific derivation and surface the gap; do not manufacture product
  detail.
- **A bug concern is faithfully recovered but not yet proven.** Proceed to
  diagnosis. Filing fidelity establishes what was reported, not whether the
  report is correct or what caused it.
- **State machine returns an unfamiliar recommendation.** Read its governing
  contract and route any unresolved technical discrepancy to its agent owner
  under `general/policy/human-contract`; do not improvise a state transition.
- **Procedure loading fails.** Report the failure; do not proceed without the
  procedure loaded.
- **A preparation write was refused before entry.** Complete Step 2 and retry
  the in-scope write against the current state. If it remains refused, inspect
  the registered role and operation outcome while retaining the session and
  claim, and ground recovery in that fresh evidence
  (`general/principle/grounding`).
- **Reviewer dispatch fails repeatedly.** Preserve the failure evidence and
  apply the orchestration recovery (`general/procedure/orchestration`). The
  attempts do not substitute for reviewer verification or establish human
  ownership.
- **Human disengages mid-flow.** The machine retains current state; the next
  session resumes where things were left.

## See Also

- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/intake.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/architecture.md
- ~/.teleclaude/docs/sdlc/procedure/lifecycle/prepare/plan-draft.md
