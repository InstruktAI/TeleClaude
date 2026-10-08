---
description: A person's notification interests — per category, a switch and type patterns relative to the category's namespace — starting from the person's role, changed afterwards only by the person or on their request, and validated without being altered.
visibility: internal
delivered_by:
  - platform-alerts
---

# Notification Interests — Spec

## What it is

A person's configuration states which platform events they want to hear about.
Interests are grouped by category:

- the `teleclaude` category holds interests in the events the platform itself
  emits;
- a category named after a published domain, such as `erp` or `sdlc`, holds
  interests in that domain's events.

Each category has a switch that turns it on or off and a list of type patterns.
A pattern is written relative to its category: in the `teleclaude` category,
`job.*` selects every type under `teleclaude.job`, and `*` selects every
platform type. Patterns follow the platform's one type-pattern grammar and
matcher (`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`).

An event matches a person's interests when its type falls in a category that is
switched on and one of that category's patterns matches it. A category that is
switched off matches nothing and keeps its patterns as written, so switching it
on again restores them.

Interests only select. Whether a matching event is told to the person at all,
and to whom an event may be told, is decided by the consumer that tells people
(`local/projects/teleclaude/spec/feature/integration/incident-alerts`).

A person starts with their role's interests when the person is created: a
platform administrator starts with the `teleclaude` category switched on and
selecting `job.*` and `deployment.*`, and every other role starts with none.
From then on interests change only when the person changes them, or an agent
acting on the person's request does; the platform never adds, removes or
rewrites them.
Configuration that predates notification interests converges to them like any
new field (`local/projects/teleclaude/spec/feature/config/document-migration`);
values already present are never overwritten.

Validation reports an interest it cannot use — a category that is neither
`teleclaude` nor a published domain, or a pattern the matcher refuses — and
leaves the configuration exactly as written. An interest it reports selects
nothing; the person's other interests keep working.

## Canonical fields

### Use cases

#### UC-NI1: A pattern selects events within its own category

```gherkin
Scenario Outline: Patterns are read relative to their category
  Given a person whose "<category>" interests are switched on with the pattern "<pattern>"
  When an event of type "<type>" occurs
  Then the event <outcome> the person's interests

  Examples:
    | category   | pattern     | type                         | outcome           |
    | teleclaude | job.*       | teleclaude.job.run.failed    | matches           |
    | teleclaude | job.*       | teleclaude.system.burst.detected | does not match    |
    | teleclaude | *           | teleclaude.system.burst.detected | matches           |
    | erp        | invoice.*   | erp.invoice.paid             | matches           |
    | erp        | invoice.*   | erp.invoices.paid            | does not match    |
    | erp        | invoice.*   | teleclaude.job.run.failed    | does not match    |
```

#### UC-NI2: A switched-off category selects nothing and keeps its patterns

```gherkin
Given a person whose "teleclaude" interests hold the pattern "job.*"
And the person has switched the "teleclaude" category off
When an event of a type under "teleclaude.job" occurs
Then the event does not match the person's interests
And the person's configuration still holds the pattern "job.*"
When the person switches the "teleclaude" category on again
Then the next event of a type under "teleclaude.job" matches the person's interests
```

#### UC-NI6: A new person starts with their role's interests

```gherkin
Scenario Outline: The starting interests follow the role
  Given an operator creates a person whose role is <role>
  When the person's configuration is read
  Then <starting interests>

  Examples:
    | role                   | starting interests                                                                 |
    | platform administrator | its teleclaude category is switched on and selects job and deployment events only  |
    | any other role         | it holds no notification interests                                                 |
```

#### UC-NI4: The platform never changes a person's interests

```gherkin
Given a person who has chosen their notification interests
When the platform is upgraded, or the person's role changes
Then the person's interests are exactly as they were
And only the person, or an agent acting on the person's request, changes them
```

#### UC-NI5: Validation reports an unusable interest and leaves it as written

```gherkin
Scenario Outline: An unusable interest is reported, not repaired
  Given a person's interests contain <unusable interest>
  When an operator validates the configuration
  Then validation reports that interest with the reason it cannot be used
  And the person's configuration is left exactly as written
  And the person's other interests still select the events they match

  Examples:
    | unusable interest                                        |
    | a category that is neither teleclaude nor a published domain |
    | a pattern the type-pattern matcher refuses               |
```
