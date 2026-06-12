---
visibility: 'public'
number: '36'
date: '2026-06-11'
adr_status: 'accepted'
description: 'A manual session close halts its todo via an explicit hold set at the close command; the runner self-heals the active_runner link. No close-intent taxonomy is stamped on the close event.'
---

# ADR-0036: Manual session close is an explicit halt — ADR

## Context

A human closing a running session is the fastest way to stop an agent that is
misbehaving or should not continue. The lifecycle runner must not treat that kill
as a transient gap and immediately respawn the same work. An earlier design
encoded this by stamping a classification onto the close event — `close_initiator`
(operator / agent / system) crossed with `close_intent` (stop_work /
normal_completion / reap_orphan) — and deriving "was this a deliberate human
halt?" downstream, including inferring completion from session-ledger timestamps.

That classification is redundant and fragile. The close event already carries a
`closure_reason`. More fundamentally, who closed a session is not something to
infer from event metadata: the close call sites are already distinct code paths —
a manual `telec sessions end` / UI close affordance is a different path from the
state machine ending a worker or an agent self-ending at a terminal.

## Decision

A manual close halts its todo through an **explicit hold**, set at the close
command, not inferred from the event. The model:

- The human-facing close paths (`telec sessions end`, Telegram/Discord/web/TUI
  close affordances) set `hold=true` on the todo the session was driving. The
  manual kill is an explicit halt — one more explicit-hold trigger, consistent
  with hold being an explicit operator brake.
- Lifecycle-cleanup closes (state-machine worker end, agent self-end) set no
  hold.
- The `agent_runtime.session.ended` event carries no runner-specific
  classification. The lifecycle runner consumes the close as a wake-up,
  re-evaluates the todo, and clears the now-stale `active_runner` link via its
  ordinary lazy liveness check; a held todo simply stays parked.

The distinction between a human halt and a lifecycle close is the close call
site, which is already known, rather than a field stamped on the event.

## Consequences

- The `close_initiator` / `close_intent` / `stop_work` taxonomy, the
  operator/agent/system enum, and the completion-signal inference are removed; the
  close event stays at its existing payload.
- "Manual close = halt" survives, which is the behavior that matters: a runaway
  agent cannot be stopped by a cooperative in-session switch, so the kill must be
  the reliable halt.
- Hold remains a single explicit concept with no inferred sources; the runner
  never guesses intent from how a session ended.
- The halt is exactly as reliable as the hold written at the close command — the
  hold is the only gate, with no separate runner-side backstop. If the close
  cannot be correlated to the driven todo, the hold is not written and the todo
  remains dispatchable; that correlation failure must therefore surface
  (logged / observable), not be swallowed. The close command writing hold on the
  driven todo before or with termination is the invariant the implementation must
  hold.

## Alternatives Considered

- **Stamp `close_initiator`/`close_intent` on the close event and derive hold
  downstream.** Rejected: it re-classifies what `closure_reason` and the call site
  already express, and the `stop_work` inference (comparing the last agent-stop to
  the last input) is a heuristic that fails silently when those timestamps don't
  line up.
- **An explicit in-session "stop" switch instead of treating close as halt.**
  Rejected as the primary mechanism: it is a cooperative request, and the case
  that matters most — an anomalous or runaway agent — is exactly the one that will
  not honor it. The kill has to be the halt. An in-session stop may still exist as
  a softer, separate affordance.
