---
description: The TUI Sessions view reflects authoritative session state — a session
  that is active in the authoritative store appears in the view, reconciled independently
  of any single live event.
---

# Session Visibility — Spec

## What it is

The TUI Sessions view is a projection of authoritative session state, not a
ledger of the live events it happened to receive. A session that is active in
the authoritative session store is visible in the view; a session that has
closed is not.

The TUI pulls authoritative state once at startup. After that, session state is
push-driven: every websocket subscription or reconnect receives an authoritative
`sessions_initial` snapshot, and session lifecycle events apply incremental
deltas between snapshots. The TUI performs no periodic or reconnect-initiated
session pull. A targeted sessions pull is reserved for an explicit server-pushed
lifecycle error that requires reconciliation.

## Canonical fields

### Use cases

#### UC-SVIS-1: A session missed by live delivery becomes visible from the reconnect snapshot

```
Given an agent-spawned session that is active in the authoritative session store
And a running TUI that never received a live event announcing that session
When the websocket reconnects and the server pushes its authoritative sessions snapshot
Then the session appears in the TUI Sessions view without a TUI restart
And the TUI does not issue a reconnect-initiated session pull
```

#### UC-SVIS-2: A pre-activation session is included in the authoritative bootstrap set

```
Given open sessions in the authoritative store spanning lifecycle statuses — active, initializing (pre-activation), closing, and escalated — alongside a closed session
When the TUI reads the sessions pillar of GET /tui/bootstrap during startup
Then the returned set is exactly the active and initializing sessions
And it excludes the closing, escalated, and closed sessions
```

#### UC-SVIS-3: A pushed lifecycle error triggers targeted reconciliation

```
Given the server pushes a session lifecycle error that requires reconciliation
When the TUI handles that error
Then it pulls only the sessions bootstrap pillar
And normal lifecycle events never trigger a session pull
```
