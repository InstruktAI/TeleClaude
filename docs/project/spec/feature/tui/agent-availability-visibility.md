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

#### UC-TAAV-1: A single-agent status change leaves other agents' rendered status intact

```
Given a running TUI whose bootstrap loaded availability for all configured agents
When a live availability event arrives for one agent
Then that agent's rendered status reflects the event
And every other agent's rendered status is unchanged
And no other agent renders the unknown marker
```

#### UC-TAAV-2: Agent availability pills are display-only

```
Given a running TUI that renders agent availability pills
When an operator clicks an availability pill
Then no agent availability state is changed
And no agent-status mutation request is sent
```
