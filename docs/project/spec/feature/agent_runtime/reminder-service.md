---
description: Durable self-session reminders with intent-revealing slugs, relative
  and absolute schedules, optional recurrence, prescribed profiles, and auditable
  lifecycle envelopes.
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
The service owns reminder lifecycle and hands each firing to the platform's
control-delivery surface; delivery mechanics, receipts, and wake behavior
belong to that surface, not to this service.

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

- `telec reminders set goal-drive --intent <intent>`

Other prescribed profiles are registered beside the job or procedure that owns
their intent. Their delivered slugs are reserved against arbitrary use without
centralizing their definitions.

### Typed entry and recipient presentation

<!-- planned-change:quiet-reminders -->
Every material transition produces one typed reminder source entry in the
owning session transcript: `armed`, `replaced`, `cancelled`, or the firing
reminder itself. The structured payload carries the slug, intent, recurrence,
schedule or event anchor, armed instant, transition instant, and next instant
when one exists. A false event predicate produces no entry because no
transition occurred.
<!-- change:quiet-reminders -->
Every material transition produces one typed record in the service's durable
reminder records: `armed`, `replaced`, `cancelled`, or the firing itself. The
structured payload carries the slug, intent, recurrence, schedule or event
anchor, armed instant, transition instant, and next instant when one exists.
A false event predicate produces no record because no transition occurred.
<!-- /planned-change:quiet-reminders -->

Reminder presentation renders from the typed reminder record rather than from
stored framing. Human-readable synchronous agent surfaces use the shared
bracket codec, while a firing handed to control delivery is rendered by the
shared XML codec at the runtime hook boundary. Both codecs carry the same slug,
intent, recurrence, schedule or event anchor, armed instant, transition instant,
and next instant. A firing has no separate `due` status. Agents never author or
imitate either codec's structural framing, and no consumer parses presentation
to recover reminder identity or lifecycle state.

<!-- planned-change:quiet-reminders -->
Projection consumes the typed entry and structured payload through the existing
category, ordering, and routing contracts. Eligible UI adapters omit the
transcript envelope and render Markdown key-value fields, for example:

```markdown
**Reminder:** `goal-drive`
**Type:** Recurring
**Triggered:** `17 Aug 2026, 12:30 CEST`
**Next:** `17 Aug 2026, 12:35 CEST`
**Intent:** Reassess whether the current work remains aligned with the stated goal
```

`armed`, `replaced`, and `cancelled` presentations add a **Status** field. A
firing presentation has no `Due` status. Slugs, typed event names, and exact
times use inline code; prose intent does not. The adapter derives human-readable
local time from TeleClaude's configured person location and time zone, never
from host locale or transport inference, and never exposes the canonical
UTC/RFC3339 storage form as UI copy.
<!-- change:quiet-reminders -->
Reminder records are readable through the reminder inspection surfaces and the
session listing's next-reminder summary. The reminder service does not
prescribe, prefix, or format subsequent agent-authored output.
<!-- /planned-change:quiet-reminders -->

<!-- planned:reminder-history-tolerant-reader -->
### Historical entry interpretation

The prescribed-profile vocabulary is closed for new commands and registry
lookup, but profile identity stored in reminder records is open historical data.
Readers carry an unknown or retired value as a string and use generic reminder
presentation. History renders the entry from its stored prose and metadata;
current registry membership never decides whether the historical record is
readable.

Cursor-driven projection distinguishes permanent record-local failure from
transient downstream delivery failure. A permanent failure is recorded and the
cursor advances past it. A transient delivery failure retains the row for retry.
Neither outcome mutates the append-only reminder record.
<!-- /planned:reminder-history-tolerant-reader -->

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

#### UC-RMS7 (r2): A firing one-shot reminder is handed to control delivery once

```gherkin
Given a live one-shot reminder reaches its scheduled time
When the reminder fires
Then one reminder entry is handed to the platform's control-delivery surface
And it carries the slug, armed time, schedule, and agent-authored intent
And it instructs the receiver to check for intervening input after the armed time before acting
And the handoff consumes the reminder
And delivery mechanics remain owned by the control-delivery surface
```

#### UC-RMS8 (r2): A recurring reminder advances without agent re-arming

```gherkin
Given a live recurring reminder reaches its scheduled time
When its firing reminder entry is accepted by the control-delivery surface
Then the reminder stays live and advances by its configured cadence without an agent re-arming it
And after downtime at most one overdue occurrence is handed off
And the next occurrence is scheduled from that recovered firing rather than replaying missed intervals
```

#### UC-RMS9 (r2): Restart recovery preserves reminder intent without catch-up noise

```gherkin
Given live reminders exist when the daemon stops
When the daemon starts again
Then future reminders retain their schedules
And a firing occurrence not yet accepted by the control-delivery surface is handed off promptly
And an accepted occurrence is not handed off again
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

#### UC-RMS12 (r2): Goal drive is a sliding inactivity reminder

```gherkin
Given an agent starts sustained work toward a goal
When it arms the goal-drive profile
Then one recurring reminder under the goal-drive slug is scheduled on a sliding five-minute inactivity interval
And the reminder does not fire while the session shows activity within the interval
And it first fires after the interval passes with no session activity and the goal still open
And its intent defaults to reassessing alignment with the goal, correcting course or stopping if not, unless overridden by a free-form --intent
And the profile is cancelled when the goal is complete, blocked on a human, abandoned, inactive, or invalidated without a successor
```


<!-- planned-change:quiet-reminders -->
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
<!-- change:quiet-reminders -->
#### UC-RMS14 (r2): Reminder lifecycle is auditable through service records

```gherkin
Given a reminder is armed, replaced, cancelled, or fires
When the material transition commits
Then the service records one typed reminder record in source order
And a firing is delivered into the agent work loop
```
<!-- /planned-change:quiet-reminders -->

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

#### UC-RMS17 (r2): Reminder firings ride the shared control-delivery order

```gherkin
Given reminder firings and other control payloads await delivery to one session
When the platform delivers them
Then they arrive in their enqueue order through the shared control-delivery surface
And the reminder service introduces no reminder-specific priority or queue bypass of its own
```

#### UC-RMS18 (r2): Satisfied reminder intent ends with the explicit sentinel on every runtime

```gherkin
Given an agent receives a firing reminder
And later input or current state shows that the reminder intent is already satisfied
When the agent evaluates the reminder
Then it takes no reminder-driven tool action
And it authors no summary, status, or confirmation
And it ends the turn with exactly `NOOP` and no other text on every runtime
And silent turn closure is not used to answer a reminder firing
```

<!-- planned:session-departure-on-agent-stop -->
#### UC-RMS19: A self-owning agent departs only after its final output settles

```gherkin
Given a self-owning agent has completed its durable handoff and child cleanup
When it arms the session-departure profile as its final tool action
And emits only its brief farewell before yielding
Then the completed turn records that final output before the reminder fires
And the reminder re-enters the same session exactly once without a caller-supplied delay
And the agent checks later input before ending itself
And it ends itself only while the departure remains valid
```
<!-- /planned:session-departure-on-agent-stop -->

#### UC-RMS20: An auto-cancel firing states its consequence in the envelope

```gherkin
Given a recurring reminder belongs to a profile that declares auto-cancel
When one of its firings is delivered
Then the delivered text states that answering with `NOOP` cancels this reminder
```

#### UC-RMS21: A NOOP-answered auto-cancel firing ends the reminder

```gherkin
Given a firing of an auto-cancel profile is answered by a turn with no tool actions and no authored content beyond `NOOP`
When the platform observes that answer
Then the service cancels the reminder
And records the cancellation with its auto-cancel reason in its durable reminder records
```

<!-- planned:quiet-reminders -->
#### UC-RMS22: Only firings reach the agent

```gherkin
Given a reminder is armed, replaced, or cancelled by any path including auto-cancel
When the transition commits
Then the service records the transition in its durable reminder records
And a reminder command's response is a minimal acknowledgement
And only a firing is delivered into the agent's context
And the reminder service does not prescribe, prefix, or format subsequent agent-authored output
```
<!-- /planned:quiet-reminders -->


<!-- planned:reminder-history-tolerant-reader -->
#### UC-RMS23: Retired reminder vocabulary cannot poison a delivery window

```gherkin
Given an agent session's cursor-to-now reminder window contains an immutable entry written with a profile name the current build does not prescribe
And a later reminder entry is waiting in the same window
When the platform projects reminder history for that session
Then the historical profile name is treated as open data and rendered through generic reminder presentation
And the cursor advances through the historical entry so the later entry remains reachable
And no internal projection failure is reported to a human as a polling error
And the immutable historical entry remains unchanged as audit truth
```
<!-- /planned:reminder-history-tolerant-reader -->

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
