---
description: Durable self-session reminders with intent-revealing slugs, relative and absolute schedules, optional recurrence, prescribed profiles, and auditable lifecycle envelopes.
delivered_by:
  - platform-reminder-service
---

# Reminder Service — Spec

## What it is

The reminder service lets an agent session leave durable, inspectable intent for
its future self. A reminder has a human-readable slug, an agent-authored intent,
and either a time schedule or a prescribed event anchor. Several reminders may
coexist because distinct intents remain distinct work. Reusing the same slug in
the same session replaces that intent atomically.

Reminders are not infrastructure heartbeats. They do not report node liveness,
renew a lease, keep Redis peers alive, or prove that an agent processed input.
The service owns reminder lifecycle and submission to the existing session-input
surface only; it adds no transport priority, delivery acknowledgement, runtime
wake detector, or message-delivery success mechanism.

## Canonical fields

### Public surface

- `telec reminders set <slug> --after <duration> --intent <text> [--repeat]`
- `telec reminders set <slug> --at <RFC3339 timestamp> --intent <text>`
- `telec reminders list`
- `telec reminders cancel <slug>`
- `telec reminders cancel --all`

`--after` and `--at` are mutually exclusive. `--repeat` uses the relative
duration as its cadence; absolute-time reminders are one-shot. All operations
are scoped to the authenticated calling session. A slug is the public reminder
identity, not a display label layered over an opaque id.

Prescribed reminders use the same registry while owning their minimal formatter
surface. The service-baked profiles are:

- `telec reminders set goal-drive --goal <goal>`
- `telec reminders set halt-to-respond`

Other prescribed profiles are registered beside the job or procedure that owns
their intent. Their delivered slugs are reserved against arbitrary use without
centralizing their definitions.

### Typed entry and recipient presentation

Every material transition produces one typed reminder source entry in the
owning session transcript: `armed`, `replaced`, `cancelled`, or the firing
reminder itself. The structured payload carries the slug, intent, recurrence,
schedule or event anchor, armed instant, transition instant, and next instant
when one exists. A false event predicate produces no entry because no
transition occurred.

Agent-facing transcript text is compact plain text inside a platform-authored
envelope. A firing reminder has no separate `due` status; the delivered entry
is the reminder acting now:

```text
[Reminder goal-drive recurring at 2026-08-17T10:30:00Z next 2026-08-17T10:35:00Z]
Reassess whether the current work remains aligned with ...
[/Reminder goal-drive]
```

Lifecycle entries add `armed`, `replaced`, or `cancelled` to the opening line.
An event-triggered firing names its typed anchor, for example
`[Reminder halt-to-respond one-shot on agent_stop]`. Opening kind and closing
slug are transcript structure; agents never author or imitate them, and no
consumer parses them to recover reminder identity or state.

Projection consumes the typed entry and structured payload through the existing
category, ordering, and routing contracts. Eligible UI adapters omit the
transcript envelope and render Markdown key-value fields, for example:

```markdown
**Reminder:** `goal-drive`
**Type:** Recurring
**Triggered:** `17 Aug 2026, 12:30 CEST`
**Next:** `17 Aug 2026, 12:35 CEST`
**Intent:** Reassess whether the current work remains aligned with ...
```

`armed`, `replaced`, and `cancelled` presentations add a **Status** field. A
firing presentation has no `Due` status. Slugs, typed event names, and exact
times use inline code; prose intent does not. The adapter derives human-readable
local time from TeleClaude's configured person location and time zone, never
from host locale or transport inference, and never exposes the canonical
UTC/RFC3339 storage form as UI copy.

### Use cases

#### UC-RMS1: A session schedules a named reminder for itself

```gherkin
Given an agent session has a valid intent-revealing slug and intent
When it schedules the reminder after a duration or at an absolute timestamp
Then the reminder is durably owned by that authenticated session
And its public identity is the slug
And no option can target another session
```

#### UC-RMS2: Distinct intents coexist without a session cap

```gherkin
Given a session has one or more live reminders under distinct slugs
When it schedules another distinct slug
Then every reminder remains live with its own intent and schedule
And no arbitrary numeric cap rejects the additional reminder
```

#### UC-RMS3: Reusing a slug atomically replaces that reminder

```gherkin
Given a session owns a live reminder under a slug
When the same session schedules that slug again
Then intent, schedule, recurrence, event anchor, and armed time are replaced atomically
And exactly one live reminder remains under that slug
And the superseded schedule cannot fire after replacement succeeds
```

#### UC-RMS4: Slug ownership is session-local

```gherkin
Given two sessions use the same non-prescribed reminder slug
When each schedules it for itself
Then each session owns an independent reminder
And replacement or cancellation in one session does not affect the other
```

#### UC-RMS5: Delivered prescribed slugs cannot be squatted

```gherkin
Given a prescribed reminder profile is delivered under a registered slug
When a caller tries to use that slug through the arbitrary-intent form
Then no arbitrary reminder is created
And the response identifies the prescribed profile surface
And a non-prescribed valid slug remains available for arbitrary self-reminders
```

#### UC-RMS6: A session inspects and cancels its own reminders

```gherkin
Given a session owns live time-scheduled and event-anchored reminders
When it lists reminders
Then it sees only its own reminders with slug, intent, schedule, recurrence, and next firing time when one exists
When it cancels one slug or atomically cancels all
Then the selected live reminders and their pending event anchors are removed idempotently
And already accepted session input is not recalled
```

#### UC-RMS7: A firing one-shot reminder enters the existing session-input path once

```gherkin
Given a live one-shot reminder reaches its scheduled time
When the reminder fires
Then one reminder entry is submitted through the existing session-input surface
And it carries the slug, armed time, schedule, and agent-authored intent
And it instructs the receiver to check for intervening input after the armed time before acting
And acceptance consumes the reminder
And the reminder service adds no runtime-specific delivery path or processing confirmation
```

#### UC-RMS8: A recurring reminder advances without agent re-arming

```gherkin
Given a live recurring reminder reaches its scheduled time
When its firing reminder entry is accepted by the existing session-input surface
Then the reminder stays live and advances by its configured cadence without an agent re-arming it
And after downtime at most one overdue occurrence is submitted
And the next occurrence is scheduled from that recovered firing rather than replaying missed intervals
```

#### UC-RMS9: Restart recovery preserves reminder intent without catch-up noise

```gherkin
Given live reminders exist when the daemon stops
When the daemon starts again
Then future reminders retain their schedules
And a firing occurrence not yet accepted by the existing session-input surface is submitted promptly
And an accepted occurrence is not submitted again
And recurring reminders produce no catch-up burst
```

#### UC-RMS10: Ended sessions retain no live reminders

```gherkin
Given a session owns live reminders
When that session ends through any lifecycle path
Then all of its reminders and pending event anchors are removed
And no later reminder fires into the ended session
And the removal is visible in structured operational evidence
```

#### UC-RMS11: Event-triggered firing is typed, first-match, and silent on false

```gherkin
Given a prescribed reminder waits on a typed agent event
When an event does not satisfy its code-owned activation predicate
Then the reminder remains pending
And no transcript entry, reminder envelope, transport write, derived event, or session input is produced
When the first event satisfies the predicate
Then that event atomically consumes the pending anchor and fires the reminder directly
And later matching events do not produce another occurrence
```

#### UC-RMS12: Goal drive is a five-minute recurring prescribed reminder

```gherkin
Given an agent starts sustained work toward a goal
When it arms the goal-drive profile with that goal
Then one recurring reminder under the goal-drive slug is scheduled every five minutes
And its intent tells the agent to reassess alignment with the goal, continue when aligned, and otherwise correct course or stop
And the profile is cancelled when the goal is complete, blocked on a human, abandoned, inactive, or invalidated without a successor
```

#### UC-RMS13: Halt to respond restores work after a mandatory peer-response yield

```gherkin
Given an identity-bearing non-human conversational turn requires a response
When the agent has prepared that response
Then its final tool action arms the halt-to-respond profile
And it emits only the prepared response and yields
And the next owning-session agent-stop fires the reminder directly
And the intent tells the agent to resume the interrupted work unless intervening input made it stale
And control notifications, reminder envelopes, checkpoints, and turns requiring no response do not trigger this profile
```

#### UC-RMS14: Reminder lifecycle remains transcript-auditable through normal projection

```gherkin
Given a reminder is armed, replaced, cancelled, or fires
When the material transition commits
Then one typed reminder entry enters owning-session transcript source truth in source order
And normal projection applies the reminder category's recipient and context visibility
And an eligible UI adapter renders the structured entry without transcript brackets
And the firing reminder enters the agent work loop while lifecycle records remain transcript evidence
And no separate reminder audit delivery lane or duplicate UI message is created
```

#### UC-RMS15: Preparation and execution reminders remain independent

```gherkin
Given a personal assistant must prepare before an important scheduled action and reground again when the action is due
When it schedules those purposes under two distinct arbitrary slugs
Then both reminders remain independently inspectable and cancellable
And the later reminder prompts fresh grounding of relevance, data, and authorization
And neither reminder is itself authorization to perform the action
```

#### UC-RMS16: The next scheduled reminder is externally inspectable

```gherkin
Given a session owns one or more reminders with concrete scheduled times
When an operator reads the session listing
Then the listing identifies the next scheduled reminder by slug and timestamp
And a session with only event-anchored reminders still exposes those reminders through its reminder registry
And a session with no live reminders exposes no next reminder
```

#### UC-RMS17: Reminder traffic keeps existing ordering and priority semantics

```gherkin
Given reminder and conversational entries are submitted around the same time
When the platform routes them
Then reminder entries use the existing ordered session and UI delivery contracts
And no reminder-specific priority, queue bypass, outbox, acknowledgement, retry class, or delivery-success mechanism is introduced
```

## Known caveats

- A reminder records intent; it is never evidence of current human authorization.
- Acceptance by the existing session-input surface does not establish that an
  idle runtime began processing. That delivery concern remains outside this
  feature.
- Absolute-time recurrence is not part of this surface. Calendar recurrence
  requires an explicit recurrence expression rather than overloading `--at`.
- Arbitrary intent remains free text. The platform validates the command shape
  and prescribed slug boundary, never the quality or meaning of intent.
- Prescribed activation predicates are code-owned extension points. Callers do
  not upload executable predicates or lambdas.
