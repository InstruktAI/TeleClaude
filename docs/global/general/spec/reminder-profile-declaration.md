---
description: 'The declaration shape for a prescribed reminder profile: where it lives, the fields it states, and the cadence rules a profile may declare.'
visibility: 'public'
---

# Reminder Profile Declaration — Spec

## What it is

A prescribed reminder is a reserved slug whose intent is owned by a policy,
procedure, command, or job. Its declaration lives beside that owner under a
`#### Reminder: <slug>` heading; the reminder service registers the slug so an
arbitrary reminder cannot squat it, and registration never moves the
declaration away from its owner. The general reminder rules are
`general/policy/reminder`.

## Canonical fields

Every declaration states, in this order:

- **Owner** — the snippet that owns the intent.
- **Parameters** — caller-supplied inputs, or `none`.
- **Activation anchor** — the moment the reminder is armed.
- **Duration** — relative interval or absolute schedule. The owning surface
  states its cadence; the reminder service never repeats or overrides it.
- **Recurrence** — one-shot or recurring. Recurrence is declared, never inferred.
- **Arm condition** — the exact state in which the reminder is set.
- **Intent** — the exact agent-authored text the firing carries.
- **Firing behavior** — what the agent does when it fires.
- **Cancellation** — the stop condition, expressed as the moment the next move
  stops being the holder's.
- **Invocation** — the minimal `telec reminders set <slug>` form.

### Adaptive cadence

A time-recurring profile may declare adaptive cadence by naming its initial
interval, backoff rule, maximum interval, the activity that resets the interval,
and its terminal cancellation condition. Re-setting the same slug atomically
replaces the schedule, so a watcher never passes through an unarmed gap while
changing pace. A profile without this declaration cannot acquire adaptive
cadence by caller choice. Event-triggered profiles have no cadence to override.

## Known caveats

- A prescribed slug is reserved once its declaration is delivered. Historical
  arbitrary reminders reserve nothing.
