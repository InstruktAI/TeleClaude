---
description: Local-first ownership of Discord interactions from their forum ancestry, with generation-safe exact-message components.
delivered_by:
  - enforce-local-discord-interaction-ownership
---

# Discord Interaction Ownership — Spec

## Required reads

@docs/project/policy/adapter-boundaries.md
@docs/project/spec/feature/reconciliation/fleet-cross-version-interop.md

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

## Known caveats

- Discord may deliver one application interaction to multiple concurrent gateway
  sessions. The ownership boundary therefore lives in the source forum's category,
  generation-specific component identity, and message-scoped handler registration,
  all evaluated before acknowledgement.
- Existing legacy launcher messages remain on their legacy component generation
  until their owning computer reconciles them. Upgraded computers do not register
  a legacy process-wide fallback, so they cannot interfere with those launchers.

## See Also

- docs/third-party/discord/interaction-dispatch-and-acknowledgement.md
