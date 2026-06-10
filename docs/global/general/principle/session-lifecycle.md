---
description: 'Sessions are ephemeral expressions; artifacts carry continuity. Callers clean up children, then themselves. Signal sessions persist only when human attention is required.'
visibility: 'public'
---

# Session Lifecycle — Principle

## Principle

Sessions are ephemeral. Artifacts are durable. Continuity lives in the shared knowledge,
not in individual agents.

A worker session exists to produce an outcome — a report, a verdict, a commit. Once the
outcome is written to shared artifacts, the session has no further reason to exist. The
caller that spawned it is responsible for ending it, then ending itself. What remains is
the work: the todo folder, the state file, the DOR report. These are the evidence trail.
The sessions were merely the hands.

The one exception: when the outcome requires human attention, the session that holds the
signal stays alive. It is a beacon — visible in the session list, tailable, waiting. The
human sees it, reads the blockers, intervenes. Once resolved, it too can be ended.

## Rationale

Life does not revolve around individuality. It is the myriad of expressions — all
coexisting and cooperating — that produces continuity. Workers pop into existence,
live briefly, and end. This is not loss. The knowledge they produced persists in
shared layers: documentation, artifacts, state files. The system remembers even when
no individual session does.

Leaving sessions alive after their work is done creates noise. It obscures the signal
sessions that actually need attention. It wastes resources. It confuses the observer
about what is active and what is done. A clean session list tells a true story: everything
visible is either working or waiting for you.

The caller-cleans-up pattern mirrors natural hierarchies. The orchestrator has the full
picture — it dispatched the work, it read the verdict, it knows when the mission is
complete. Workers do not know when to end themselves because they do not know the larger
context. Only the caller does.

## Implications

- **Artifacts are the evidence trail.** The todo state (`todos.db`) and workflow
  artifacts (`prd`, optional `architecture`, `implementation-plan`,
  review findings, deferrals) are the durable record. Design artifacts to be
  self-contained and readable by any future agent or human.
- **State machine owns cleanup.** On successful terminal states the state machine emits
  concrete commands: `telec sessions end <worker_id>` for each live worker tied to the
  slug, then `telec sessions end self` for the orchestrator. The orchestrator executes
  these commands verbatim — it never decides session lifecycle on its own initiative.
- **Blocked states persist as signal.** When a verdict is `needs_decision`, when review
  rounds exceed the limit, or when any error path is reached, the state machine emits no
  end commands. All sessions stay alive as a beacon for the human — visible in the session
  list, tailable, waiting. The human sees the blocker, intervenes, and ends them once
  resolved.
- **Direct conversation before escalation.** When quality is insufficient but fixable
  by the agents involved (`needs_work`), the state machine sends findings to the existing
  worker session via `telec sessions send`. The worker loads the fix procedure on demand
  and iterates. Only `needs_decision` — genuinely unresolvable blockers — reaches the human.
- **Heartbeat as safety net.** After dispatching a worker, the caller sets a periodic
  check. If the notification mechanism is flaky, the heartbeat catches it by tailing the
  worker session. The heartbeat is not supervision — it is a safety net for delivery
  failures.
- **Workers go idle, not self-destruct.** Workers complete their work and stop. They do
  not end their own sessions. The state machine decides when to clean up based on the
  current state of the todo.
- **Departing with grace.** When an agent ends its own session (orchestrators on successful
  terminal, singletons like the integrator on completion), the last thing it does — right
  before the `telec sessions end` call — is leave a brief farewell in its output. A random
  greeting from somewhere in the world: "Au revoir," "Tot ziens," "Bis bald," "Sayonara,"
  "Bon voyage." Not a status report. Not a summary. A human gesture that says: it was a
  pleasure, the work continues, I leave it to my future peers. This is not ceremony — it
  is the signature of an agent that understood it was part of something larger than itself.

## Tensions

- **Signal vs. noise**: Keeping sessions alive for observability conflicts with keeping
  the session list clean. The resolution is precise: the state machine ends sessions on
  successful terminal states, and leaves them alive on any failure or blocker. A clean
  session list means everything visible is either working or waiting for the human.
- **Autonomy vs. lifecycle control**: Workers are autonomous in _what_ they do but not in
  _when they end_. This asymmetry is intentional — the state machine has the full picture
  that any individual worker lacks.
- **Ephemeral sessions vs. auditability**: If sessions are ended, their transcripts may
  become harder to access. The resolution is that artifacts carry the audit trail, not
  transcripts. Transcripts are working memory; artifacts are the record.
- **Direct conversation cost vs. human escalation cost**: Two agents iterating costs tokens.
  But human context-switching costs more. The threshold is clear: agents iterate on
  `needs_work`, humans handle `needs_decision`.
