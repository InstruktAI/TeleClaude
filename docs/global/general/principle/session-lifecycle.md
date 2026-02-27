---
id: 'general/principle/session-lifecycle'
type: 'principle'
scope: 'global'
description: 'Sessions are ephemeral expressions; artifacts carry continuity. Callers clean up children, then themselves. Signal sessions persist only when human attention is required.'
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

- **Artifacts are the evidence trail.** The todo folder (`state.yaml`, `dor-report.md`,
  `requirements.md`, `implementation-plan.md`) is the durable record. Design artifacts
  to be self-contained and readable by any future agent or human.
- **Caller ends child, then itself.** The session that dispatched a worker is responsible
  for ending it after confirming the outcome. Then it ends itself. This is the standard
  cleanup order.
- **Signal sessions persist.** When a verdict is `needs_decision` or blockers require
  human input, the session holding the signal stays alive. It is the only session that
  should remain. The caller ends itself and trusts the signal to be visible.
- **Direct conversation before escalation.** When quality is insufficient but fixable
  by the agents involved (`needs_work`), the caller opens a direct conversation with
  the worker. Two agents who just produced and validated the same artifacts are the best
  pair to resolve gaps. Only `needs_decision` — genuinely unresolvable blockers — reaches
  the human.
- **Heartbeat as safety net.** After dispatching a worker, the caller sets a periodic
  check. If the notification mechanism is flaky, the heartbeat catches it by tailing the
  worker session. The heartbeat is not supervision — it is a safety net for delivery
  failures.
- **Workers go idle, not self-destruct.** Workers complete their work and stop. They do
  not end their own sessions. The caller decides when to clean up based on the outcome.
- **Caller verifies artifact delivery.** Before ending any session, the caller confirms
  that all expected artifacts exist and contain the correct verdict. If artifacts are
  missing or stale (e.g., reverted by a hook), the caller reconstructs them directly —
  it has full context from running the earlier phase. Artifact recovery is never
  delegated back to the worker.

## Tensions

- **Signal vs. noise**: Keeping sessions alive for observability conflicts with keeping
  the session list clean. The resolution is precise: only signal sessions persist. Everything
  else is ended by its caller.
- **Autonomy vs. lifecycle control**: Workers are autonomous in _what_ they do but not in
  _when they end_. This asymmetry is intentional — the caller has context the worker lacks.
- **Ephemeral sessions vs. auditability**: If sessions are ended, their transcripts may
  become harder to access. The resolution is that artifacts carry the audit trail, not
  transcripts. Transcripts are working memory; artifacts are the record.
- **Direct conversation cost vs. human escalation cost**: Two agents iterating costs tokens.
  But human context-switching costs more. The threshold is clear: agents iterate on
  `needs_work`, humans handle `needs_decision`.
