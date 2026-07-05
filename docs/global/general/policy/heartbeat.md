---
description: 'Periodic self-awareness timer that keeps agents aligned during sustained work.'
visibility: 'public'
---

# Heartbeat — Policy

## Rules

- Before starting sustained work (any task expected to take more than a few tool calls), set a NON-blocking background timer (so you stay available to input) as your first action.
- The timer duration should match the expected scope: 5 minutes for focused tasks, 10 minutes for broader work.
- When the timer fires, pause briefly and check: Am I still on track? Is my current direction aligned with the objective?
- If yes, reset the timer and continue. If not, correct course or stop.
- **Intent invalidation:** A timer encodes the intent that was valid when it was set. If the user has intervened since the timer was set — provided new direction, spoken to a worker directly, changed context, or expressed disagreement — the timer's encoded intent is stale. When a timer fires, check for user intervention first. If intervention occurred, discard the timer's original instructions and re-evaluate from the current state. Never execute stale instructions from a timer that was set before a context change.
- **Departing is a heartbeat outcome, never an abrupt act.** A heartbeat carries intent, and the firing resolves to one of continue, correct course, or stop. For a session that holds its own lifecycle — one that dispatched the work, or a singleton answerable only to itself, never a dispatched worker — whose work is complete and that must end itself, stopping _is_ departing — so an agent never ends itself as the final act of a turn. It finishes its work, leaves its farewell, and arms a short timer carrying the intent to depart, then lets the turn close on its own. When that timer fires, the intent-invalidation check comes first: if anything has arrived in the meantime — a fresh message, new work, a surfaced blocker, a human stepping back in — the depart intent is stale, and the agent stays and tends to what came. Only when the moment is still clear does it carry the departure through — and the depart action is `telec sessions end self`, the sanctioned self-end invocation, never a raw session id. Deferring this way is what gives the agent its last look before it lets go — the look an abrupt end never takes.
- **Task-scoped, not session-scoped.** The heartbeat chain stops when the current task's deliverables are complete. The agent remains available — no heartbeat. A new task starts a new heartbeat. Role-specific completion conditions (child session cleanup, integration finalization) are defined in the role's procedure, not here.
- **Stop conditions.** The heartbeat chain ends — do not reset the timer — when any of these hold:
  - **Deliverables complete.** The task output is committed, delivered, or reported. No further work remains.
  - **Blocked on human decision.** A question was asked or a gate requires human input. The human's next message starts a new cycle if it initiates new work.
  - **No active task.** The session is idle between tasks. The next user message starts a new cycle.
  - **Stale intent with no successor.** The timer's encoded intent is invalidated by user intervention and no new task has been given. The chain stops — do not re-evaluate into the void.
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

## See Also

- ~/.teleclaude/docs/general/principle/session-lifecycle.md — the departure disposition the depart-intent heartbeat enacts.

> **Note to self:** The heartbeat is just a pinch. Am I on track? Yes — continue. No — adjust. That's it. Don't overthink it.
