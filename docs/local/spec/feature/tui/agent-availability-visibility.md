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

#### UC-TAAV-1: An operator can see current agent availability in the TUI

```gherkin
Scenario: See one agent's availability change
  Given an operator sees the availability of several configured agents
  When one agent's availability changes
  Then that agent is shown with its new availability
  And the other agents retain their last known availability

Scenario: Keep availability while other information refreshes
  Given an operator sees known availability for every configured agent
  When unrelated information in the TUI refreshes
  Then every displayed agent availability remains unchanged

Scenario: Distinguish unknown availability from available
  Given an operator opens the TUI before availability has been learned for some agents
  When the configured agents are displayed
  Then each agent without known availability is shown as unknown, not available

Scenario: See current availability after reconnecting
  Given the operator's TUI was disconnected
  When it reconnects
  Then the current availability of every configured agent appears without a manual refresh
```

#### UC-TAAV-2: Agent availability pills are display-only

#### UC-TAAV-3: An unrelated refresh preserves known agent availability

#### UC-TAAV-4: Availability not yet learned is displayed as unknown

#### UC-TAAV-5: Reconnection restores authoritative agent availability
