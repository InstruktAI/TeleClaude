---
description: A live single-agent availability event updates only the agent it names — every other agent's rendered availability in a running TUI stays intact, with no restart required.
delivered_by:
  - tui-agents-show-question-mark-after-status-change
---

# Agent Availability Visibility — Spec

## What it is

The running TUI renders agent availability — the footer pills and the agent
selection surfaces — from an availability map seeded with the full authoritative
set at bootstrap and kept current by live single-agent availability events. A
live event carries exactly one agent's state and updates exactly that agent's
rendered status; the rendered status of every other agent continues to reflect
the last authoritative state, with no restart required.

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
