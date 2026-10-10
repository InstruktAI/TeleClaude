---
description: A chat-platform message longer than the platform's single-message limit is delivered as consecutive in-limit messages without holding up the daemon's other work.
delivered_by:
  - fix-daemon-event-loop-wedged-170s-splitting
---

# Outbound Message Overflow — Spec

## What it is

When a message bound for a chat platform is longer than that platform's
single-message limit, the adapter delivering it splits it into consecutive
messages, in order, each within the limit. Formatting markup still open where
one message ends is closed there and reopened at the start of the next.

## Canonical fields

### Use cases

#### UC-OMO1: Delivering a very long message does not hold up the daemon's other work

```gherkin
Given a message several million characters long is being delivered to Discord, which must split it into consecutive messages
When an agent asks the daemon for its health while that message is being prepared for delivery
Then the daemon answers the agent within its ordinary response time
And the long message still reaches Discord as consecutive messages that each fit within Discord's message limit
```
