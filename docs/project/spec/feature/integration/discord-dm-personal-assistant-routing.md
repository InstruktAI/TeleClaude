---
description: Route an inbound Discord DM from a bound person to their DM-scoped personal-assistant
  session, and deliver the assistant's reply back to that DM channel.
visibility: internal
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
to the DM rather than to a guild forum thread.

The DM path is one policy of the shared inbound resolve-or-create seam; the guild path is
another. Both scope session resolution by channel through the same seam and persist the
channel binding on the session for outbound delivery — the DM policy keys on the DM channel
with the session's guild id unset.

## Canonical fields

### Use cases

#### UC-DM-SCOPED-RESOLUTION: A bound person's Discord DM resolves to their DM-scoped personal-assistant session, never a guild session

```
Given a person bound to a Discord account
And that person already has an open Discord session in a guild channel (a project forum thread or their team channel)
When the person sends a direct message to the bot
Then the shared inbound resolve-or-create seam binds the message to a session scoped to that DM channel, with the session's guild id unset
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
