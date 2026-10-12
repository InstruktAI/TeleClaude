---
description: Route an inbound Discord DM from a bound person to their DM-scoped personal-assistant
  session, and deliver the assistant's reply back to that DM channel.
visibility: internal
---

# Discord DM Personal-Assistant Routing — Spec

## Required reads

- @docs/local/spec/feature/identity/human-identity-resolution.md

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

<!-- planned-change:designated-channel-continuity -->

The DM path hands each direct message to the core conversation seam, keyed on the DM
channel; the guild path is a policy of the shared inbound resolve-or-create seam. Each
persists the channel binding on the session for outbound delivery — a DM session carries
the DM channel with its guild id unset.
<!-- change:designated-channel-continuity -->

The DM path hands each direct message to the core conversation seam, keyed on the DM
channel. Designated Team personal-assistant channels also reach that seam through
`local/projects/teleclaude/spec/feature/integration/discord-personal-assistant-channels`;
guild forum conversations use their independent session-resolution path. Each
persists the channel binding on the session for outbound delivery — a DM session carries
the DM channel with its guild id unset.

A direct message carrying audio, image or file attachments, with or without text,
reaches the seam as one turn of that DM conversation. Its attachments and any
accompanying text follow the once-only combined-input contract of
`local/projects/teleclaude/spec/feature/integration/discord-personal-assistant-channels`.
<!-- /planned-change:designated-channel-continuity -->

A direct message that is exactly the person's invitation token is an entry to
their personal assistant
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`). A
DM channel is never bound to a help-desk session: a desk identifier sent as a
direct message gets the neutral reply and leaves the DM with the personal
assistant.

Every computer receives each direct message, and the mesh master alone decides
where it goes; no other computer handles it.

## Canonical fields

### Use cases

#### UC-DM-SCOPED-RESOLUTION: A bound person's Discord DM resolves to their DM-scoped personal-assistant session, never a guild session

```
Given a person bound to a Discord account
And that person already has an open Discord session in a guild channel (a project forum thread or their team channel)
When the person sends a direct message to the bot
Then the conversation seam delivers the message to the DM channel's session, whose guild id is unset
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

#### UC-DM-HELP-DESK-ENTRY: A help desk's identifier sent as a DM enters no desk

```
Given a person bound to a Discord account whose DM channel reaches their personal assistant
When the person sends a help desk's entry identifier as a direct message
Then they receive the neutral reply and no desk session is created
And their next direct message reaches their personal-assistant session
```

<!-- planned:designated-channel-continuity -->

#### UC-DM-ATTACHMENT-INPUT: An attachment sent as a direct message reaches the DM's assistant

```
Scenario Outline: direct message through <modality>
  Given a bound person whose DM channel reaches their personal assistant
  When they send <modality> input as a direct message, with or without accompanying text
  Then the DM channel is resolved once to its personal-assistant session
  And each accepted attachment and any accompanying text reach that session once
  And the assistant's reply returns to that DM channel

  Examples:
    | modality |
    | audio    |
    | image    |
    | file     |
```

<!-- /planned:designated-channel-continuity -->
