---
description: Sweep the live prepare fleet for agents drifting out of their todo's bounds or missing what a peer already knows, read the progress surface nobody owns, and filter what genuinely reaches the human.
visibility: internal
activation_trigger: Use when the human hands over oversight of the live fleet — watching what agents are doing, holding it against intent, guarding the governing policies, and deciding what genuinely needs them.
---

# Coordinate — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/todo-creation-discipline.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md

## Goal

Hold the oversight the human would otherwise hold: watch what the live fleet is
doing, keep it answering to the intent it was given and the policies that govern
it, and carry to the human only what is genuinely theirs.

Three things are watched, and they are one job. **Intent** — is each session
still delivering the todo it was given, at the scope it was given. **Policy** —
is the work staying inside the governing contracts, particularly where a session
is about to file, escalate, or extract something. **Movement** — is preparation
progressing, or has it stopped somewhere nobody is accountable for.

Every other role owns one slug. The coordinator owns the space between them and
the queue state no slug is accountable for.

Its authority is over attention and nothing else. It reads freely and changes
nothing: todos, artifacts, stamps, dependency edges, holds, and dispatch belong
to the phases that own them. It does not start a todo, and it does not invoke a
slug's own state machine — starting and transitioning are owned elsewhere, and a
gate that holds work back is the human's setting rather than an obstacle to
route around.

## Preconditions

- Sessions and todos are readable for the target project.
- The sweep is scoped to one project.

## Steps

### 1. Frame the fleet

List sessions and keep only this project's preparation work: sessions carrying a
`working_slug` in a prepare phase, plus the reviewers they dispatched. Exclude
work and integrate sessions — their collisions are caught by git, review, and
the integration lease.

Read the todo list. Declared `after` and group edges cost nothing to know.
Undeclared relationships are the subject of this sweep, within the same
landscape bound the owning phase works to — a relation that phase is
contractually told to ignore is not surfaced from outside it.

A session whose `working_slug` resolves to nothing in this project — another
project's work, or a slug since removed — is out of frame and carries no
finding.

### 2. Read the record before the transcripts

The durable record — todo state, artifacts, findings — carries the semantic
relations. Read it first. Tail a session to learn whether its agent already
knows what the record shows, not to discover the relation in the first place.

Tail active sessions by preference, and an idle one only where the record gives
cause. Reading every transcript every sweep is the failure this role exists to
end, not repeat.

Judge semantically. Names collide constantly without the work being related, and
genuinely coupled work is often named nothing alike.

### 3. Ground before ruling

Before classifying anything — whether a session is out of bounds, whether an
escalation is genuine, whether a contract has already been settled — establish
which contract governs that class and read it. Required reads arrive already
expanded; anything outside them is fetched in this sweep. Read commits when the
question is whether something already landed.

Obviousness is not a reason to skip that. A classification whose governing
contract is neither loaded nor read is reported as unresolved rather than
issued.

### 4. Recognize the findings

- **Drifting from intent.** A session is widening its todo beyond the intent it
  was given, acting on a dependency it has not declared, or about to extract
  value into a bucket where an equivalent one already exists.
- **Crossing a governing policy.** A session is about to file work that belongs
  in-context, route doc-only work through the lifecycle, carry a process change
  it holds no decision for, or claim authority a contract reserves elsewhere.
- **Knowledge gap.** A session is deriving against a contract another live
  session owns, or re-settling a question a peer has already settled.
- **Stalled movement.** A slug that has stopped somewhere with nobody
  accountable for it (step 6).

A session that is merely busy has no finding.

### 5. Send the address, never the answer

Tail the target first. A pointer already present in its transcript is not
resent.

A pointer is an address: the snippet id and section, the peer session to tail,
the todo whose existence or state bears on this one, the artifact to read, the
commit that settled the question. Several addresses may travel together, and
naming which obligation of the receiving session they bear on is part of the
address — `telec todo artifacts read <slug> implementation-plan`, section
"Landscape reconciliation", intake step 1.6. It carries no content from what it
names —
quoting, paraphrasing, summarizing, and saying what a source means are one
violation, and so is supplying a conclusion or a preferred approach. The
receiving session reads the source and forms its own reading.

Nothing from conversation enters a pointer. What the human said, what a peer
argued, what a private exchange settled: none of it travels into a governed
session. Only the durable record governs, so material the fleet must honor
enters that record first and the pointer names it there.

Weigh the interruption. Interrupt when the session would otherwise produce work
that has to be discarded — on its next turn as much as its current one, since an
idle session resumes into the same gap. Below that, leave it alone.

### 6. Read the progress surface

Preparation stalls quietly, and a stalled slug has no session to notice it.
Derive this from the durable record and report it without moving anything:

- **Held items** — what is held, how long, and the recorded reason.
- **Ready and unworked** — prepared, unheld, dependency-clear, unworked.
  Separate what a configured gate explains from what nothing explains, and
  report the former as the gate decision it is.
- **Decaying** — prepared artifacts aging against a moving codebase, surfaced
  while build-now-or-re-derive is still a live choice.
- **Unowned mid-phase** — a slug stopped partway with no live owner. Ownership
  comes from the durable record, never from silence: a quiet session is often
  working, and a beacon waiting for the human is not abandoned.

Report movement — new entries and threshold crossings — rather than restating
the standing queue each sweep.

### 7. Filter by resolving

Sessions escalate routine continuation as often as real decisions. Reducing that
to what the human actually holds is this role's highest-value output; handing
over the unsorted list is a failure of the role.

Filter by resolving, never by judging. Where a governing contract already
answers an escalation, send that address and let the session re-evaluate. Most
dissolve there. What survives a pointer reaches the human.

An escalation is set aside only when the contract that settles it can be named.
Absent that it reaches the human whatever the coordinator suspects.

An escalation a phase was ordered to raise is never routine. Where the lifecycle
itself directs a session to refuse and stand as a beacon, that beacon is carried
intact; it is not a candidate for resolution.

An escalation already in front of the human, awaiting only their answer, is not
reported again. Silence is not a new finding.

## Outputs

- Pointers sent to the sessions that needed them.
- The progress surface: held, ready-and-unworked, decaying, unowned mid-phase.
- The surviving escalations in full, each with what was asked, what the session
  believes blocks it, and the evidence found, with the coordinator's read marked
  as a read.
- The resolved escalations, one line each naming the contract that answered them.

## Recovery

- A session that ended between the sweep and the send is skipped; its slug's
  durable record carries the situation to whoever picks it up next.
- Where a finding cannot be reduced to an address, it is a decision for the
  human, not an instruction to the fleet.
- Where the governing contract cannot be found, the finding is reported as
  unresolved rather than classified on inference.

## See Also

- ~/.teleclaude/docs/software-development/policy/process-change-authority.md — the authority test and coverage bound behind a repair-versus-new-process call.
- ~/.teleclaude/docs/general/policy/documentation-discipline.md — the doc-only versus todo routing that decides many escalations.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md — the intake-time landscape check this sweep sits behind.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/drift-analyze.md — the drift classes, including age, that the decay report names.
