---
description: Durable agent reminders for goal alignment, cooperative peer-response
  yield, stale-intent invalidation, cancellation, and locally owned prescribed profiles.
---

# Agent Reminder — Policy

## Rules

### Reminders carry intent, not authority

- A reminder is durable intent left by a session for its future self. It is not
  a liveness heartbeat, human authorization, proof of delivery, or proof that an
  agent processed input.
- Before acting on a due reminder, read everything that arrived after its armed
  time. When later input changes, supersedes, or invalidates the encoded intent,
  discard that intent and re-evaluate from current state.
- A reminder never substitutes stale stored data for fresh grounding. An agent
  reminded to perform an important scheduled action re-establishes relevance,
  source truth, and any authorization the action requires at execution time.
- An agent never occupies a terminal or tool runtime merely to wait for time,
  human input, a notification, or external completion. Blocking `sleep`, wait
  commands, polling loops, and long-lived tool cells make the session
  unavailable to incoming conversation. Arm the applicable reminder when
  future-self intent is needed, then yield with no waiting process left behind;
  the reminder or incoming event re-enters the session through its normal input
  path.
- A due reminder whose intent is already satisfied warrants no authored output
  beyond the sentinel. The agent takes no tool action and authors no message —
  no summary, no status, no confirmation of the reminder — and ends the turn
  with exactly `NOOP` and no other text, on every runtime. The platform never
  delivers a bare `NOOP` turn to peers, projected surfaces, or notifications.
- A prescribed profile may declare auto-cancel. A `NOOP`-answered firing of a
  declaring profile — a turn with no tool actions and no authored content
  beyond the sentinel — cancels that reminder. Every firing of a declaring
  profile states this consequence in its envelope.

### Reminder identity and lifecycle

- A reminder's identity is `(authenticated session, intent-revealing slug)`.
  Distinct intents use distinct slugs and may coexist without a numeric cap.
- Setting the same slug again in one session atomically replaces the live
  reminder. The earlier schedule cannot fire after replacement succeeds.
- Every reminder is cancelable. Cancel one slug when its subgoal is satisfied;
  cancel all reminders only when every outstanding reminder intent for the
  session is obsolete. Cancellation is session-scoped and idempotent.
- Relative reminders may be one-shot or recurring. Absolute-time reminders are
  one-shot. Recurrence is explicit, never inferred merely because an intent
  sounds ongoing.
- Prescribed reminder slugs are reserved once their definitions are delivered.
  Arbitrary slugs remain available when they do not collide with a prescribed
  definition. Historical arbitrary reminders do not reserve a slug forever.

### Reminder transcript and presentation

- Every material reminder transition is recorded in source order in the
  service's typed reminder records: armed, replaced, cancelled, and the firing
  itself. A firing is the reminder acting now, not a separate `due` status
  message.
- Agent-facing reminder text uses the compact platform-owned bracketed envelope
  defined by the reminder-service contract. Opening and closing lines are
  structural and agents never imitate them.
- Armed, replaced, and cancelled transitions are recorded in the service's
  durable reminder records. Only a firing is delivered to the agent. A
  reminder command returns a minimal acknowledgement.
- A false event-activation predicate is silent because no transition occurred.
  It creates no transcript entry, envelope, derived event, transport write, or
  session input.

### Prescribed reminder declarations

A prescribed reminder is documented beside the policy, procedure, command, or
job that owns its intent under `#### Reminder: <slug>`. The declaration states:

- owner;
- caller parameters;
- activation anchor;
- duration or absolute schedule;
- one-shot or recurring behavior;
- exact arm condition;
- exact agent-authored intent;
- firing behavior;
- cancellation or stop condition; and
- minimal formatter invocation.

The owning surface states its cadence. The general reminder service never
repeats or overrides a caller's process interval. A delivered prescribed
definition registers its slug with the service so an arbitrary reminder cannot
squat it; registration does not move the declaration away from its owner.

A time-recurring profile may declare adaptive cadence. Its declaration names
the initial interval, backoff rule, maximum interval, activity that resets the
interval, and terminal cancellation condition. Re-setting the same prescribed
slug atomically replaces its recurring schedule, so a continuing watcher never
passes through an unarmed gap while becoming quieter or more responsive.
Profiles without an adaptive-cadence declaration do not acquire one by caller
choice. Event-triggered profiles have no cadence to override.

#### Reminder: goal-drive

- **Owner:** Agent Reminder policy.
- **Parameters:** free-form `intent` (optional; a default reassessment intent is used when omitted).
- **Activation anchor:** immediately when sustained work starts.
- **Duration:** five minutes of session inactivity. The schedule slides: each
  occurrence anchors to the session's last activity, so the reminder never
  fires while the agent is actively working and first fires after the interval
  passes with no activity and the goal still open.
- **Recurrence:** recurring; the service advances the sliding cadence without
  an agent re-arming after every occurrence.
- **Arm condition:** set before the first substantive autonomous action of sustained work. Do not arm it after a state-machine procedure delegates execution and prescribes its own watcher; that watcher owns the waiting cadence. A terminal or human-gated procedure state makes `goal-drive` inapplicable and requires immediate cancellation.
- **Intent:** defaults to `Reassess whether the current work remains aligned with the goal. If aligned, continue; otherwise correct course or stop.`; `--intent` overrides with agent-authored text.
- **Firing behavior:** check for later input first, then reassess only the active
  goal. It is not a debrief or housekeeping trigger. Mid-work drift discipline
  is carried by agent instructions, not by this profile's firings.
- **Cancellation:** cancel when deliverables are complete, work is blocked on a
  human decision, no active task remains, the goal is abandoned, or stale intent
  has no successor. The profile declares auto-cancel: a `NOOP`-answered firing
  cancels the reminder.
- **Invocation:** `telec reminders set goal-drive` (uses the default intent) or `telec reminders set goal-drive --intent <intent>`.

## Rationale

Agent runtimes do not reliably preserve local timers across turn closure. A
platform-owned reminder makes future intent durable and inspectable while
keeping the semantic decision with the agent. Intent-revealing slugs let agents
and humans understand why a reminder exists, multiple reminders preserve
independent subgoals, and cancellation prevents completed work from returning
as zombie activity.

Goal drive supplies a low-noise alignment rhythm during sustained work.

Yielding instead of terminal-waiting keeps the session receptive to the human
and lets the platform own re-entry. A terminal process is an execution surface,
not a scheduler or conversational parking mechanism.

## Scope

- Applies to every agent session using the platform reminder service.
- Local prescribed profiles remain governed by their owning job or procedure.
- Infrastructure liveness heartbeats, leases, peer refresh, cache health, and
  operation heartbeats are outside this policy.

## Enforcement

- Sustained work without `goal-drive` armed before substantive action is a
  process violation.
- Acting on reminder intent without first checking later input is a process
  violation.
- Using a blocking terminal command, polling loop, or long-lived tool cell only
  to wait for time, input, notification, or external completion is a process
  violation.
- Reimplementing reminders with detached processes, blocking waits, transport
  messages, or agent-runtime-specific timer folklore is a process violation.

## Exceptions

- Short interactive work that completes in a few tool calls does not arm
  `goal-drive`.
