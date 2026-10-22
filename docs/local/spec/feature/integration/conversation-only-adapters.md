---
description: Non-Discord human-facing adapters provide identity binding and conversation
  input→response delivery without operator-console controls.
---

# Conversation-Only Adapters — Spec

## What it is

Human-facing adapters other than Discord are conversation surfaces. They bind
an external person to a personal-assistant session, accept supported input
modalities, and return that session's response to the same origin surface.
Discord alone carries the operator console and admin controls.

### Receiver ownership

Telegram's inbound receiver starts only on a computer whose configuration
declares it the mesh master, including when a non-master has Telegram enabled
in its local configuration. A non-master does not claim Telegram updates or
perform conversation-entry side effects. Every conversational surface, the
master's Telegram receiver included, submits input only under the owner
decision in
`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`.

Discord's computer-owned operator surfaces remain active on their owning
computers. Provider receipt, connection readiness and possession of credentials
are transport facts; they do not confer conversation ownership
(`general/principle/trust-and-guardrails`).

Person-addressed outbound delivery follows its existing messaging contract.

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

#### UC-COA3: An operator can use Discord for administration while other adapters carry conversations

```gherkin
Scenario: Manage the platform through Discord
  Given Discord and a non-Discord adapter both carry person-facing traffic
  When an operator uses the platform's administrative controls
  Then those controls are available through Discord
  And the other adapter remains a conversation input-and-response surface
```

#### UC-COA4: A peer does not activate a Telegram receiver

#### UC-COA5: An operator can manage a project forum while the master handles conversations

### Cross-context references

- **integration** owns provider-boundary input normalization and response
  delivery for each adapter.
- **identity** owns person resolution and invitation binding.
- **agent_runtime** owns session input acceptance and execution.
- **Discord presentation** owns the operator console and admin rendering.

## Known caveats

- Identity binding, invitation binding and help-desk entry may use
  provider-native entry gestures such as a start link; those gestures establish
  conversation identity or the conversation's help desk and are not
  operator-console controls.
- Person-addressed outbound notifications use the messaging-provider contract,
  not the conversation adapter, and are unchanged by this capability.

- While more than one live computer declares itself master, each of them starts
  its Telegram receiver, but conversation entry has no owner
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).
  Telegram updates those receivers claim during the conflict go unanswered and
  are not replayed.
