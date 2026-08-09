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

The intervention is deliberately small. The coordinator does not correct work,
it points a session at what it needs and lets the session decide. Its authority
is over attention, never over the lifecycle.

Every action worth taking already has an owner. The runner starts todos. The
state machines own transitions. A slug's live holders — an orchestrator bound
to it, or a live `active_runner` — make a second driver impossible. Attention is
the one thing no component owns, and it is the whole of this role's mandate.

Two consequences bind the coordinator's hands specifically:

- **It never starts a todo.** The runner starts what is eligible, and the gates
  that hold work back are the human's setting. An eligible unowned slug the
  runner has not picked up is a runner defect, reported as one.
- **It never invokes a slug's own state machine.** Only a live holder refuses
  the call. Without one it succeeds by adopting this session as that todo's
  driver, and the fleet loses its coordinator without an error. The `hold` flag
  is not consulted on that path, so a held slug is no safer than any other.

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
  Plan and commit review catch these after they land; the pointer catches them
  before the work is derived from them.
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
  working it. Most of this is the configured autostart gate behaving as set, not
  a fault; report it as the gate decision it is, so the human can flip the gate
  or start the work by hand. Separate the rows a gate explains from the rows
  nothing explains, and report movement — new entries and threshold crossings —
  rather than restating the standing queue every sweep.
- **Decay** — prepared artifacts age against a moving codebase. Drift analysis
  fires on re-entry, not on the clock, so the cost of a stale plan stays hidden
  until someone builds it. Surface age so the build-now-or-re-derive choice is
  made deliberately.
- **Unowned mid-phase** — a slug stopped partway with neither a bound
  orchestrator nor a live `active_runner`. Read ownership from those two
  signals, never from idleness or age: a quiet session is often working, and a
  beacon waiting for the human is not abandoned. Absence of noise is not
  evidence; absence of a live holder is.

### 7. Filter what reaches the human

Sessions escalate routine continuation as often as they escalate real
decisions. Reducing that to what the human actually holds is this role's
highest-value output. Handing them the unsorted list is a failure of the role,
not a safe default.

Filter by resolving, never by judging. For each session waiting on the human,
establish under step 3 whether a governing contract already answers it. Where
one does, send that address to the asking session and let it re-evaluate — most
escalations dissolve there, because the session was blocked on a contract it had
not read rather than on a decision. What survived a pointer is what reaches the
human.

An escalation is set aside only when the contract that settles it can be named.
Absent that, it reaches the human whatever the coordinator suspects — a
classification that cannot cite its authority is a hunch, and this role is the
one furthest from the contracts it would be guessing about.

Report the survivors in full: what each session asks, what it believes blocks
it, and the evidence step 3 produced, with the coordinator's own read marked as
a read rather than a verdict. Report the resolved ones as one line each naming
the contract that answered them, so the reduction stays visible without
becoming work to read.

## Outputs

- Pointers sent to the live sessions that needed them.
- The progress surface: held, ready-and-unworked, decaying, unowned mid-phase.
- The surviving escalations, each carrying what was asked, what the session
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

- ~/.teleclaude/docs/general/policy/documentation-discipline.md — the doc-only versus todo routing that decides many escalations.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md — the intake-time landscape check this sweep sits behind.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/drift-analyze.md — the drift classes, including age, that the decay report names.
