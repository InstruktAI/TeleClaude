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

<!-- planned:master-conversation-entry -->

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
Retiring a bot requires resolving any active senders that still depend on that
identity through `local/projects/teleclaude/procedure/conversation-entry-cutover`.

<!-- /planned:master-conversation-entry -->

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
And identity binding, invitation binding and help-desk entry remain available as the entries into conversation
```

#### UC-COA3: Discord retains the admin surface

```gherkin
Given the platform has Discord and one or more non-Discord adapters enabled
When an operator uses adapter-specific administrative controls
Then those controls are available only through Discord
And the non-Discord adapters remain conversation input→response surfaces
```

<!-- planned:master-conversation-entry -->

#### UC-COA4: A peer does not activate a Telegram receiver

```gherkin
Given a computer is not the unique master
And its local Telegram configuration is enabled
When adapters start or reconnect
Then no Telegram inbound receiver is activated on that computer
And no conversation input is consumed by that computer
```

#### UC-COA5: Discord operator surfaces retain their owner

```gherkin
Given a non-master computer owns project forums in Discord
When its adapter starts under master-owned conversation entry
Then its operator surfaces remain available
And conversational ownership does not transfer its forums to another computer
```

<!-- /planned:master-conversation-entry -->

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

<!-- planned:master-conversation-entry -->

- While more than one live computer declares itself master, each of them starts
  its Telegram receiver, but conversation entry has no owner
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).
  Telegram updates those receivers claim during the conflict go unanswered and
  are not replayed.

<!-- /planned:master-conversation-entry -->
