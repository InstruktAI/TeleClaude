---
description: How delivering a chat-platform message longer than the platform's single-message
  limit affects the daemon's other work.
---

# Outbound Message Overflow — Spec

## What it is

The behavior an observer can rely on while the daemon delivers a message that
is longer than the receiving chat platform's single-message limit.

## Canonical fields

### Use cases

#### UC-OMO1: A person can receive a long message without stalling the daemon

```gherkin
Scenario: Deliver a response longer than Discord's single-message limit
  Given an assistant has a response longer than Discord can display in one message
  When the assistant delivers it while the daemon handles another request
  Then the person receives consecutive messages that fit within Discord's message limit
  And the daemon answers the other request within its ordinary response time
```
