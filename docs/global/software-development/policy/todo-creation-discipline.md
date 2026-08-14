---
description: Decide whether a todo should exist, audit that decision at preparation entry, and reconcile a live violation without wasting further preparation effort.
---

# Todo Creation Discipline — Policy

## Rules

### Decide before creating

- **Run the bounded creation check before every `telec todo create`.** Read
  `telec todo list`. For each plausible match, read its `input`; if whether it
  has started build affects the choice, inspect its current state too. This is
  a cheap check for an obvious existing home, not the deeper judgment about
  whether one premise yields to, supersedes, or depends on another.
- **Use what the check finds.** Do not create a todo when the work is already
  plainly covered. When a small addition belongs in an existing `change`,
  `bug`, or `feature` that has not started build, route it to that todo's live
  claimant for amendment; when the todo is dormant and unclaimed, amend it
  directly in the session that found it. Do not create a sibling merely to
  bypass artifact authority. A separate todo is warranted when the work is
  independently shippable, substantial in its own right, or the related todo
  is already building or finalizing.
- **File in the project that owns the changed code.** The project where a
  symptom appears is not necessarily the owner of the work. State the project
  explicitly when it differs from the invoking working directory. If the
  owner cannot be established, resolve that before filing rather than letting
  the working directory decide.
- **Execute small, settled code work in context.** When the approach is known,
  the edit is bounded, and the work needs neither a plan, a builder, nor a
  handoff, make the change on `main` in the human-present session and route the
  commit through review. Importance does not decide this boundary; remaining
  judgment does. A small change whose correctness is genuinely contested
  still belongs in the lifecycle.
- **Use the todo's `log` artifact for a breadcrumb.** A minimal FYI that
  changes neither scope nor a decision does not justify a new todo or a rewrite
  of `input`, `prd`, or `implementation-plan`.
- **File process-layer work only from a live human decision.** A proposed
  change to lifecycle state, gate composition, review lanes, or todo semantics
  is not filed from an agent's inference. Without the decision, do not create
  the todo; escalate the proposal to the human as
  `software-development/policy/process-change-authority` directs.
- **Declare genuine human involvement at filing.** An agent whose filing was
  seen, requested, or shaped by a human passes `--human-involved`. Omitting the
  flag declares the filing agent-initiated for later audit.

- **The bug filing surface interrogates before filing.** A bug-kind todo
  autostarts its prepare lane, so filing is pipeline entry and the creation
  check above is enforced at the filing surface itself: a `telec bugs report`
  invocation carrying only the report payload does not file — it presents the
  pre-filing decisions (fix-directly-in-context per the five-minute rule;
  duplication against the todo list, in-flight bug lanes, and suppressions;
  ordering behind or dependency on work already in flight; validity of the
  trigger evidence and the owning project) and only that output names how to
  complete the filing. The surface verifies the decisions were faced, never
  that the answers are true; judging the answers stays with intelligence.
  Change and feature creation are not interrogated this way — they do not
  autostart and keep their human gate.

### Audit at preparation entry

- **Audit before deriving from `input`.** At Step 0a, read the mechanically
  stamped creation record and the current `input`, establish the owning
  project, repeat the bounded creation check, apply the governing creation and
  process-authority contracts, and confirm that functionality work carries its
  required pending documentation. The creation record establishes lineage,
  entry point, human involvement, and door-specific context; it does not prove
  which sources or todo queries the creator consulted.
- **Repair before retiring.** Correct the project, input, missing
  documentation, dependencies, or other repairable omission in place. Retire
  only a confirmed duplicate, an owner that cannot be corrected in place,
  unauthorized process intent, or an input for which no defensible intent
  remains. Scheduling and `hold` state do not decide validity.
- **Repeat after `input` changes.** A prior reading of different intent does
  not authorize new derivation.
- **Perform the kind's deeper landscape judgment at its actual phase.** These
  checks are not equivalent and do not all occur at creation:
  - `feature` — intake Step 1.6 reconciles the broader todo landscape.
  - `bug` — diagnose Step 1 retires an exact-defect duplicate before
    investigation; plan-draft Step 1c later handles broader overlap.
  - `change` — plan-draft Step 1c handles broader overlap before planning.
  - `task` — only the bounded entry audit exists; deep task-landscape
    reconciliation is not implemented.

### Reconcile a flagged live todo

- **Any observer may flag a policy conflict to a todo's live claimant.** A
  flag is a challenge, never a verdict. The first message is complete: it
  identifies the todo, the source address grounding the concern, the section
  of this policy under challenge, and this reconciliation section. It carries
  addresses, not rewritten instructions or a proposed outcome.
- **A flag binds only a live claimant.** An unclaimed todo has no message-based
  flag path and consumes no active preparation effort; its next claimant must
  apply the Step 0a entry audit before deriving from it. Creation lineage is
  audit evidence, not a guarantee that the creator is still reachable.
- **The claimant pauses preparation immediately.** It advances no phase,
  dispatches no new child, and does not act on child output produced for the
  challenged premise until it has analyzed the concern and chosen one of the
  following exits. A child already mid-turn may finish; end it only when the
  challenge plainly makes its current work unusable.
  - **Defend.** Point to the grounded creation check and landscape evidence.
    A defense is not a request for the flagger's permission: after sending the
    grounded basis, the claimant resumes preparation. A permitted follow-up
    reopens the pause once.
  - **Hold.** Run `telec todo update <slug> --hold` to set the todo's automatic
    dispatch brake, then write the flag's source address and the reason the
    premise may become valid later to the todo's `log` artifact. The hold state
    itself records only a manual hold; the log carries why this hold exists.
  - **Stand down.** End the claimant's preparation children. Before releasing
    the claim, make the todo tell the truth by either holding it with the log
    entry above or amending `input` to carry the reconciliation. Only then run
    `telec todo update <slug> --unclaim`. A bare release is forbidden: it
    returns the suspect premise to the runner with less context and recreates
    the same preparation waste.
  - **Retract.** For work that is truly invalid — including doc-only work,
    process change without its required human decision, or a confirmed
    duplicate — end the claimant's children, run `telec todo remove <slug>`,
    and leave the final result. Then depart under the departure discipline in
    `general/policy/heartbeat`.
- **The flagger does not select or negotiate the exit.** After the complete
  flag, it may send at most one source-grounded, address-only follow-up when a
  defense exposes a specific unresolved contradiction. When that follow-up
  arrives, the claimant pauses again and answers by choosing another exit or
  maintaining its defense. A grounded defense with no follow-up is the only
  conversational settlement; flagger silence leaves nothing pending. For
  every state-changing exit, the flagger reads settlement from the todo
  record: the hold and its log entry, the amended `input`, or removal.
- **Only deadlock reaches the human.** Deadlock exists only when the claimant
  maintains its defense after the permitted follow-up and the flagger still
  cannot reconcile the conflict. The flagger then presents one live question
  to the human. A resolved defense, hold, stand-down, or retraction does not
  become human clerking.

### Read authorship from the creation record

- **Never infer who created a todo from account identity.** Read the immutable
  creation record: `entry_point`, `lineage`, `human_involved`, and
  door-specific `context`. The lineage root names the authority under which
  the work ran; the optional acting session identifies the agent hands. The
  human identity at the root is not authorship evidence.

## Rationale

Creation stays intentionally cheap. Its bounded check prevents obvious waste
without forcing every creator to perform the preparation worker's deeper
landscape analysis. The entry audit then reads the actual todo and current
landscape before the input becomes authority for derived work.

The prior contract named violations but gave an observer no consequence to
trigger. A live-claimant flag closes that gap at the moment cost is being
incurred: preparation pauses, while the claimant retains judgment over whether
to defend, hold, stand down, or retract. Restricting the flagger to addresses
and one follow-up prevents a challenge from becoming a parallel
orchestration. Restricting human escalation to an unresolved defense keeps
ordinary correction out of the human's attention.

The message-based flag is deliberately not durable todo state. It protects
actively prepared work, where a claimant exists and effort is being spent.
Unclaimed work is protected by the mandatory entry audit when preparation
next begins.

## Scope

All todo creation and preparation, every kind, every human or agent creator,
and every observer that flags a live claimant under this policy.

## Enforcement

- A todo created without the bounded check, in the wrong owning project, for
  plainly duplicate or amendable work, for in-context work, or for an
  unauthorized process change violates this policy.
- A prepare claimant that derives from `input` before the entry audit, or
  continues preparation after receiving a flag and before reconciliation,
  violates this policy.
- A flagger that supplies remediation content, chooses the claimant's exit,
  continues beyond one grounded follow-up, or escalates a resolved case to the
  human violates this policy.
- `telec todo update --hold` does not accept a reason and records the generic
  manual-hold reason `todo update`; a flag-related hold without the associated
  todo-log explanation is incomplete reconciliation.

## Exceptions

- `task` receives the bounded creation and entry audits with no carve-out. It
  has no kind-specific deep landscape reconciliation today; do not imply that
  one ran. See `software-development/spec/todo-kind-task`.
