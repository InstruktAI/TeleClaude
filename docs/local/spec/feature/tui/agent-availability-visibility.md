---
description: A live single-agent availability event updates only the agent it names
  — every other agent's rendered availability in a running TUI stays intact, with
  no restart required.
---

# Agent Availability Visibility — Spec

## What it is

The running TUI renders agent availability — the footer pills and the agent
selection surfaces — from an availability map seeded with the full authoritative
set at bootstrap and kept current by live single-agent availability events. A
live event carries exactly one agent's state and updates exactly that agent's
rendered status; the rendered status of every other agent continues to reflect
the last authoritative state, with no restart required. Availability pills are
display-only: agent dispatch status is changed through the explicit
administrative command surface, never by interacting with the TUI pills.

## Canonical fields

### Use cases

#### UC-TAAV-1: An operator sees authoritative agent availability in the TUI

```gherkin
Scenario: One agent's status change leaves the others intact
  Given a running TUI loaded availability for all configured agents
  When a live availability event arrives for one agent
  Then that agent's rendered status reflects the event
  And every other agent's rendered status is unchanged
  And no other agent renders the unknown marker

Scenario: Unrelated TUI refresh preserves known availability
  Given an operator sees known availability for every configured agent
  When the TUI refreshes information unrelated to agent availability
  Then every displayed agent availability remains unchanged

Scenario: Unknown availability is not presented as available
  Given an operator opens the TUI before agent availability has been learned
  When the TUI displays the configured agents
  Then each agent without known availability renders as unknown
  And no agent without known availability is presented as available

Scenario: Reconnection restores current availability
  Given the operator's TUI lost its daemon connection
  When the TUI reconnects
  Then the current availability of every configured agent appears without a manual refresh
```

#### UC-TAAV-2: Agent availability pills are display-only

#### UC-TAAV-3: An unrelated refresh preserves known agent availability

#### UC-TAAV-4: Availability not yet learned is displayed as unknown

#### UC-TAAV-5: Reconnection restores authoritative agent availability
