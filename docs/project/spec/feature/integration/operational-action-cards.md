---
description: Human-facing operational action cards render one actionable occurrence through the shared paired bracket envelope without occupying the agent-control namespace.
delivered_by:
  - envelope-authoritative-classification
---

# Operational Action Cards — Spec

## Required reads

@docs/project/design/architecture/operational-action-cards.md

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

### Cross-context references

- **integration** owns push-adapter delivery of the rendered action card.
- **agent_runtime** publishes the shared semantic envelope model and bracket
  codec; integration consumes that published type and renderer without
  declaring vocabulary or closure rules.
