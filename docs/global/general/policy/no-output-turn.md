---
description: How an agent closes a turn that warrants no output, and why a prose stand-in
  for silence is not silence.
---

# No-Output Turn — Policy

## Rules

- **A turn that owes nothing closes with the sentinel `NOOP` and nothing else.**
  No agent runtime can end a turn having authored no output, so silence is
  something an agent says, never something it omits. The sentinel is that turn's
  entire authored content: no preamble, no trailing remark, no formatting around
  it.
- **Output is owed when it changes what the receiver does next** — it answers a
  question that was asked, reports a blocker, contradiction, scope change, or
  decision point, carries information that changes the receiver's next move, or
  delivers a result or artifact. `general/spec/agent-shorthand` carries the
  enumerated validity contract for agent-to-agent exchanges.
- **A prose stand-in for silence is invalid output, not an escape from it.**
  "Standing by", "nothing further", "acknowledged", "going quiet", a lone dash,
  and every other way of writing nothing are substantive turns: they are
  delivered, they reach the receiver, and between linked peers they wake the
  other side into answering them. An instruction to stay silent is discharged by
  the sentinel and by nothing else.
- **The sentinel closes the turn and does nothing else.** It carries the same
  single meaning on every turn, whatever that turn received. It never signals
  agreement, completion, or readiness, never stands in for an act a command
  performs, and no contract gives it a second consequence.
- **Where a bare-sentinel turn is suppressed is the platform's decision, not the
  agent's.** The platform owns which surfaces drop such a turn, and the raw
  transcript retains it either way. An agent uses the sentinel because nothing is
  owed, never because it predicts where that turn would have landed.

## Rationale

An agent instructed to stay silent, with no way to say nothing, invents one — and
every invention is a message. Two linked peers each invented a different prose
surrogate and spent eleven turns telling each other they had stopped talking;
each surrogate was substantive output, was cross-shared, and woke the peer into
producing the next one. The sentinel exists so the instruction is satisfiable: it
is the one authored output the platform is built to drop, so the turn closes
without reaching anyone.

Keeping the sentinel's meaning single is what makes it safe to reach for on any
turn. A sentinel that also retired a reminder, confirmed a handoff, or signalled
readiness would have to be withheld whenever those consequences were unwanted —
and an agent that cannot use it freely is back to inventing prose.

## Scope

All agents, all sessions, every turn whose authored output would otherwise be
nothing: agent-to-agent exchanges, reminder firings, and any turn an agent takes
with nothing owed to anyone.

## Enforcement

- A turn whose authored content is a prose stand-in for silence is invalid
  output. A reviewer, a peer, or the agent's own next turn names it as the
  acknowledgement it was written to avoid.
- Decorating the sentinel — prefixing it, explaining it, or pairing it with a
  status line — produces a substantive turn and is the same violation.
- A contract that assigns the sentinel a consequence beyond closing the turn is a
  defect in that contract.

## Exceptions

- None. An agent that owes output writes that output; the sentinel is for the
  turn that owes none.

## See Also

- ~/.teleclaude/docs/general/principle/attunement.md — silence as a valid response, and the phase reading that decides when nothing is owed.
- ~/.teleclaude/docs/general/spec/agent-shorthand.md — the enumerated output-validity contract for agent-to-agent exchanges.
- ~/.teleclaude/docs/general/policy/reminder.md — the reminder firing that closes with the sentinel.
