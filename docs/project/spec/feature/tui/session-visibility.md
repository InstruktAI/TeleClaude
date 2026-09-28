---
description: The TUI Sessions view reflects authoritative session state — a session
  that is active in the authoritative store appears in the view, reconciled independently
  of any single live event.
---

# Session Visibility — Spec

## What it is

The TUI Sessions view is a projection of the authoritative session state the
viewer's role reaches (`project/design/architecture/scoped-roles`), not a ledger
of the live events it happened to receive. Every open session in the
authoritative session store whose project the viewer's effective role reaches
above `customer` is visible, regardless of lifecycle status or human ownership,
and so are the sessions other computers share with this one when the viewer
holds a platform role; a session whose `closed_at` is set is not.

A session absent from a snapshot is out of the viewer's view, not closed: the
TUI drops it from the view without recording a closure, and only a
`session_closed` event records one. When the viewer's role stops reaching a
session while the TUI runs, the session receives no further updates on that
connection; a row already shown stays until the session closes — its close
always reaches a connection that was shown it — or until the next snapshot
leaves it out.

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

#### UC-SVIS-2: Every open lifecycle state is included in the authoritative bootstrap set

```
Given open sessions in the authoritative store spanning lifecycle statuses — active, initializing, headless, closing, and escalated — alongside a session whose closed_at is set
And a viewer whose role reaches the projects those sessions run in
When the TUI reads the sessions pillar of GET /tui/bootstrap during startup
Then the returned set contains every open session the viewer's role reaches, regardless of lifecycle status or human ownership
And it excludes the session whose closed_at is set and every session in a project the viewer's role does not reach
```

#### UC-SVIS-3: A pushed lifecycle error triggers targeted reconciliation

```
Given the server pushes a session lifecycle error that requires reconciliation
When the TUI handles that error
Then it pulls only the sessions bootstrap pillar
And normal lifecycle events never trigger a session pull
```

#### UC-SVIS-4: A session left out of a snapshot is not recorded as closed

```
Given a TUI showing a live session in a project the viewer's company owns
And the viewer's membership in that company is withdrawn
When the websocket reconnects and the server pushes the viewer's sessions snapshot without that session
Then the session leaves the TUI Sessions view
And the TUI records no closure for it, and no pane or provenance entry marks it closed
```
