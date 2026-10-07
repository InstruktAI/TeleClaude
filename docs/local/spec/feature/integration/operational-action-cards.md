---
description: Human-facing operational action cards render one actionable occurrence
  through the shared paired bracket envelope without occupying the agent-control namespace.
---

# Operational Action Cards — Spec

## Required reads

@docs/local/design/architecture/operational-action-cards.md

## What it is

Operational action cards interrupt a human when a current occurrence requires
their decision or intervention. Their text fallback is a human-facing envelope
rendered by the shared bracket codec from the same semantic model used by the
platform's other envelopes. It is not agent control traffic and never occupies
the reserved `[TeleClaude …]` control namespace.

## Canonical fields

### Use cases

#### UC-OAC1: A human action card uses the registered paired bracket envelope

```gherkin
Given an operational occurrence requires a current action from a human
When the platform renders its text action card
Then the human sees a paired action envelope containing the topic, occurrence minute, summary, and concrete action
And the opening is outside the reserved TeleClaude control namespace
And the body is followed by the registered matching close
And every human push adapter receives that same rendered envelope rather than a private template
```

<!-- planned:human-alerts-agent-only -->

#### UC-OAC2: An occurrence yields one card, from the computer where it happened

```gherkin
Given an operational occurrence on one computer requires a current action from a human
When every computer in the fleet receives its event
Then only the computer the occurrence happened on delivers its card
And no other computer delivers a card for it
```

#### UC-OAC3: Admin action cards reach only administrators who turned them on

```gherkin
Given an operational occurrence requires a current action and addresses no one
When its card is delivered to the platform administrators
Then each administrator who turned admin push on receives it on their configured channels
And an administrator who has not turned it on receives no card
And admin push is off for an administrator until they turn it on
```

<!-- /planned:human-alerts-agent-only -->

### Cross-context references

- **integration** owns push-adapter delivery of the rendered action card.
- **agent_runtime** publishes the shared semantic envelope model and bracket
  codec; integration consumes that published type and renderer without
  declaring vocabulary or closure rules.
