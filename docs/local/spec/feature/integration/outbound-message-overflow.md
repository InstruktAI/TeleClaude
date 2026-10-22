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

#### UC-OMO1: A person receives a long response while the daemon remains responsive

```gherkin
Scenario: Deliver a response longer than the receiving platform's message limit
  Given an assistant response exceeds the receiving chat platform's single-message limit
  And the daemon receives another request during delivery
  When the response is delivered
  Then the person receives it in consecutive messages that fit within the platform's limit
  And the daemon answers the other request within its ordinary response time
```
