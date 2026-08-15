---
description: Local-first ownership of Discord interactions in a multi-computer fleet, with owner-addressed components and explicit ownership for shared surfaces.
delivered_by:
  - enforce-local-discord-interaction-ownership
---

# Discord Interaction Ownership — Spec

## Required reads

@docs/project/policy/adapter-boundaries.md
@docs/project/spec/feature/reconciliation/fleet-cross-version-interop.md

## What it is

The contract that makes Discord input ownership structural in a multi-computer
fleet. An interaction addressed to a computer-owned Discord resource is consumed
and executed by that computer. Other computers may receive the provider event,
but they do not acknowledge it, translate it into a command, or produce any side
effect. Raw Discord payloads never cross the fleet transport.

Shared Discord surfaces have one explicit owning computer. Only after that owner
has accepted and normalized an interaction may it issue a typed command naming a
different target computer. Local resources therefore remain available without a
peer, while genuinely remote operations cross the fleet through the command
contract rather than through provider-event relay.

## Canonical fields

### Ownership rules

- Every computer-owned Discord artifact has one stable computer owner.
- Interactive components carry an owner-addressed identity that is distinct
  across computers and across incompatible component generations.
- Persistent component handlers are registered against the exact Discord message
  they serve. No process-wide fallback handler claims components from arbitrary
  messages.
- A daemon establishes local ownership before acknowledging an interaction.
- A foreign interaction is ignored without acknowledgement, command creation,
  state mutation, or user-visible response.
- An accepted interaction for a computer-owned resource becomes a local command
  and executes on the owning computer without fleet transport.
- A shared Discord surface has one declared owner. Cross-computer work originating
  there uses a typed, target-addressed command after normalization.
- Rolling deployment is safe: a peer that predates a component generation cannot
  claim that generation's interactions.

### Use cases

#### UC-DIO1: A project launcher executes on its owning computer

```gherkin
Given a human sees a session launcher in a project forum owned by one computer
When the human selects an agent
Then the owning computer acknowledges the interaction
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

#### UC-DIO5: Shared surfaces use explicit command routing

```gherkin
Given a human acts through a Discord surface whose ownership is shared across the fleet
When the designated owner accepts an action targeting another computer
Then it normalizes the action into a typed command naming that computer
And only the target computer executes the command
And the raw Discord interaction is not relayed
```

## Known caveats

- Discord may deliver one application interaction to multiple concurrent gateway
  sessions. The ownership boundary therefore lives in component identity and
  message-scoped handler registration, before acknowledgement.
- Existing legacy launcher messages remain on their legacy component generation
  until their owning computer reconciles them. Upgraded computers do not register
  a legacy process-wide fallback, so they cannot interfere with those launchers.

## See Also

- docs/third-party/discord/interaction-dispatch-and-acknowledgement.md
