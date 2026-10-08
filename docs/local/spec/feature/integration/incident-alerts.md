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

The thing is what the event is about, its subject, with one exception: a
recurring job is one thing across all its runs.

A thing whose working again the platform reports is broken from its first
reported failure until an event reports that it works:

- the first failure of a thing that is not broken tells, and the thing is
  broken from then on;
- a further failure of a broken thing tells nothing;
- an event reporting that a broken thing works tells once that it works again
  and how long it was broken, and the thing is no longer broken;
- an event reporting that a thing works tells nothing when the thing is not
  broken.

A failure of a kind the platform never reports recovering from is told each
time it occurs, and nothing is kept about it.

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
Given a platform administrator whose notification interests select the platform events that report a thing failing or working
And a thing that is not broken
When an event reports that the thing failed
Then the administrator receives one message that the thing failed
```

#### UC-IA2: A broken thing failing again tells nothing

```gherkin
Given a platform administrator whose notification interests select the platform events that report a thing failing or working
And a thing whose failure was told and that no event has reported working since
When further events report that the same thing failed
Then the administrator receives no further message about that thing
```

#### UC-IA3: A broken thing working again tells once, with how long it was broken

```gherkin
Given a platform administrator who was told that a thing failed
And further events reported that the same thing failed
When an event reports that the thing works
Then the administrator receives one message that the thing works again
And the message states how long the thing was broken
When further events report that the thing works
Then the administrator receives no further message about that thing
```

#### UC-IA4: A thing that was not broken working tells nothing

```gherkin
Given a platform administrator whose notification interests select the platform events that report a thing failing or working
And a thing that is not broken
When an event reports that the thing works
Then the administrator receives no message about that thing
```

#### UC-IA5: An event that reports no failure and no recovery tells nothing

```gherkin
Given a platform administrator whose notification interests select every platform event
When a platform event occurs that reports neither that a thing failed nor that it works
Then the administrator receives no message about it
```

#### UC-IA7: Only interested administrators are told

```gherkin
Scenario Outline: The audience is the platform administrators whose interests select the event
  Given a person who <relationship>
  And whose notification interests <interests>
  When an event reports that a thing that is not broken failed
  Then the person <outcome>

  Examples:
    | relationship                    | interests                                              | outcome              |
    | is a platform administrator     | select the event's type                                | receives one message |
    | is a platform administrator     | do not select the event's type                         | receives no message  |
    | is a platform administrator     | select the event's type in a category switched off     | receives no message  |
    | is not a platform administrator | select the event's type                                | receives no message  |
```

#### UC-IA8: Only the computer where it happened tells it

```gherkin
Given a fleet of two computers that both receive every platform event
And a platform administrator whose notification interests select the event's type
When an event on one of the computers reports that a thing that is not broken failed
Then the administrator receives exactly one message about it
And it names the computer where the thing failed
```

#### UC-IA9: A restart changes nothing about what is told

```gherkin
Given a platform administrator who was told that a thing failed
When the platform restarts on the computer where the thing failed
And a further event reports that the same thing failed
Then the administrator receives no further message about that thing
When an event later reports that the thing works
Then the administrator receives one message that the thing works again, with how long it was broken
```

#### UC-IA10: A failure with no reported recovery is told each time

```gherkin
Given a platform administrator whose notification interests select the platform's failure detections
And a kind of failure for which the platform never reports that the thing works again
When that failure occurs twice for the same thing
Then the administrator receives one message for each occurrence
```

#### UC-IA11: A recurring job is one thing across its runs

```gherkin
Given a platform administrator whose notification interests select platform job events
And a recurring job that is not broken
When a run of the job fails
Then the administrator receives one message that the job failed
When the job's next runs fail too
Then the administrator receives no further message about that job
When a later run of the job succeeds
Then the administrator receives one message that the job works again, with how long it was broken
```
