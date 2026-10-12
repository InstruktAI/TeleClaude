---
description: Local-first ownership of Discord interactions from their forum ancestry,
  with generation-safe exact-message components.
---

# Discord Interaction Ownership — Spec

## Required reads

@docs/local/policy/adapter-boundaries.md
@docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md

## What it is

The contract that makes Discord input ownership structural in a multi-computer
fleet. A project interaction's source hierarchy identifies its owner before any
acknowledgement: the interaction belongs to a thread or message in a project
forum, and that forum belongs to one computer's project category. The owning
computer resolves the forum through its local project map and executes locally.
Other computers may receive the provider event, but they do not acknowledge it,
translate it into a command, or produce any side effect. Raw Discord payloads
never cross the fleet transport.

## Canonical fields

### Ownership rules

- A project forum derives its computer owner from its parent project category
  and its project from that computer's local forum map.
- Interaction channel, message, forum, and category identity may be inspected or
  resolved without acknowledging the interaction. Failure to resolve ownership
  fails closed.
- Interactive components carry a generation-specific identity that is distinct
  from incompatible legacy component generations.
- Persistent component handlers are registered against the exact Discord message
  they serve. No process-wide fallback handler claims components from arbitrary
  messages.
- A daemon establishes local ownership before acknowledging an interaction.
- A foreign interaction is ignored without acknowledgement, command creation,
  state mutation, or user-visible response.
- An accepted interaction for a computer-owned project resource becomes a local
  command and executes on the owning computer without fleet transport.
- Rolling deployment is safe: a peer that predates a component generation cannot
  claim that generation's interactions.

<!-- planned:master-conversation-entry -->

### Shared application publication and command handling

The unique master publishes the shared application's guild command tree.
Other computers register their local handlers without publishing competing
provider definitions. Publication ownership is separate from execution:
computer-owned project interactions still execute on their own computer
(`general/principle/trust-and-guardrails`).

Slash-command ownership is established from the addressed surface before any
acknowledgement, including a negative or ephemeral response. A project forum's
owner handles its supported commands; shared conversation surfaces belong to
the master. A receiver that cannot establish ownership stays silent. Command
support and caller authorization retain their existing contracts. In particular,
source ownership is checked before `/cancel` answers that no active session exists.

<!-- /planned:master-conversation-entry -->

### Use cases

#### UC-DIO1: A project launcher executes on its owning computer

```gherkin
Given a human sees a session launcher in a project forum beneath one computer's project category
When the human selects an agent
Then the computer matching the forum's parent category acknowledges the interaction
And resolves the project from its local forum map
And creates the session locally for that project
And no other computer participates in executing the launch
```

#### UC-DIO2: A foreign computer cannot consume the interaction

```gherkin
Given multiple computers are connected to Discord through the same application
And a human activates a component belonging to another computer
When a foreign computer receives the provider event
Then it does not acknowledge the interaction
And it creates no command or state change
And it sends no response to the human
```

#### UC-DIO3: Version skew cannot transfer component ownership

```gherkin
Given one computer exposes an owner-addressed component generation
And another live computer runs a version that predates that generation
When a human activates the component
Then the older computer does not recognize or claim it
And the owning computer remains able to acknowledge and execute it
```

#### UC-DIO4: Restart restores only locally scoped component handling

```gherkin
Given an owning computer restarts while its Discord launcher message still exists
When its Discord adapter restores persistent interaction handling
Then it attaches handling to that exact launcher message
And it does not install a process-wide handler for matching components elsewhere
```

<!-- planned:master-conversation-entry -->

#### UC-DIO5: One computer publishes the shared command tree

```gherkin
Given multiple computers connect as one Discord application in a guild
And the fleet establishes one master
When their adapters start or reconnect
Then only the master publishes the application's guild command tree
And each computer can register the handlers for its own resources
```

#### UC-DIO6: A foreign cancel receiver stays silent

```gherkin
Given a human invokes a supported cancel command in one computer's project forum
And another connected computer has no matching local session
When both receive the interaction
Then only the forum owner acknowledges and handles the command
And the foreign receiver sends no no-session response
```

#### UC-DIO7: Shared-surface command feedback has one owner

```gherkin
Given a slash-command interaction occurs on a shared conversational surface
And the fleet establishes one master
When multiple computers receive that interaction
Then the master alone applies the command's supported behavior and emits its response
And every non-master remains silent even when its local lookup has no session
```

<!-- /planned:master-conversation-entry -->

## Known caveats

<!-- planned-change:master-conversation-entry -->

- Slash-command publication runs on every connected daemon. The cancel handler
  can acknowledge a foreign interaction with a no-session response before
  establishing source ownership.

<!-- change:master-conversation-entry -->

<!-- /planned-change:master-conversation-entry -->

- Discord may deliver one application interaction to multiple concurrent gateway
  sessions. The ownership boundary therefore lives in the source forum's category,
  generation-specific component identity, and message-scoped handler registration,
  all evaluated before acknowledgement.
- Existing legacy launcher messages remain on their legacy component generation
  until their owning computer reconciles them. Upgraded computers do not register
  a legacy process-wide fallback, so they cannot interfere with those launchers.

## See Also

- docs/third-party/discord/interaction-dispatch-and-acknowledgement.md
