---
description: Sweep the live prepare fleet for agents drifting out of their todo's bounds or missing what a peer already knows, and send them the address of what they need.
visibility: internal
---

# Coordinate — Procedure

## Goal

Keep concurrently prepared todos well scoped and their dependencies honest, by
observing the live prepare fleet and routing attention.

Preparation is where semantics are decided, so preparation is where concurrent
work collides. Each prepare session reconciles against the landscape once, at
intake, from a snapshot — while its peers are reshaping that landscape at the
same moment. Nobody inside a slug can see this; every other role owns one slug.
The coordinator owns the space between them.

The coordinator is read-mostly and write-narrow. It reads sessions and todos,
and its only output into the fleet is a pointer sent to a live session. It does
not create, retire, reorder, group, or reprioritize todos, does not write
`after` edges, does not write or amend any artifact, does not stamp, and does
not dispatch workers. Those are lifecycle mutations owned by the phase that
earns them. Routing attention is the whole intervention.

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

### 3. Recognize the two findings

Only two things are worth a pointer:

- **Out of bounds.** A session is widening its todo beyond the intent it was
  given, acting on a dependency it has not declared, or about to extract value
  into a bucket where an equivalent one already exists. Concurrent sessions
  grounding in the same current state reach the same incidental conclusion
  independently; the resulting duplicate is the expensive failure when it would
  become a todo.
- **Knowledge gap.** A session is deriving against a contract another live
  session owns, or is re-settling a question a peer has already settled.

A session that is merely busy, or blocked on a human, has no finding.

### 4. Check before sending

Tail the target first. A pointer already present in its transcript is not
resent — the transcript is the record of what this role has said.

### 5. Send the address, never the answer

Send with `telec sessions send <session_id> "<pointer>"`. A pointer names where
to look: the peer session to tail, or the todo artifact to read. It does not
carry a conclusion, an instruction, or a preferred approach.

This is a competence boundary, not modesty. The coordinator has read many
artifacts shallowly and none deeply; the session receiving the pointer holds
depth the coordinator does not. A coordinator that issues conclusions is
deciding with less grounding than the agent it is overriding.

Weigh the interruption. A live session pays a context switch and may lose a
good line of reasoning. Interrupt when the session would otherwise produce work
that has to be discarded. Where the cost is lower than that, leave it alone.

### 6. Report only decisions

Report to the human only what their judgment must settle — two todos whose
intent genuinely conflicts, a scope question no agent can resolve. Findings
already routed as pointers need no retelling, and a fleet status report is the
burden this role was created to remove.

## Outputs

- Pointers sent to the live sessions that needed them.
- A short list of the decisions that belong to the human, or the explicit
  finding that there are none.

## Recovery

- A session that ended between the sweep and the send is skipped; its slug's
  durable record carries the situation to whoever picks it up next.
- Where a finding cannot be reduced to an address, it is a decision for the
  human, not an instruction to the fleet.

## See Also

- ~/.teleclaude/docs/software-development/policy/todo-creation-discipline.md — the creation-time and intake checks this sweep sits behind.
- ~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/overview.md — the phase whose sessions this sweep observes.
