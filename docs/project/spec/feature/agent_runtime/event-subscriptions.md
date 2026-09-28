---
description: Agent sessions subscribe to catalog events and are woken with each matching event's content, once or every time, until they withdraw the subscription or their session ends.
delivered_by:
  - telec-events-subscribe-feat
---

# Event Subscriptions — Spec

## What it is

An event subscription is an agent session's standing request to be woken when a
platform event of a given catalog type occurs. The subscribing session receives
the event itself — its type, identity, time, originating computer, and content —
as a wake, so it can react at the moment the fact happens instead of polling or
guessing when to look again. A subscription is either single-delivery, spent by
the first event it delivers, or every-time, live until it is withdrawn or its
session ends. It may be narrowed to events whose content carries given values.

A subscription belongs to the session that made it. The session can list and
withdraw its own subscriptions and cannot see or touch another session's. The
event catalog listing is the discovery surface: it names the subscribable event
types and tells its reader how to subscribe to them.

Subscriptions consume the event catalog as it stands and change neither which
events the platform emits nor what they carry. The wake rides the platform's
control-delivery surface (`project/spec/feature/agent_runtime/control-delivery`),
which owns in-turn delivery, idle waking, batching, and session-close cleanup of
pending payloads.

## Canonical fields

### Use cases

#### UC-ES1: A single-delivery subscription wakes its agent once

```gherkin
Given an agent session has subscribed once to an event type from the catalog
When an event of that type occurs
Then the agent is woken with that event's type, identity, time, originating computer, and content
And the subscription is spent
And a later event of that type does not wake the agent
```

#### UC-ES2: An every-time subscription wakes its agent for each occurrence

```gherkin
Given an agent session has subscribed to every occurrence of an event type from the catalog
When several events of that type occur over time
Then the agent is woken with each event's content, one wake per event
And the subscription stays live after each wake
```

#### UC-ES3: A narrowed subscription is woken only by matching content

```gherkin
Given an agent session has subscribed to an event type narrowed to events whose content carries given values
When an event of that type occurs whose content carries those values
Then the agent is woken with that event
But when an event of that type occurs whose content does not carry those values
Then the agent is not woken
And a single-delivery subscription is not spent by it
```

#### UC-ES4: The wake reaches a working agent and an idle agent alike

```gherkin
Given an agent session holds a live subscription
When a matching event occurs while the agent is mid-turn
Then the agent receives the event at its next natural work boundary without its turn being interrupted
But when a matching event occurs while the agent is idle
Then the agent is woken and receives the event
```

#### UC-ES5: A withdrawn subscription wakes nothing

```gherkin
Given an agent session withdraws one of its live subscriptions
When a matching event occurs afterwards
Then the agent is not woken by it
And withdrawing a subscription that no longer exists reports that nothing was removed without failing
```

#### UC-ES6: An agent sees and controls only its own subscriptions

```gherkin
Given two agent sessions each hold live subscriptions
When one session lists its subscriptions
Then it sees each of its own live subscriptions with its event type, delivery mode, and any narrowing
And it sees none of the other session's subscriptions
And it cannot withdraw a subscription belonging to the other session
```

#### UC-ES7: The catalog listing tells an agent how to subscribe

```gherkin
Given an agent reads the event catalog listing
When it looks for how to act on a listed event type
Then the listing tells it how to subscribe to that event type
```

#### UC-ES8: A subscription to an unknown event type is refused

```gherkin
Given an agent session asks to subscribe to an event type the catalog does not list
When the request is made
Then no subscription is created
And the refusal names the unknown type and points the agent to the event catalog listing
```

#### UC-ES9: Subscriptions end with their session and survive a platform restart

```gherkin
Given an agent session holds live subscriptions
When the platform restarts while the session stays alive
Then the session's subscriptions are still live and matching events still wake it
But when the session ends
Then all of its subscriptions are removed and no later event is delivered for them
```

#### UC-ES10: One event wakes a subscription at most once

```gherkin
Given an agent session holds a live every-time subscription
When a matching event is processed more than once by the platform
Then the agent is woken for that event exactly once
```

#### UC-ES11: A subscription never widens an event's declared visibility

```gherkin
Given agent sessions on two computers hold subscriptions to the same event type
When a cluster-visible event of that type occurs on one computer
Then both sessions are woken by it
But when a local event of that type occurs on one computer
Then only the session on that computer is woken by it
```

#### UC-ES12: Only callers entitled to every tenant may subscribe

```gherkin
Given an agent session acting for a person who holds the admin role, or running under the platform's system principal for no company
When it asks to subscribe to a catalog event type
Then the subscription is created
But when the session acts for a person who is not an admin, or runs under the system principal for a company
Then the request is refused and no subscription is created
```

## Known caveats

- A subscription observes events from the moment it is created. An event that
  occurred before it existed is never delivered to it.
- Events carry no tenant scope, so a subscriber observes events belonging to any
  company or person on the computers it is entitled to observe. The subscriber
  audience is therefore limited to callers who may already read every tenant.
- An every-time subscription to a high-frequency event type wakes its agent as
  often as the event occurs; control delivery batches what is pending at each
  boundary but does not rate-limit.
