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
<!-- planned:reminder-noop-firing-contract -->
- A due reminder whose intent is already satisfied warrants no authored output.
  The agent takes no tool action and authors no message — no summary, no
  status, no confirmation of the reminder — and ends the turn with exactly
  `NOOP` and no other text. The sentinel exists for runtimes that cannot close
  a turn silently; a runtime that can end its turn with no output does so
  instead. The platform never delivers a bare `NOOP` turn to peers, projected
  surfaces, or notifications; the turn remains transcript truth.
<!-- /planned:reminder-noop-firing-contract -->


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

- Every material reminder transition is durable source truth: armed, replaced,
  cancelled, and the firing reminder itself enter the owning session transcript
  in source order as typed reminder entries. A firing is the reminder acting
  now, not a separate `due` status message.
- Agent-facing reminder text uses the compact platform-owned bracketed envelope
  defined by the reminder-service contract. Opening and closing lines are
  structural and agents never imitate them.
- Projection consumes the typed reminder entry and its structured payload. A UI
  adapter renders the eligible entry as Markdown key-value fields without the
  transcript envelope. Exact identifiers use inline code; prose intent does not.
- UI adapters localize structured instants from TeleClaude's configured person
  location and time zone, and render an unambiguous human-readable local time
  including its zone. They never infer locale from the host or transport.
  Canonical UTC/RFC3339 values remain in structured state and agent-facing
  transcript syntax, not in human-facing UI copy.
- A false event-activation predicate is silent because no transition occurred.
  It creates no transcript entry, envelope, derived event, transport write, or
  session input.
- Reminder entries use existing transcript projection, routing, ordering, and
  priority semantics. They create no reminder-specific UI or audit lane.

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
- **Parameters:** `goal`.
- **Activation anchor:** immediately when sustained work starts.
- **Duration:** five minutes.
- **Recurrence:** recurring; the service advances the cadence without an agent
  re-arming after every occurrence.
- **Arm condition:** set before the first substantive action of sustained work.
- **Intent:** `Reassess whether the current work remains aligned with <goal>. If aligned, continue; otherwise correct course or stop.`
- **Firing behavior:** check for later input first, then reassess only the active
  goal. It is not a debrief or housekeeping trigger.
- **Cancellation:** cancel when deliverables are complete, work is blocked on a
  human decision, no active task remains, the goal is abandoned, or stale intent
  has no successor.
- **Invocation:** `telec reminders set goal-drive --goal <goal>`.

#### Reminder: halt-to-respond

- **Owner:** Agent Reminder policy.
- **Parameters:** none; caller and event correlation derive from the
  authenticated session.
- **Activation anchor:** the next owning-session `agent_stop` after arming.
- **Duration:** none; the qualifying event makes the reminder due directly.
- **Recurrence:** one-shot.
- **Arm condition:** after preparing a response to an identity-bearing
  non-human conversational turn, arm as the final tool action; then emit only
  that prepared response and yield. Control notifications, reminders,
  checkpoints, silent directives, and turns requiring no response are excluded.
- **Intent:** `Resume the work interrupted to answer the non-human input, unless intervening input made that work stale.`
<!-- planned-change:reminder-noop-firing-contract -->
- **Firing behavior:** resume only when prior work remains interrupted. If work
  already resumed or no prior work remains, the intent is satisfied and no
  further action follows.
<!-- change:reminder-noop-firing-contract -->
- **Firing behavior:** resume only when prior work remains interrupted. If work
  already resumed or no prior work remains, the intent is satisfied and the
  satisfied-firing no-op contract applies: no tool action, no authored message,
  the turn ends with exactly `NOOP` and no other text.
<!-- /planned-change:reminder-noop-firing-contract -->
- **Cancellation:** cancel if the response is not emitted, the interrupted work
  is completed or abandoned before the due time, or later input invalidates it.
- **Invocation:** `telec reminders set halt-to-respond`.

## Rationale

Agent runtimes do not reliably preserve local timers across turn closure. A
platform-owned reminder makes future intent durable and inspectable while
keeping the semantic decision with the agent. Intent-revealing slugs let agents
and humans understand why a reminder exists, multiple reminders preserve
independent subgoals, and cancellation prevents completed work from returning
as zombie activity.

The two baseline profiles solve cross-cutting failures. Goal drive supplies a
low-noise alignment rhythm during sustained work. Halt to respond makes a peer
response end in a deterministic cooperative yield without asking transport to
infer semantic completion from prose.

## Scope

- Applies to every agent session using the platform reminder service.
- Local prescribed profiles remain governed by their owning job or procedure.
- Infrastructure liveness heartbeats, leases, peer refresh, cache health, and
  operation heartbeats are outside this policy.

## Enforcement

- Sustained work without `goal-drive` armed before substantive action is a
  process violation.
- A response-bearing non-human conversational turn that does not follow the
  `halt-to-respond` arm-response-yield sequence is a process violation.
- Acting on reminder intent without first checking later input is a process
  violation.
- Reimplementing reminders with detached processes, blocking waits, transport
  messages, or agent-runtime-specific timer folklore is a process violation.

## Exceptions

- Short interactive work that completes in a few tool calls does not arm
  `goal-drive`.
- A non-human turn that requires no authored response does not arm
  `halt-to-respond`.
