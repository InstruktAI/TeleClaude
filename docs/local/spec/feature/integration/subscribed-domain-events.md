---
description: A person hears every published-domain event their notification interests select and whose audience they are in, as it happens, in one message from the computer where it happened — each event its own fact, with nothing to close and no recovery message.
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
- the person is in the event's audience: the people on the roster of the
  company the event's origin belongs to — the company itself or any project it
  owns — whichever of its projects or computers produced the event, and, for an
  origin that belongs to no company on a person's roster, whoever the platform's
  one reach rule admits
  (`local/projects/teleclaude/spec/feature/identity/data-visibility`).

Each domain event is a fact of its own: domain events report no state of a thing
under the platform lifecycle convention (`event-envelope`), so there is nothing
to open, close or recover. Every event that is told is told once, as it comes,
in one message, and a second event about the same thing is a second message.
Whether an event is told depends only on the person's interests and the
event's audience; nothing the event or its producer states marks it as worth
telling.

Only the computer where the event happened tells it — the computer its source
names — so each person hears each event once across the fleet. Each message
takes the form every person-addressed notification takes
(`local/projects/teleclaude/spec/feature/integration/notification-messages`).

A message that cannot be delivered to one person does not hold back the others,
and is not repeated to those already told. It is attempted again a bounded
number of times; one that still cannot be delivered is parked where it can be
inspected, never counted as told. A restart neither loses a message nor tells
again one already recorded as told.

## Canonical fields

### Use cases

#### UC-SD1: A selected domain event is told as it happens

```gherkin
Scenario Outline: Every published domain's events are told the same way
  Given a person whose "<category>" notification interests are switched on with the pattern "<pattern>"
  And who is in the event's audience
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
  Given a person who is in the audience of every event below
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

#### UC-SD3: Outside a person's companies, only events their reach admits are told

```gherkin
Scenario Outline: Reach bounds what interests can select
  Given a person whose "erp" notification interests are switched on with the pattern "*"
  And an event whose origin belongs to no company on the person's roster
  And the person's reach <reach> that origin
  When an event of type "erp.invoice.paid" with that origin occurs
  Then the person <outcome>

  Examples:
    | reach          | outcome              |
    | admits         | receives one message |
    | does not admit | receives no message  |
```

#### UC-SD9: A company's people hear its domain events from any of its projects

```gherkin
Scenario Outline: The company audience does not depend on the producing project
  Given a person on a company's roster whose "sdlc" notification interests are switched on with the pattern "*"
  When an event of type "sdlc.review.approved" happens in <origin>
  Then the person receives one message about it

  Examples:
    | origin                                                  |
    | the company itself                                      |
    | a project the company owns that the person is assigned to |
    | a project the company owns that the person is not assigned to |
```

#### UC-SD4: Every domain event is its own message

```gherkin
Given a person whose notification interests select an event type and who is in its audience
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
And a person whose notification interests select an event type and who is in its audience
When an event of that type happens on one of the computers
Then the person receives exactly one message about it
And it names the computer where the event happened
```

#### UC-SD7: A person who cannot be reached is not counted as told

```gherkin
Given two people whose notification interests select an event type and who are in its audience
And the channel of one of them fails to accept messages
When an event of that type occurs
Then the other person receives one message about it
And the message to the unreachable person is attempted again, without repeating it to the other
And when it still cannot be delivered, the undelivered message is parked where it can be inspected
```

#### UC-SD8: A restart neither loses nor repeats a told event

```gherkin
Given an event that the person's interests select and whose audience the person is in
When the platform restarts on the computer where it happened while that event is being told
Then the person receives the message about it after the restart if it was not yet sent
And receives no second message if it was recorded as told
```

## Known caveats

- **A computer runs this telling only once it is upgraded.** An event that
  happens on a computer whose version predates this behavior is not told,
  because only the computer where an event happened tells it.
