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
- A due reminder whose intent is already satisfied warrants no authored output.
  The agent takes no tool action and authors no message — no summary, no
  status, no confirmation of the reminder — and ends the turn with exactly
  `NOOP` and no other text. The sentinel exists for runtimes that cannot close
  a turn silently; a runtime that can end its turn with no output does so
  instead. The platform never delivers a bare `NOOP` turn to peers, projected
  surfaces, or notifications; the turn remains transcript truth.

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
<!-- planned-change:quiet-reminders -->
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
<!-- change:quiet-reminders -->
- Reminder lifecycle is agent-facing only. Firings are delivered by the
  platform into the owning session's context; no human-facing surface renders
  reminder entries, and no reminder-specific UI or audit lane exists. Typed
  transcript entries remain the durable, inspectable record of every material
  transition — armed, replaced, cancelled, fired.
- When a delivered firing triggers action, the agent's next authored output
  opens with one line of provenance naming the reminder slug, its recurrence,
  and the moment it fired — the firing time carried in the entry, not the
  delivery time. The line is a compact self-report, never a verbatim echo of
  the envelope. A satisfied firing authors no output at all under the
  satisfied-firing contract above.
- A false event-activation predicate is silent because no transition occurred.
  It creates no transcript entry, envelope, derived event, transport write, or
  session input.
<!-- /planned-change:quiet-reminders -->

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
<!-- planned-change:reminder-timer-semantics -->
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
<!-- change:reminder-timer-semantics -->
- **Duration:** five minutes of session inactivity. The schedule slides: each
  occurrence anchors to the session's last activity, so the reminder never
  fires while the agent is actively working and first fires after the interval
  passes with no activity and the goal still open.
- **Recurrence:** recurring; the service advances the sliding cadence without
  an agent re-arming after every occurrence.
- **Arm condition:** set before the first substantive action of sustained work.
- **Intent:** `Reassess whether the current work remains aligned with <goal>. If aligned, continue; otherwise correct course or stop.`
- **Firing behavior:** check for later input first, then reassess only the active
  goal. It is not a debrief or housekeeping trigger. Mid-work drift discipline
  is carried by agent instructions, not by this profile's firings.
- **Cancellation:** cancel when deliverables are complete, work is blocked on a
  human decision, no active task remains, the goal is abandoned, or stale intent
  has no successor.
- **Idle-expiry:** the service cancels the reminder itself after consecutive
  occurrences during which the session shows no activity other than
  reminder-triggered turns — a session kept breathing only by this reminder has
  no active work by definition. The cancellation is recorded as a typed entry
  naming the idle-expiry reason.
<!-- /planned-change:reminder-timer-semantics -->
- **Invocation:** `telec reminders set goal-drive --goal <goal>`.

#### Reminder: halt-to-respond

- **Owner:** Agent Reminder policy.
- **Parameters:** none; caller and event correlation derive from the
  authenticated session.
- **Activation anchor:** the next owning-session `agent_stop` after arming.
- **Duration:** none; the qualifying event makes the reminder due directly.
- **Recurrence:** one-shot.
<!-- planned-change:quiet-reminders -->
- **Arm condition:** after preparing a response to an identity-bearing
  non-human conversational turn, arm as the final tool action; then emit only
  that prepared response and yield. Control notifications, reminders,
  checkpoints, silent directives, and turns requiring no response are excluded.
<!-- change:quiet-reminders -->
- **Arm condition:** optional, at the agent's judgment. Arm only when the
  response interrupts in-progress work whose resumption needs a guarantee:
  after preparing the response, arm as the final tool action, then emit only
  that prepared response and yield. An agent with no interrupted work responds
  and yields without arming — an idle session needs no resumption hook, and a
  firing whose only possible outcome is the satisfied-firing no-op is noise.
<!-- /planned-change:quiet-reminders -->
- **Intent:** `Resume the work interrupted to answer the non-human input, unless intervening input made that work stale.`
- **Firing behavior:** resume only when prior work remains interrupted. If work
  already resumed or no prior work remains, the intent is satisfied and the
  satisfied-firing no-op contract applies: no tool action, no authored message,
  the turn ends with exactly `NOOP` and no other text.
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
<!-- planned-change:quiet-reminders -->
- A response-bearing non-human conversational turn that does not follow the
  `halt-to-respond` arm-response-yield sequence is a process violation.
<!-- change:quiet-reminders -->
- Arming `halt-to-respond` while holding no interrupted work is a process
  violation; a response that interrupts in-progress work and yields without
  either arming `halt-to-respond` or resuming that work is one as well.
<!-- /planned-change:quiet-reminders -->
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
- A non-human turn that requires no authored response does not arm
  `halt-to-respond`.
