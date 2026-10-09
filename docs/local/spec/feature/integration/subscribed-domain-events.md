---
description: A person hears every published-domain event their notification interests select and whose origin they can see, as it happens, from the computer where it happened, at least once — each event its own fact, with nothing to close and no recovery message.
visibility: internal
delivered_by:
  - domain-notifications
---

# Subscribed Domain Events — Spec

## What it is

People hear about the events of the published domains they are interested in,
such as an invoice being paid or a review being rejected, as those events happen.

An event of a published domain is one whose type begins with that domain's name
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`): the
platform's own domain events, such as `sdlc`, and the events an external system
relays through an inbound endpoint, such as `erp`, alike. Events the platform
emits about its own operation are not domain events; incident alerts tell those
(`local/projects/teleclaude/spec/feature/integration/incident-alerts`).

A domain event is told to a person when both hold:

- the person's notification interests select it: the category named after the
  event's domain is switched on and one of its patterns matches the event's type
  (`local/projects/teleclaude/spec/feature/config/notification-interests`);
- the person is in the event's audience: the person can see the event's origin
  by the platform's one reach rule, as on every other surface that shows
  platform data (`local/projects/teleclaude/spec/feature/identity/data-visibility`).
  A person hears about what they can see, whichever computer produced the event.

Each domain event is a fact of its own: domain events report no state of a thing
under the platform lifecycle convention (`event-envelope`), so there is nothing
to open, close or recover. Every event that is told is told as it comes, in one
message, and a second event about the same thing is a second message.
Whether an event is told depends only on the person's interests and the
event's audience; nothing the event or its producer states marks it as worth
telling.

Only the computer where the event happened tells it — the computer its source
names — so no other computer in the fleet tells it again. Each message
takes the form every person-addressed notification takes
(`local/projects/teleclaude/spec/feature/integration/notification-messages`).

Delivery is at least once. A message is recorded as told once its channel
accepts it, and a message recorded as told is never sent again. Accepting a
message and recording it are not one operation, because the channels take no
delivery identity a repeat could be recognized by, so a message whose recording
was interrupted is sent again rather than lost.

A message that cannot be delivered to one person does not hold back the others,
and is not repeated to those already told. It is attempted again a bounded
number of times; one that still cannot be delivered is parked where it can be
inspected, never counted as told.

## Canonical fields

### Use cases

#### UC-SD1: A selected domain event is told as it happens

```gherkin
Scenario Outline: Every published domain's events are told the same way
  Given a person whose "<category>" notification interests are switched on with the pattern "<pattern>"
  And who can see the event's origin
  When <producer> emits an event of type "<type>"
  Then the person receives one message about it on their own channel

  Examples:
    | category | pattern   | producer                                         | type                 |
    | sdlc     | review.*  | the platform, about the sdlc domain it publishes | sdlc.review.approved |
    | erp      | invoice.* | an inbound endpoint, relaying an erp request     | erp.invoice.paid     |
```

#### UC-SD2: Only events the person's interests select are told

```gherkin
Scenario Outline: The interests decide which domain events reach the person
  Given a person who can see the origin of every event below
  And whose notification interests <interests>
  When an event of type "erp.invoice.paid" occurs
  Then the person <outcome>

  Examples:
    | interests                                                       | outcome              |
    | hold the erp category switched on with the pattern "invoice.*"  | receives one message |
    | hold the erp category switched on with the pattern "order.*"    | receives no message  |
    | hold the erp category switched off with the pattern "invoice.*" | receives no message  |
    | hold no erp category                                            | receives no message  |
    | hold only the sdlc category, switched on with the pattern "*"   | receives no message  |
```

#### UC-SD3: Only events whose origin the person can see are told

```gherkin
Scenario Outline: Reach bounds what interests can select
  Given a person whose "erp" notification interests are switched on with the pattern "*"
  And the person's reach <reach> the origin of an event
  When an event of type "erp.invoice.paid" with that origin occurs
  Then the person <outcome>

  Examples:
    | reach          | outcome              |
    | admits         | receives one message |
    | does not admit | receives no message  |
```

#### UC-SD9: A company's roster alone does not bring its projects' events

```gherkin
Scenario Outline: Membership reaches the company, not its projects
  Given a person whose "sdlc" notification interests are switched on with the pattern "*"
  And whose only reach comes from being a member on a company's roster
  When an event of type "sdlc.review.approved" happens in <origin>
  Then the person <outcome>

  Examples:
    | origin                     | outcome              |
    | the company itself         | receives one message |
    | a project the company owns | receives no message  |
```

#### UC-SD4: Every domain event is its own message

```gherkin
Given a person whose notification interests select an event type and who can see its origin
When two events of that type about the same thing occur
Then the person receives two messages, one for each event
And no message tells that anything was resolved, closed or working again
```

#### UC-SD5: Platform events are not told as domain events

```gherkin
Given a person whose notification interests select every event of a published domain
When the platform emits an event about its own operation
Then the person receives no domain-event message about it
```

#### UC-SD6: Only the computer where it happened tells it

```gherkin
Given a fleet of two computers that both receive every platform event
And a person whose notification interests select an event type and who can see its origin
When an event of that type happens on one of the computers
Then the person receives exactly one message about it
And it names the computer where the event happened
```

#### UC-SD7: A person who cannot be reached is not counted as told

```gherkin
Given two people whose notification interests select an event type and who can see its origin
And the channel of one of them fails to accept messages
When an event of that type occurs
Then the other person receives one message about it
And the message to the unreachable person is attempted again, without repeating it to the other
And when it still cannot be delivered, the undelivered message is parked where it can be inspected
```

#### UC-SD8: A selected event is delivered at least once

```gherkin
Scenario Outline: An interruption never loses a message and repeats only an unrecorded one
  Given an event that the person's interests select and whose origin the person can see
  When the event's handling is interrupted, such as by a restart, <when>
  Then the person <outcome>

  Examples:
    | when                                                          | outcome                                         |
    | before the message reached the channel                        | receives the message once it is handled again   |
    | after the channel accepted the message and it was recorded    | receives no second message                      |
    | after the channel accepted the message, before it was recorded | receives the message a second time              |
```

## Known caveats

- **A message whose recording was interrupted arrives twice.** The channels
  take no delivery identity, so accepting a message and recording it as told
  cannot be one operation; delivery is at least once by choice, because the
  alternative loses the message.

- **A computer runs this telling only once it is upgraded.** An event that
  happens on a computer whose version predates this behavior is not told,
  because only the computer where an event happened tells it.
