---
description: How delivering a chat-platform message longer than the platform's single-message limit affects the daemon's other work.
delivered_by:
  - fix-daemon-event-loop-wedged-170s-splitting
---

# Outbound Message Overflow — Spec

## What it is

The behavior an observer can rely on while the daemon delivers a message that
is longer than the receiving chat platform's single-message limit.

## Canonical fields

### Use cases

#### UC-OMO1: Delivering a very long message does not hold up the daemon's other work

```gherkin
Given a message several million characters long is being delivered to Discord, which must split it into consecutive messages
When an agent asks the daemon for its health while that message is being prepared for delivery
Then the daemon answers the agent within its ordinary response time
And the long message still reaches Discord as consecutive messages that each fit within Discord's message limit
```
