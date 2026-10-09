---
description: Platform administrators who are interested in a platform problem hear
  about it once when a thing breaks and once when it works again, with how long it
  was broken, from the computer where it happened — and nothing in between.
visibility: internal
---

# Incident Alerts — Spec

## What it is

Incident alerts tell platform administrators about problems on the platform.
They read the states platform events report under the platform lifecycle
convention (`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`):
an event belongs to a lifecycle family, the last segment of its type names a
state the event catalog declares failing or ok, and the thing whose state it
reports is its subject within its origin, so a failure and its recovery name the
same subject and origin. A recurring job is therefore one thing across all its
runs, and same-named things that originated in different projects, people or
companies are different things.
A matter is one lifecycle family's state of one thing: two families that report
on the same subject are two matters, and one family's recovery never closes the
other's failure.
Every family that can report a failing state also reports an ok state. An event
that reports no state is never told.

A thing is broken from its first reported failing state until an event reports
it ok:

- the first failure of a thing that is not broken tells, and the thing is
  broken from then on;
- a further failure of a broken thing tells nothing;
- an event reporting that a broken thing is ok tells once that it works again
  and how long it was broken, and the thing is no longer broken;
- an event reporting that a thing is ok tells nothing when the thing is not
  broken.

An alert is told to each platform administrator whose notification interests
select the event's type
(`local/projects/teleclaude/spec/feature/config/notification-interests`), and to
no one else, whatever their interests. Only the computer where the event
happened tells it, so each administrator hears each alert once across the
fleet. Each alert is one message in the form every person-addressed
notification takes (`local/projects/teleclaude/spec/feature/integration/notification-messages`).

The only state incident alerts keep is, per computer, which matters are open,
since when, and which selected administrators still await the message of the
matter's latest transition; a thing that works again leaves nothing behind once
every selected administrator has been told. No record of sent alerts is kept,
and a restart of the platform neither tells a recorded alert again nor loses
the message that a broken thing works again.

A message that cannot be delivered to one administrator does not hold back the
others. It stays outstanding and is attempted again a bounded number of times;
an alert that still cannot be delivered is parked where it can be inspected,
never counted as told. When the thing works again before an outstanding failure
message was delivered, that administrator is told the recovery, with how long
the thing was broken, instead of the stale failure.

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

#### UC-IA5: An event that reports no state tells nothing

```gherkin
Given a platform administrator whose notification interests select every platform event
When a platform event occurs that reports no failing or ok state of a thing
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

#### UC-IA12: An administrator who cannot be reached is not counted as told

```gherkin
Given two platform administrators whose notification interests select platform job events
And the channel of one of them fails to accept messages
When a recurring job that is not broken fails
Then the other administrator receives one message that the job failed
And the message to the unreachable administrator is attempted again, without repeating it to the other
And when it still cannot be delivered, the undelivered alert is parked where it can be inspected
```

## Known caveats

- **A send the channel accepted just before the computer stopped is sent again.**
  The platform records each administrator's message once the channel accepts
  it; a message accepted in the moment before that record is made is sent again
  after the restart, because the channels take no delivery identity a resend
  could carry, and dropping it instead could lose the alert.
