---
description: Platform administrators who are interested in a platform problem hear about it once when a thing breaks and once when it works again, with how long it was broken, from the computer where it happened — and nothing in between.
visibility: internal
delivered_by:
  - platform-alerts
---

# Incident Alerts — Spec

## What it is

Incident alerts tell platform administrators about problems on the platform.
They read the events the platform itself emits
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`). An event
either reports that a thing failed, reports that a thing works, or reports
neither; an event that reports neither is never told.

The thing is what an administrator recognizes as broken: a recurring job is one
thing across all its runs, and otherwise the thing is what the event is about.

A thing whose working again the platform reports is broken from its first
reported failure until an event reports that it works:

- the first failure of a thing that is not broken tells, and the thing is
  broken from then on;
- a further failure of a broken thing tells nothing;
- an event reporting that a broken thing works tells once that it works again
  and how long it was broken, and the thing is no longer broken;
- an event reporting that a thing works tells nothing when the thing is not
  broken.

A failure of a thing whose working again the platform never reports is told
each time it occurs, and nothing is kept about it.

An alert is told to each platform administrator whose notification interests
select the event's type
(`local/projects/teleclaude/spec/feature/config/notification-interests`), and to
no one else, whatever their interests. Only the computer where the event
happened tells it, so each administrator hears each alert once across the
fleet. Each alert is one message in the form every person-addressed
notification takes (`local/projects/teleclaude/spec/feature/integration/notification-messages`).

The only state incident alerts keep is, per computer, which things are broken
and since when; a thing that works again leaves nothing behind. No record of
sent alerts is kept, and a restart of the platform neither tells an alert again
nor loses the message that a broken thing works again.

## Canonical fields

### Use cases

#### UC-IA1: The first failure of a thing tells interested administrators

```gherkin
Given a platform administrator whose notification interests select platform job events
And a recurring job that is not broken
When a run of that job fails
Then the administrator receives one message that the job failed
```

#### UC-IA2: A broken thing failing again tells nothing

```gherkin
Given a platform administrator whose notification interests select platform job events
And a recurring job whose last run failed and was told
When the next runs of that job fail too
Then the administrator receives no further message about that job
```

#### UC-IA3: A broken thing working again tells once, with how long it was broken

```gherkin
Given a platform administrator who was told that a recurring job failed
And the job's runs kept failing since
When a run of that job succeeds
Then the administrator receives one message that the job works again
And the message states how long the job was broken
When the following runs of that job succeed too
Then the administrator receives no further message about that job
```

#### UC-IA4: A thing that was not broken working tells nothing

```gherkin
Given a platform administrator whose notification interests select platform job events
And a recurring job none of whose runs failed since it last worked
When a run of that job succeeds
Then the administrator receives no message about that job
```

#### UC-IA5: An event that reports no failure and no recovery tells nothing

```gherkin
Given a platform administrator whose notification interests select every platform event
When a platform event occurs that reports neither that a thing failed nor that it works
Then the administrator receives no message about it
```

#### UC-IA6: A failure with no reported recovery is told each time

```gherkin
Given a platform administrator whose notification interests select the platform's failure detections
And a kind of failure for which the platform never reports that the thing works again
When that failure occurs twice for the same thing
Then the administrator receives one message for each occurrence
```

#### UC-IA7: Only interested administrators are told

```gherkin
Scenario Outline: The audience is the platform administrators whose interests select the event
  Given a person who <relationship>
  And whose notification interests <interests>
  When a recurring job that is not broken fails
  Then the person <outcome>

  Examples:
    | relationship                         | interests                                        | outcome                         |
    | is a platform administrator          | select platform job events                       | receives one message            |
    | is a platform administrator          | select no platform job events                    | receives no message             |
    | is a platform administrator          | select platform job events in a category switched off | receives no message        |
    | is not a platform administrator      | select platform job events                       | receives no message             |
```

#### UC-IA8: Only the computer where it happened tells it

```gherkin
Given a fleet of two computers that both receive every platform event
And a platform administrator whose notification interests select platform job events
When a recurring job fails on one of the computers
Then the administrator receives exactly one message about it
And it names the computer where the job failed
```

#### UC-IA9: A restart changes nothing about what is told

```gherkin
Given a platform administrator who was told that a recurring job failed
When the platform restarts on the computer where the job runs
And the job's next run fails
Then the administrator receives no further message about that job
When a later run of the job succeeds
Then the administrator receives one message that the job works again, with how long it was broken
```
