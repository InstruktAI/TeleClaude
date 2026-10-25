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

A prescribed profile that its owner retires keeps its slug reserved. Setting a
retired slug is refused with the successor that replaced the profile, so a caller
still following the retired instruction learns how to continue without it rather
than meeting a generic shape refusal. `integrator-queue-watch` is retired: the
integrator is woken by its procedure's event subscriptions, and the caller
continues with the procedure's next step.

Time-scheduled reminders have at most one live occurrence. A one-shot is
consumed when its firing is accepted by control delivery. A recurring schedule
advances after an accepted firing; after downtime, at most one overdue
occurrence is delivered and the next time is calculated from that firing.
Restart preserves future schedules and resumes only an occurrence not yet
accepted. Ending the owning session removes its reminders and pending event
anchors.

An event-anchored reminder remains pending until its first matching typed event.
A false predicate creates no transition record, while the first match consumes
the anchor and fires once. An `agent_stop` anchor occurs after the completed
turn's final output has been recorded. A prescribed profile may prohibit cancellation; if a
cancel-one or cancel-all request selects a protected reminder, the request is
rejected before any selected reminder is removed.

Only a firing enters the agent's context; other transitions create typed
records and their command receives a synchronous acknowledgement. Each firing
states its occurrence count since the current arming and, for a scheduled
reminder, the deadline that fired. At most one undelivered firing is retained
per slug, so a newer occurrence supersedes an older one that has not reached
the session.

### Typed entry and recipient presentation

Every material transition produces one typed record in the service's durable
reminder records: `armed`, `replaced`, `cancelled`, or the firing itself. The
structured payload carries the slug, intent, recurrence, schedule or event
anchor, armed instant, transition instant, and next instant when one exists.
A false event predicate produces no record because no transition occurred.

Reminder presentation renders from the typed reminder record rather than from
stored framing. Human-readable synchronous agent surfaces use the shared
bracket codec, while a firing handed to control delivery is rendered by the
shared XML codec at the runtime hook boundary. Both codecs carry the same slug,
intent, recurrence, schedule or event anchor, armed instant, transition instant,
and next instant. A firing has no separate `due` status. Agents never author or
imitate either codec's structural framing, and no consumer parses presentation
to recover reminder identity or lifecycle state.

Reminder records are readable through the reminder inspection surfaces and the
session listing's next-reminder summary. The reminder service does not
prescribe, prefix, or format subsequent agent-authored output.

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
Neither outcome mutates the append-only reminder record, escapes into the parent
polling loop, or becomes human-facing internal error feedback.

### Use cases

#### UC-RMS1: A person asks their assistant to return to a task later

```gherkin
Scenario: Schedule a named reminder for the assistant
  Given a person asks their assistant to return to a task later
  When the assistant schedules a time-based reminder under a named slug
  Then the reminder is durably owned by that assistant's session
  And only that session can list or cancel it
  And the reminder cannot target another session
```

#### UC-RMS2: Distinct intents coexist without a session cap

#### UC-RMS3: Reusing a slug atomically replaces that reminder

#### UC-RMS4: Slug ownership is session-local

#### UC-RMS5: Delivered prescribed slugs cannot be squatted

#### UC-RMS6: A person inspects and cancels their assistant's reminders

```gherkin
Scenario: Inspect the assistant's own reminders
  Given a person's assistant owns time-based and event-anchored reminders
  When the person asks the assistant to list its reminders
  Then the assistant sees only reminders owned by its session, including their intent and schedule

Scenario: Cancel reminders without recalling accepted input
  Given a person's assistant owns live reminders
  When the person asks it to cancel a reminder or all reminders
  Then the service applies the selected profiles' cancellation policies before removing anything
  And accepted session input is not recalled
```

#### UC-RMS7: A firing one-shot reminder is handed to control delivery once

#### UC-RMS8: A recurring reminder advances without agent re-arming

#### UC-RMS9: Restart recovery preserves reminder intent without catch-up noise

#### UC-RMS10: Ended sessions retain no live reminders

#### UC-RMS11: Event-triggered firing is typed, first-match, and silent on false

#### UC-RMS12: Goal drive is a sliding inactivity reminder

#### UC-RMS14: Reminder lifecycle is auditable through service records

#### UC-RMS15: A personal assistant prepares and regrounds for a scheduled action

```gherkin
Scenario: Prepare and reground for a scheduled action
  Given a person wants their assistant to prepare before an important scheduled action
  When the assistant schedules one reminder to prepare and another to reground when the action is due
  Then the person can inspect or cancel each reminder independently
  And the later reminder prompts fresh grounding of relevance, data, and authorization
  And neither reminder authorizes the action
```

#### UC-RMS16: An operator can see the next scheduled reminder for a session

```gherkin
Scenario: See the next scheduled reminder
  Given an operator is monitoring a session with live reminders
  When they read the session listing
  Then it identifies the next scheduled reminder by slug and timestamp
  And event-anchored reminders remain inspectable through the reminder registry
  And a session with no live reminders shows no next reminder
```

#### UC-RMS17: Reminder firings ride the shared control-delivery order

#### UC-RMS18: Satisfied reminder intent reconciles its schedule before the explicit sentinel

#### UC-RMS19: A self-owning agent departs only after its final output settles

#### UC-RMS20: A recurring firing states its cancellation instruction in the envelope

#### UC-RMS21: A bare NOOP turn retires no reminder

#### UC-RMS22: Only firings reach the agent

#### UC-RMS23: Retired reminder vocabulary cannot poison a delivery window

#### UC-RMS24: A permanent reminder-record failure cannot stall projection

#### UC-RMS25: A cancellation-protected reminder remains continuously armed

#### UC-RMS26: A firing exposes its occurrence history

#### UC-RMS27: A newer firing supersedes an undelivered one

#### UC-RMS28: An interrupted agent returns to its work after answering non-human input

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
