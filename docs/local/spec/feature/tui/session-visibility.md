---
description: The TUI Sessions view projects the daemon's viewer-authorized open-session state through a complete connection snapshot and subsequent state changes.
---

# Session Visibility — Spec

## Required reads

@docs/local/adr/0013-unified-cluster-events.md

## What it is

The TUI Sessions view projects session state delivered by the daemon. The daemon
owns peer discovery, its consolidated local and remote session view, and viewer
eligibility. Eligibility follows identity reach
(`local/projects/teleclaude/design/architecture/scoped-roles`) and the attended
session policy (`local/projects/teleclaude/spec/feature/agent_runtime/procedure-standing-agent`).
Every eligible open session appears regardless of computer, lifecycle status,
human ownership, or current agent activity. Closed and unattended sessions stay
outside the normal view.

The shared UI WebSocket contract is owned by
`local/projects/teleclaude/design/architecture/api-server`. The TUI receives a
complete viewer-authorized session snapshot when the connection opens or
reconnects, followed by state changes on that connection. A discovered peer's
sessions enter the same view when the daemon receives their state. Static peer
configuration and client-maintained peer membership do not determine delivery.

Only the session stream changes the TUI's session collection. HTTP bootstrap
responses and refreshes of other resources leave that collection intact.
HTTP session reads remain available to command callers and provenance lookups.
When a lifecycle failure requires reconciliation, the daemon supplies a fresh
session snapshot through the connection.

A complete snapshot replaces the eligible session set. Absence from a snapshot
removes a row from the view without declaring the session closed. A session
closure is reflected as closure only when the daemon reports that fact. Reach
changes reconcile the view from the daemon's current eligibility decision;
closed-session cleanup remains deliverable to a connection previously shown the
session.

The TUI renders the delivered state and applies its local presentation choices.
It performs no periodic session polling or fleet discovery.

## Canonical fields

### Use cases

#### UC-SVIS-1: A session missed by live delivery becomes visible from the reconnect snapshot

```gherkin
Given a human operator viewing sessions they may access
And an eligible open session absent from that view after a connection interruption
When the view reconnects to the daemon
Then the session appears from the daemon's complete session snapshot
And the operator does not need to restart the TUI
```

#### UC-SVIS-2: Every eligible open lifecycle state is included at startup

```gherkin
Given a human operator whose reach includes local and remote projects
And attended open sessions in those projects spanning active, initializing, headless, closing, and escalated states
And sessions that are closed, unattended, or outside the operator's reach
When the operator opens the TUI Sessions view
Then the view contains every eligible open session regardless of agent activity or human ownership
And the ineligible sessions remain outside the view
```

#### UC-SVIS-3: A lifecycle failure reconciles the view from the daemon

```gherkin
Given a human operator whose session view needs reconciliation after a reported lifecycle failure
When the daemon reports the failure
Then the daemon supplies its current eligible session set to the view
And the view reflects that set without a separate session read
```

#### UC-SVIS-4: A session left out of a snapshot is not recorded as closed

```gherkin
Given a human operator viewing a live session they may access
When the operator's reach changes and the daemon supplies a complete snapshot without that session
Then the session leaves the view
And its absence does not mark the session closed or create a closure in pane or provenance state
```

#### UC-SVIS-5: An unattended procedure agent never enters the normal view

```gherkin
Given an unattended procedure agent is open in a project a human operator may access
When the operator's view starts, reconnects, or receives a change to that agent's session
Then the normal Sessions view does not show that agent
```

#### UC-SVIS-6: A newly discovered peer's idle sessions enter the running view

```gherkin
Given a human operator viewing sessions on a running TUI
And another computer with eligible open sessions whose agents are idle
When the daemon discovers that computer and receives its session state
Then those sessions appear in the running view
And the operator does not need to configure the peer or restart the TUI
```

#### UC-SVIS-7: A resource refresh cannot replace newer session state

```gherkin
Given a human operator's session view has received current session state from the daemon
And an earlier HTTP request or a refresh of another resource is still completing
When that response reaches the TUI
Then the session collection continues to reflect the current session stream
```

## Known caveats

The view reflects the daemon's consolidated state. Recovery of cluster events
missed by an offline daemon belongs to the cluster's bootstrap contract, not to
UI reconciliation.

## See Also

- docs/local/design/architecture/api-server.md
