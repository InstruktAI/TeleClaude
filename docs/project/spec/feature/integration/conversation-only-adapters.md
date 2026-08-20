---
description: Non-Discord human-facing adapters provide identity binding and conversation input→response delivery without operator-console controls.
delivered_by:
  - adapters-input-response-only
---

# Conversation-Only Adapters — Spec

## What it is

Human-facing adapters other than Discord are conversation surfaces. They bind
an external person to a personal-assistant session, accept supported input
modalities, and return that session's response to the same origin surface.
Discord alone carries the operator console and admin controls.

## Canonical fields

### Use cases

#### UC-COA1: A non-Discord adapter carries a conversation turn

```gherkin
Given a human is bound to a personal-assistant session through a non-Discord adapter
When the human supplies a supported conversational input on that adapter
Then the input is accepted for the bound session through the shared inbound contract
And the session's notices and answer return to that human on the same origin adapter
```

#### UC-COA2: A non-Discord adapter exposes no operator console

```gherkin
Given a human is using a non-Discord adapter
When the adapter publishes or handles its interactive surface
Then it offers no agent selection, session lifecycle, raw-key, channel-management, or admin-reflection controls
And identity or invitation binding remains available as the entry into conversation
```

#### UC-COA3: Discord retains the admin surface

```gherkin
Given the platform has Discord and one or more non-Discord adapters enabled
When an operator uses adapter-specific administrative controls
Then those controls are available only through Discord
And the non-Discord adapters remain conversation input→response surfaces
```

### Cross-context references

- **integration** owns provider-boundary input normalization and response
  delivery for each adapter.
- **identity** owns person resolution and invitation binding.
- **agent_runtime** owns session input acceptance and execution.
- **Discord presentation** owns the operator console and admin rendering.

## Known caveats

- Identity and invitation binding may use provider-native entry gestures such
  as a start link; those gestures establish conversation identity and are not
  operator-console controls.
- Person-addressed outbound notifications use the messaging-provider contract,
  not the conversation adapter, and are unchanged by this capability.
