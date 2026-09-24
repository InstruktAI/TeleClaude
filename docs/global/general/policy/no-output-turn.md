---
description: How an agent closes a turn that warrants no output, and why a prose stand-in
  for silence is not silence.
---

# No-Output Turn — Policy

## Rules

- **A turn that owes nothing closes with the sentinel `NOOP` and nothing else** —
  no preamble, no trailing remark, no formatting around it. No runtime can end a
  turn with no output, so silence is something an agent says, never something it
  omits.
- **Output is owed when it changes what the receiver does next**: it answers a
  question asked, reports a blocker, contradiction, scope change, or decision
  point, carries information that changes the receiver's next move, or delivers a
  result. `general/spec/agent-shorthand` enumerates validity for agent-to-agent
  exchanges.
- **A prose stand-in for silence is output.** "Standing by", "nothing further",
  "acknowledged", "going quiet", a lone dash — each is delivered, and between
  linked peers each wakes the other into answering. An instruction to stay silent
  is discharged by the sentinel and nothing else. Decorating the sentinel makes it
  one of these.
- **The sentinel closes the turn and does nothing else.** It never signals
  agreement, completion, or readiness, never stands in for a command's act, and
  no contract may give it a second consequence.
- **Where a bare-sentinel turn is suppressed is the platform's decision, not the
  agent's.** The platform owns which surfaces drop such a turn, and the raw
  transcript retains it either way — the sentinel is the agent's own write to
  its own transcript, never something the platform edits back out. Use it
  because nothing is owed, never because of where the turn would land.

## Rationale

An instruction to stay silent must be satisfiable. The sentinel is the one
authored output the platform is built to drop on the surfaces it suppresses it
from, so the turn closes there without reaching anyone; every invented
surrogate is a message, and between linked peers surrogates sustain the
exchange they were meant to end.

A single meaning is what makes the sentinel safe to reach for on any turn. Any
second consequence would force an agent to withhold it when that consequence is
unwanted — and back to inventing prose.

## Scope

All agents, all sessions, every turn whose authored output would otherwise be
nothing.

## Enforcement

A reviewer, a peer, or the agent's own next turn names a prose stand-in as the
acknowledgement it was written to avoid. A contract that assigns the sentinel a
second consequence is a defect in that contract.

## Exceptions

None.

## See Also

- ~/.teleclaude/docs/general/principle/attunement.md — silence as a valid response, and the phase reading that decides when nothing is owed.
- ~/.teleclaude/docs/general/spec/agent-shorthand.md — the enumerated output-validity contract for agent-to-agent exchanges.
- ~/.teleclaude/docs/general/policy/reminder.md — the reminder firing that closes with the sentinel.
