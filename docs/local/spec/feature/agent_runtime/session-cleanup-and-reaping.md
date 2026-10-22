---
description: 'agent_runtime — terminate a session, free its host-pane + workspace + tmpdir resources, sweep orphans, and replay close-requested events for sessions whose channel cleanup never completed.'
visibility: 'public'
---

# Session Cleanup and Reaping — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The cleanup half of agent_runtime session lifecycle. Where `session-lifecycle` accepts a close request, this surface performs it: token revocation, host-pane termination, conversation-link teardown, listener cleanup, adapter channel deletion, workspace removal, per-session tmpdir removal, temporary runtime resource removal, escalation teardown, inbound expiry, and the final `closing -> closed` lifecycle write.

It also reconciles the gap between what durable storage believes and what the system holds: stale sessions (storage-active but host-pane-gone), orphan host-pane sessions (TeleClaude-prefixed host pane with no storage row), orphan workspace directories (UUID-named directory under the workspace base with no storage row), and orphan per-session tmpdirs (UUID-named subdirectory under the configured tmpdir base, not bound to a live session).

Finally, it provides the recently-closed replay mechanism: a sweep that re-emits a session-close request for closed sessions whose adapter channel reference is still set — recovering channel-deletion work that was dropped across a service restart.

The cleanup loop runs on the maintenance service tick (every hour by default). An end-session request reaches the termination flow synchronously via the command service.

## Canonical fields

### Durable session identity

Every session record survives normal close, stale-runtime cleanup and removal.
Close and soft deletion are distinct facts: closing ends execution, while soft
deletion removes ordinary navigation and automatic continuation eligibility.
Exact-id historical retrieval remains subject to the existing reach rules.
Restoration retains the original TeleClaude identity. Ephemeral process, token,
listener and temporary-directory cleanup remains available independently of the
retained record (`general/principle/trust-and-guardrails`). The agent_runtime
domain contract owns the kind, origin and once-per-ending emission of
`session.ended`; this cleanup surface performs the close write that triggers it.
An end request for an absent session has no cleanup side effects. A retry for an
already-closed session may reap leftover resources without changing its closure
state or emitting another ending event.

### Terminal source reconciliation

Post-close worker and polling cleanup consumes current terminal source state.
On live-reader handover the runtime rechecks resident worker identities and
workflow driver references, including references to closed or soft-deleted
sessions. Workflow reconciliation clears only references still naming the
terminal session and starts no new workflow work. The existing minute-driven
workflow reconciliation supplies subsequent repair independently of historical
close notifications, under `sdlc/policy/domain-ownership`.

The runtime owner is acquired outside the closing command's source-change
callback. This ownership separation follows
`local/projects/teleclaude/design/architecture/event-delivery`.

### Host binding release

Termination retains the host binding while its host remains available. Once the
runtime establishes host termination or absence, it publishes that release
through the existing session binding update before slow remaining cleanup.
The session stays closing until its final lifecycle write. The host-access
projection is owned by
`local/projects/teleclaude/spec/feature/agent_runtime/host-pane-access`.

A failed or inconclusive observation retains the binding. Binding-publication
failure is reported within the existing best-effort post-termination cleanup;
remaining resource cleanup and finalization retain their existing progression.
The original host identity remains available to that cleanup's process-reap
diagnostics. This resource observation and its publication follow
`sdlc/policy/domain-ownership`; consumers receive the published fact rather than
deciding host availability from close intent.

### Process and startup ownership

Cleanup attempts to resolve and reap the host-pane process tree within a bound
before removing its per-session temporary directory. If the tree cannot be
resolved or exit remains unconfirmed at timeout, cleanup proceeds with
temporary-directory removal and the final lifecycle write; known surviving
process ids are recorded. During startup, the expected host-pane name for a
session whose binding is not yet persisted still counts as owned, so the orphan
sweep cannot terminate it.

### Use cases

#### UC-SCR-1: Host-pane processes are reaped before per-session tmpdir removal

#### UC-SCR-2: Order of operations is fixed

#### Already-closed session

#### UC-SCR-8: An interrupted close finalizes on the next terminate-session

```gherkin
Given an operator requested a session close that was interrupted before the session finished closing
When they retry the close
Then the existing session reaches its closed state
And the operator receives the ordinary close result
```

#### UC-SCR-9: A starting session's host pane survives the orphan-host-pane sweep

#### UC-SCR-10: A purged Claude session's Claude Code temp directory is removed

```gherkin
Given an operator permanently removes an ended Claude session
When cleanup completes
Then that session's temporary workspace is removed without touching another session's files
And an ordinary close preserves the temporary workspace for a possible revival
```

#### UC-SCR-11: Every session that ends is reported once, typed by the kind of session it was

#### UC-SCR-12: An ending is reported once, and a later ending again

#### UC-SCR-3: A person can find a closed session after cleanup

```
Given a human operator has closed a session
When runtime maintenance reclaims its temporary resources
Then its TeleClaude session record and transcript lineage remain addressable
And historical references continue to resolve
```

#### UC-SCR-4: An operator can remove a session from navigation without erasing its history

```
Given a human operator removes a session from ordinary navigation
When that removal is applied and later retention maintenance runs
Then the session is soft-deleted and remains absent from ordinary selection
And its identity, historical content and source relationships are retained
And maintenance never hard-purges that record
```

#### UC-SCR-5: Adapter stale-thread reconciliation reaches project-specific session forums

#### UC-SCR-6: A desk's customer-sessions threads reflect its open sessions

#### UC-SCR-7: Escalation relay threads reflect active relays

### Cross-context references

- **agent_runtime domain / session_mirrors** — the domain contract owns the `session.ended` event family and its typed kind/origin; session_mirrors consumes it. Mirror extraction at session-end depends on the lifecycle write running, which is why this cleanup module guarantees the final close-session even when intermediate cleanup steps raise.
- **integration** — the escalation-end step clears relay status / Discord channel binding / relay-started-at on the session and emits `session.escalation_ended` (CLUSTER visibility) so the escalation integration can drop its corresponding Discord channel binding. The adapter-channel deletion side runs via the adapter client's delete-channel inside the resource-cleanup step. Integration owns stale Discord-thread reconciliation and which computer may remove those threads; this surface supplies per-session cleanup inputs.
- **workflow** — sessions spawned by orchestrators register one-shot stop-listeners on creation (see `session-lifecycle`); the resource-cleanup step removes both target-side and caller-side listener rows so notifications stop firing for the dead session.

## Known caveats

- **The lifecycle write at the end is non-negotiable.** Every intermediate step after host-pane termination is wrapped in best-effort error handling specifically so a single hiccup (e.g., a removal race on a per-session tmpdir) cannot strand a session at `lifecycle_status=closing`. If the lifecycle write were skipped on an inner failure, the session would be invisible to both the live UI and the close-reaper sweep.
- **Resource cleanup does NOT touch the lifecycle write.** Callers handle the lifecycle write; the resource-cleanup helper is purely for adapter / filesystem / listener teardown. The split exists so terminate-session and stale-session cleanup can both reuse the same resource sweep with different lifecycle intentions (close vs soft deletion).
- **Headless sessions are excluded from stale detection.** They have no host-pane reference to consult, so stale detection short-circuits to false for them — they only ever close via explicit user/agent action.
- **Stale detection has a 10-second race-condition floor.** Sessions younger than 10 seconds are skipped to avoid reaping a just-created session whose host pane has not yet appeared.
- **Orphan-tmpdir sweep has a 10-minute race-safety window.** A tmpdir freshly created for a brand-new session is invisible to the sweep until its modification time ages past the window. The window is necessary because the row insert (which makes the session id "live") and the tmpdir creation are not co-transactional.
- **Symlink-escape guards on tmpdir removal.** Single-session and orphan-tmpdir sweeps both refuse to traverse symlinks and check that the resolved path remains under the configured base. A maliciously symlinked tmpdir cannot trick the sweep into removing arbitrary paths.
- **The recently-closed sweep re-emits a session-close request, not a session-closed event.** This is deliberate — it routes back through termination's idempotent path so the channel reference gets cleared on the second pass. Re-emitting a session-closed event would not run the channel-delete logic.
- **Orphan sweeps are time-bound to the maintenance tick (~1 hour).** There is no startup sweep that runs these unconditionally on boot — the first sweep happens immediately on periodic-cleanup entry (the first-run flag skips the initial sleep), but a freshly-rebooted service that crashes again within minutes can carry orphans across two restarts before they are observed.
- **The in-flight cleanup set is process-local.** Two service processes claiming the same session (which should not happen — there is one service per machine) would not coordinate through this guard. The guard exists to deduplicate parallel events within a single service, not to provide cross-process exclusion.
- Removal changes visibility of the retained session record. Resource cleanup,
  stale-session recovery and retention sweeps preserve its durable identity,
  transcript lineage and mirror relationships.

- **The single session-ended type is retired, not renamed.** Endings are
  reported only under the kinded types, so a subscriber selects one kind or
  every ending through the shared prefix. The lifecycle runner's consumer also
  accepts the retired name until no computer emits it and no entry under it
  remains in the platform event stream, so an ending reported under it before
  an upgrade still wakes the runner whenever the consumer reads it.
  No other consumer is affected across versions: procedure activation acts only
  on endings its own computer emitted, and no published procedure subscribes to
  the retired name. An older computer keeps emitting that name until it is
  upgraded, and events stored under it stay as recorded. Reverting the change
  restores the single type; kinded endings already emitted are ignored by a
  computer that does not know them.
