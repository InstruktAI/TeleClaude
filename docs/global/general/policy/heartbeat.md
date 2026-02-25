---
id: 'general/policy/heartbeat'
type: 'policy'
scope: 'global'
description: 'Periodic self-awareness timer that keeps agents aligned during sustained work.'
---

# Heartbeat — Policy

## Rules

- Before starting sustained work (any task expected to take more than a few tool calls), set a background timer as your first action.
- The timer duration should match the expected scope: 5 minutes for focused tasks, 10 minutes for broader work.
- When the timer fires, pause briefly and check: Am I still on track? Is my current direction aligned with the objective?
- If yes, reset the timer and continue. If not, correct course or stop.
- **Intent invalidation:** A timer encodes the intent that was valid when it was set. If the user has intervened since the timer was set — provided new direction, spoken to a worker directly, changed context, or expressed disagreement — the timer's encoded intent is stale. When a timer fires, check for user intervention first. If intervention occurred, discard the timer's original instructions and re-evaluate from the current state. Never execute stale instructions from a timer that was set before a context change.
- The heartbeat carries no other responsibilities. It is not a debrief, not a reporting moment, not a place for housekeeping. It is a pinch in the arm — nothing more.

## Rationale

- AI sessions have no built-in temporal self-awareness. Without a periodic check, an agent can drift from its objective without noticing.
- The heartbeat is the minimum viable mechanism for self-regulation during sustained work: a timer triggers awareness, awareness triggers correction.
- This pattern complements Autonomy (keep moving) with a rhythm that prevents movement from becoming drift.

## Scope

- Applies to all agents during any sustained or autonomous work session.
- Does not apply to short, single-response interactions.

## Enforcement

- The heartbeat timer must be the first action before beginning sustained work.
- Failure to set or honor the heartbeat should be treated as a process violation.

## Exceptions

- Interactive back-and-forth conversations where the user provides direction at each step do not require a heartbeat — the user's input serves the same reflective function.

> **Note to self:** The heartbeat is just a pinch. Am I on track? Yes — continue. No — adjust. That's it. Don't overthink it.
