---
description: A message that tells a person about platform events reaches them on their
  own routed channel as readable markdown stating what happened, to which thing, on
  which computer and when — for every event type, including types introduced later.
visibility: internal
---

# Notification Messages — Spec

## What it is

When the platform tells a person about an event, it sends one message to that
person on their own routed channel, resolved the way every person-addressed
message is routed (`local/projects/teleclaude/spec/messaging`).

The message is readable markdown in plain words. It states:

- what happened;
- the thing it happened to;
- the computer it happened on;
- when it happened.

A message states facts for a person to read. It carries no agent framing, such
as a bracketed envelope header, and no instruction or action for the reader.

Every event type is told this way, including a type introduced after the
messages were built: what a message says comes from the facts the event and its
type's declaration state (`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`),
so a new type needs no change to how messages are composed or delivered.

Which events are told, to whom, and what a consumer adds to its own messages —
such as how long a recovered thing was broken — belong to the consumer that
tells people (`local/projects/teleclaude/spec/feature/integration/incident-alerts`).

## Canonical fields

### Use cases

#### UC-NM1: A message says what happened, to what, where and when

```gherkin
Given a person is told about a platform event
When the person reads the message on their channel
Then it states in plain words what happened
And it names the thing it happened to
And it names the computer it happened on
And it states when it happened
```

#### UC-NM2: A message carries facts and no agent framing

```gherkin
Given a person is told about a platform event
When the person reads the message on their channel
Then it is readable markdown
And it carries no bracketed envelope header
And it tells the reader no action to take
```

#### UC-NM3: A new event type reads as well as a known one

```gherkin
Given an event type introduced after the messages were built
And nothing about composing or delivering messages has changed since
When a person is told about an event of that type
Then the message states what happened, the thing, the computer and the time as it does for every other type
```

#### UC-NM4: A message reaches the person on their own channel

```gherkin
Given a person whose routed channel is one of the platform's messaging channels
When the person is told about a platform event
Then the message arrives on that channel
And it reaches no one else
```
