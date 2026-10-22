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

### Use cases

#### UC-DIO1: A person starts a session from a project forum

```gherkin
Given a person opens a session launcher in a project's forum
When they select an agent
Then a new session starts for that project
```

#### UC-DIO2: A foreign computer cannot consume the interaction

#### UC-DIO3: Version skew cannot transfer component ownership

#### UC-DIO4: Restart restores only locally scoped component handling

#### UC-DIO5: One computer publishes the shared command tree

#### UC-DIO6: A person cancels a session without a false no-session response

```gherkin
Given a person uses a supported cancel command in a project forum
And the session is active on a different computer from a connected peer
When the command is processed
Then the session's owner handles the cancellation and returns its result
And the person receives no false no-session response from the other computer
```

#### UC-DIO7: Shared-surface command feedback has one owner

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
