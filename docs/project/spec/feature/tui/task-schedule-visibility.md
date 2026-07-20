---
description: 'Schedule visibility on TUI todo rows: a bounded next-occurrence schedule
  column replaces the one-cell schedule badge, and a task-error-held row shows its
  fault instant in the error style instead of a next occurrence.'
visibility: public
delivered_by:
  - tui-task-schedule-visibility
---

# Task Schedule Visibility — Spec

## Required reads

- @docs/project/spec/feature/tui/todo-row-alignment.md

## What it is

A todo row whose todo carries a schedule renders a schedule property column
(label `S`) in the shared property-column block, showing the instant the
schedule next fires — never the schedule rule itself. A rule with comma-list
cron fields is unbounded in humanized form and would inflate the shared column
width for every row in the pane; a next-occurrence instant is bounded by
construction. The raw rule stays inspectable through `telec todo show`; the TUI
never renders it.

The value is recomputed at render time from the stored rule (`cron:` five-field
or ISO one-shot), so it advances to the following instant on the view's normal
refresh cadence. Cron instants are evaluated in UTC, matching the runner's
due-check semantics, and rendered in the local timezone. Values are absolute
times, never countdowns.

A todo held by a task-error hold renders the schedule column differently: the
fault instant (when the error outcome was stamped) in the error style, instead
of a next occurrence — nothing fires while the hold stands, so a next-occurrence
value would be untruthful. The hold glyph in the state column continues to
render alongside it.

Rows without a schedule render no schedule column content. The former one-cell
schedule badge no longer exists; the presence of the schedule column value is
the row's schedule signal.

## Canonical fields

### Rendered formats

All formats resolve in the local timezone and are bounded:

- next occurrence on the current calendar day: `S:HH:MM`
- within the next seven days: `S:Ddd HH:MM` (abbreviated weekday)
- beyond seven days, same calendar year: `S:MM-DD HH:MM`
- a different calendar year: `S:YYYY-MM-DD`

### Use cases

#### UC-TSV1: A scheduled todo row shows its next occurrence

```
Given a todo carries a recurring cron schedule
And the todo is not held
When its row renders in the preparation view
Then the row's property column block includes a schedule column showing the schedule's next occurrence instant
And the value uses the bounded format for the instant's distance from now
And the value renders in the local timezone
And the schedule rule text itself never renders
```

#### UC-TSV2: A one-shot schedule renders in the same bounded formats

```
Given a todo carries a one-shot ISO schedule
And the todo is not held
When its row renders in the preparation view
Then the schedule column shows the scheduled instant in the same bounded format family
```

#### UC-TSV3: A task-error-held todo shows its fault instant in the error style

```
Given a kind=task todo carries a schedule
And a firing stamped an error outcome, holding the todo with the task-error hold source
When its row renders in the preparation view
Then the schedule column shows the hold's set instant instead of a next occurrence
And the value renders in the error style
And the state column's hold glyph renders
```

#### UC-TSV4: A row without a schedule renders no schedule column content

```
Given a todo carries no schedule
When its row renders in the preparation view
Then the row renders no schedule column value
And the state column contains no schedule badge cell
```
