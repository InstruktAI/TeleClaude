---
description: Person invitations issue and rotate on the master and return links to its canonical public conversation endpoints wherever the administrator invokes the command.
delivered_by:
  - master-conversation-entry
---

# Person Invitations — Spec

## What it is

An administrator can invite a registered person from any computer. The invitation
operation executes on the unique master: person validation, token issuance or
rotation, public endpoint resolution and optional email delivery use that owner's
state. The result returns to the caller through the existing computer-addressed
execution contract
(`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).

The invocation surface is `telec config person invite <person>`. With no explicit
computer, it resolves the master automatically. An explicit computer selection
must name that owner; a request reaching a different computer is refused with
the owning destination before changing invitation state. Caller clearance is
evaluated on the owner under the existing configuration authorization contract.
Owner resolution supplies an explicit destination to the existing command relay
before execution; the generic relay does not select invitation ownership.

Every returned link names that master's public provider endpoint. The issuing
store is the one redemption consults. A caller's local bot credential is never a
substitute for the master, and bot credentials remain on their owning computer
(`sdlc/policy/security-awareness`). An unavailable or ambiguous master leaves
invitation state unchanged and returns a concrete failure. A person absent from
the master's registry receives the existing person-validation refusal.

Email delivery remains optional: failure to email is reported alongside any
generated links, which remain available to the caller. A configured provider
whose endpoint cannot be resolved is reported as unavailable for the invitation;
other generated links may still be returned. Resending rotates the person's
invitation through the same owning store. Initialization alone issues no invite.

<!-- planned-change:telegram-bot-retirement -->

Existing invitations on the master retain their state through activation.
Secondary-bot invitations and their records are accounted for by
`local/projects/teleclaude/procedure/conversation-entry-cutover`; they establish
no alternative live issuer. Provider account binding and conversation selection
belong to identity and agent runtime, respectively.
<!-- change:telegram-bot-retirement -->

Existing invitations on the master retain their state through activation. An
invitation issued elsewhere establishes no alternative live issuer. Provider
account binding and conversation selection belong to identity and agent
runtime, respectively.
<!-- /planned-change:telegram-bot-retirement -->

## Canonical fields

### Use cases

#### UC-PI1: An invitation requested from a peer uses the master's endpoints

```gherkin
Given a registered person exists on the unique master
And an administrator invokes person invite on another computer
When the invitation succeeds
Then the master issues the token in the store used for redemption
And the returned links name the master's configured public endpoints
And the caller's local invitation store and bot credentials are not used as substitutes
```

#### UC-PI2: Issuance and redemption agree

```gherkin
Given a person received a Telegram invitation generated through the master
When they redeem it at the bot named by its link
Then the invitation resolves to that person from the issuing store
And the account-binding result is handed to the master's conversation entry
```

#### UC-PI3: Missing ownership cannot rotate an invitation locally

```gherkin
Given no unique available master can execute the invitation
When an administrator requests an invite from a peer
Then the command reports the ownership failure
And no computer issues or rotates a replacement token locally
And no invitation email is sent
```

#### UC-PI4: Explicitly addressing a non-owner is refused

```gherkin
Given an administrator explicitly addresses person invite to a non-master
When the request is evaluated
Then it is refused with the authoritative destination or its unavailability
And the non-owner changes no invitation state
```

#### UC-PI5: Optional email failure preserves generated links

```gherkin
Given the master issued an invitation with usable public links
When its email delivery is unavailable or fails
Then the caller receives the generated links and the email outcome
And the command claims no successful email delivery
```

#### UC-PI6: Resending uses the same authority

```gherkin
Given a person's current invitation was issued by the master
When an administrator requests a resend from another computer
Then rotation occurs in the master's invitation store
And redemption follows the replacement invitation rather than the old one
```
