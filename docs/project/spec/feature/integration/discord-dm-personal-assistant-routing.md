---
description: "Route an inbound Discord DM from a bound person to their DM-scoped personal-assistant session, and deliver the assistant's reply back to that DM channel."
visibility: 'internal'
delivered_by: ['discord-personal-assistant-routing-broken']
---

# Discord DM Personal-Assistant Routing — Spec

## Required reads

- @docs/project/spec/feature/identity/human-identity-resolution.md

## What it is

A bound person reaches their personal assistant by sending a direct message to the
Discord bot. The DM surface is the personal assistant: the adapter resolves the sender to
their configured identity, binds the DM to a **DM-scoped** personal-assistant session in
the person's personal workspace, and delivers the assistant's output back to that same DM
channel.

The binding is scoped to the DM channel, not to the person. A person is an active operator
who also holds guild sessions — project-forum threads, their private team channel, launcher
sessions — and every one of those carries the same Discord user id. Personal-assistant
routing therefore keys on the DM channel that the message arrived on, so a direct message
is never absorbed into an unrelated guild session, and the assistant's reply is delivered
to the DM rather than to a guild forum thread. This mirrors the guild message path, which
already scopes session resolution by channel and persists the channel binding on the
session for outbound delivery.

## Canonical fields

### Use cases

#### UC-DM-SCOPED-RESOLUTION: A bound person's Discord DM resolves to their DM-scoped personal-assistant session, never a guild session

```
Given a person bound to a Discord account
And that person already has an open Discord session in a guild channel (a project forum thread or their team channel)
When the person sends a direct message to the bot
Then the message is handled by the personal-assistant DM path
And it resolves to a personal-assistant session scoped to that DM channel
And it does not resolve to the pre-existing guild session
```

#### UC-DM-SESSION-CREATE-AND-REUSE: A bound person's first DM creates a DM-bound personal-assistant session that subsequent DMs reuse

```
Given a bound person who has no personal-assistant session for their DM channel yet
When the person sends a direct message to the bot
Then a new personal-workspace session is created for that person
And the session is bound to the originating DM channel
And a subsequent direct message from the same person resolves to that same session rather than creating another
```

#### UC-DM-REPLY-DELIVERY: The personal assistant's reply is delivered to the originating Discord DM channel

```
Given a personal-assistant session bound to a Discord DM channel
When the assistant produces output for that session
Then the output destination resolves to the originating DM channel
And no guild forum thread is created for the session
```
