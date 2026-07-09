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

Authoritative reconciliation runs at three moments: at mount, on every websocket
reconnect, and periodically while the TUI is running. Live websocket deltas keep
the view responsive between those moments, but they are an optimization over the
authoritative set — never its sole source. Because reconciliation is periodic and
not tied to any single delivery, a session whose activation was never delivered
to a given running TUI (a websocket down at that instant, a dropped push) becomes
visible within one reconciliation cycle rather than staying invisible until the
TUI is restarted.

## Canonical fields

### Use cases

#### UC-SVIS-1: A session missed by live delivery becomes visible on reconciliation

```
Given an agent-spawned session that is active in the authoritative session store
And a running TUI that never received a live event announcing that session
When the TUI's periodic session reconciliation runs
Then the session appears in the TUI Sessions view without a TUI restart
```

#### UC-SVIS-2: A pre-activation session is included in the authoritative bootstrap set

```
Given open sessions in the authoritative store spanning lifecycle statuses — active, initializing (pre-activation), closing, and escalated — alongside a closed session
When the TUI reads the authoritative bootstrap route it reconciles against (the sessions pillar of GET /tui/bootstrap)
Then the returned set is exactly the active and initializing sessions
And it excludes the closing, escalated, and closed sessions
```
