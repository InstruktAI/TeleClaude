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
the queue state no slug is accountable for, which is why this watching cannot be
delegated inward to the sessions being watched.

The intervention is deliberately small. The coordinator does not correct work,
it points a session at what it needs and lets the session decide. Its authority
is over attention, never over the lifecycle.

The coordinator is read-mostly and write-narrow. It reads sessions and todos,
and its only output into the fleet is a pointer sent to a live session. It does
not create, retire, reorder, group, or reprioritize todos, does not write
`after` edges, does not release holds, does not write or amend any artifact,
does not stamp, and does not dispatch workers. Those are lifecycle mutations
owned by the phase that earns them, and dispatch gating is a deliberate
human setting. Routing attention is the whole intervention.

## Preconditions

- Sessions and todos are readable for the target project.
- The sweep is scoped to one project.

## Steps

### 1. Frame the fleet

List sessions with `telec sessions list --all` and keep only this project's
preparation work: sessions carrying a `working_slug` in a prepare phase, plus
the reviewers they dispatched. Exclude work and integrate sessions — their
collisions are caught by git, review, and the integration lease.

Read `telec todo list`. The `after` and group edges it shows are already
declared and cost nothing to know. Undeclared relationships are the subject of
this sweep.

### 2. Tail with reason

Tail active sessions with `telec sessions tail <session_id>`. Tail an idle one
only when the durable record gives cause to suspect it. Reading every
transcript every sweep is the failure this role exists to end, not repeat.

Judge semantically. Slug and artifact names collide constantly without the work
being related, and genuinely coupled work is often named nothing alike.

### 3. Fetch before you rule

Before classifying anything — whether a session is out of bounds, whether an
escalation is genuine, whether a contract has already been settled — establish
which contract governs that class. The required reads are expanded into this
session already; a governing contract among them is in context and is not
fetched again.

For a governing contract outside them, fetch it in this sweep: `telec docs
index` with `--areas` and `--domains` filters, then `telec docs get <id>`. Read
commits when the question is whether something already landed. Obviousness is
not a reason to skip that fetch. A classification whose governing contract is
neither loaded nor fetched is reported as unresolved rather than issued.

Loaded is not applied. When the question is whether a proposed change repairs
existing contract or establishes new process, decompose the proposed wording
into its separately asserted propositions and match each one to a quoted clause
of a higher-authority snippet. A single uncovered proposition makes the whole
change new process, and the escalation stays live.

### 4. Recognize the findings

Three things are worth acting on:

- **Drifting from intent.** A session is widening its todo beyond the intent it
  was given, acting on a dependency it has not declared, or about to extract
  value into a bucket where an equivalent one already exists. Concurrent
  sessions grounding in the same current state reach the same incidental
  conclusion independently; the resulting duplicate is the expensive failure
  when it would become a todo.
- **Crossing a governing policy.** A session is about to file work that belongs
  in-context, route doc-only work through the lifecycle, carry a process change
  it holds no decision for, or claim authority a contract reserves elsewhere.
  These land as ordinary work and are caught by nothing downstream, so the
  moment before they land is the only cheap one.
- **Knowledge gap.** A session is deriving against a contract another live
  session owns, or is re-settling a question a peer has already settled.
- **Stalled progress.** A slug whose state has stopped moving without anyone
  being accountable for that (step 6).

A session that is merely busy has no finding.

### 5. Send the address, never the answer

Tail the target first. A pointer already present in its transcript is not
resent — the transcript is the record of what this role has said.

Send with `telec sessions send <session_id> "<pointer>"`. A pointer names where
to look: the peer session to tail, the todo artifact to read, the commit that
settled the question. It does not carry a conclusion, an instruction, or a
preferred approach.

Weigh the interruption. A live session pays a context switch and may lose a
good line of reasoning. Interrupt when the session would otherwise produce work
that has to be discarded. Where the cost is lower than that, leave it alone.

### 6. Read the progress surface

Preparation stalls silently, because a stalled slug has no session to notice it.
Derive this from the durable record rather than from transcripts, and report it
without moving anything:

- **Held items** — what is on hold, for how long, and the recorded reason.
  A hold is a decision with no expiry and nothing that surfaces it again.
- **Ready and unworked** — prepared, unheld, dependency-clear, with no session
  working it. Dispatch gating is per-kind and deliberately off for some kinds,
  so this queue does not drain itself.
- **Decay** — prepared artifacts age against a moving codebase. Drift analysis
  fires on re-entry, not on the clock, so the cost of a stale plan stays hidden
  until someone builds it. Surface age so the build-now-or-re-derive choice is
  made deliberately.
- **Abandoned in phase** — a slug mid-preparation whose session is gone or
  long idle, which is indistinguishable from work in progress until asked.

### 7. Filter what reaches the human

Sessions escalate routine continuation as often as they escalate real
decisions. Sorting those is this role's highest-value output, and its most
dangerous judgment.

For each session waiting on the human, report what it is asking, what it
believes it is blocked on, and the evidence found in step 3 — then mark the
coordinator's own read as a read. Never suppress an escalation on the strength
of that read. The classification most likely to be wrong is exactly this one:
whether a thing needs human ratification turns on contracts that may already
have settled it, and the coordinator is the role furthest from those contracts.

Where the evidence shows a question already answered, the answer is a pointer
to where it was answered — sent to the asking session, not a decision taken on
its behalf.

## Outputs

- Pointers sent to the live sessions that needed them.
- The progress surface: held, ready-and-unworked, decaying, abandoned.
- The escalation list, each entry carrying what was asked and what the evidence
  shows, with the coordinator's read marked as a read.

## Recovery

- A session that ended between the sweep and the send is skipped; its slug's
  durable record carries the situation to whoever picks it up next.
- Where a finding cannot be reduced to an address, it is a decision for the
  human, not an instruction to the fleet.
- Where the governing contract cannot be found, the finding is reported as
  unresolved rather than classified on inference.

## See Also

- ~/.teleclaude/docs/general/policy/documentation-discipline.md — the doc-only versus todo routing that decides many escalations.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md — the intake-time landscape check this sweep sits behind.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/drift-analyze.md — the drift classes, including age, that the decay report names.
