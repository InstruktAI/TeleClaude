---
description: Designated Discord Team assistant channels carry every conversation input
  to the core's continuing-conversation resolver.
---

# Discord Personal Assistant Channels — Spec

## What it is

A person's designated private Team channel is their continuing assistant entry
point. Discord supplies the established channel designation, verified sender
identity and reply destination to the core conversation resolver. The core owns
endpoint resolution, retained session selection, adoption and revival
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).

Discord's Team provisioning association establishes which person a channel
serves. Input is resolved against that association and the sender's authoritative
identity (`local/projects/teleclaude/spec/feature/identity/human-identity-resolution`).
The adapter carries that association rather than deriving assistant eligibility
from a session's working folder or the provider object's class.

Text and attachment-only messages carry the same channel designation. Replies
reach the originating Team channel with its guild metadata preserved. DMs retain
their distinct channel-scoped bindings
(`local/projects/teleclaude/spec/feature/integration/discord-dm-personal-assistant-routing`).
Forum posts retain their independent session selection. A transport that delivers
to an explicitly focused session carries that selection and leaves its lifecycle
classification with the core
(`local/projects/teleclaude/spec/feature/integration/discord-personal-voice-conversation`).

Discord Team assistant channels are shared guild surfaces received by every
connected computer. Their input reaches the core as a shared conversation under
the master-routing contract in
`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`.
Provisioning ownership and conversation-input ownership are separate facts:
resolving an existing channel on a peer supplies no authority to deliver its input.

A message containing attachments and accompanying text resolves its designated
channel once. Each accepted attachment and the accompanying text reach that
conversation once, including at first entry and after revival. With multiple
attachments the accompanying text appears once across the delivered material.
Audio input delivers its transcription and accompanying message text under the
same contract. The existing input-delivery boundary owns occurrence identity
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).

## Canonical fields

### Use cases

#### UC-DPAC-1: Team text enters the continuing assistant

```gherkin
Given Discord has an established private Team channel for a registered person
When that person sends text in the channel
Then Discord hands its channel designation and verified identity to core conversation resolution
And the assistant response returns to that Team channel
```

#### UC-DPAC-2: Attachment-only input carries the same designation

```gherkin
Scenario Outline: Team input through <modality>
  Given a registered person has a designated Team assistant channel
  When they send <modality> input with no text body
  Then Discord supplies the same conversation designation as for text input
  And the accepted input reaches the channel's continuing session
  And its response returns to that channel

  Examples:
    | modality |
    | audio    |
    | image    |
    | file     |
```

#### UC-DPAC-3: A forum post stays independently selected

```gherkin
Given a person has a Team assistant channel and an independent project-forum session
When they post to the forum session
Then Discord delivers to that independently selected session
And it supplies no Team assistant designation for that post
```

#### UC-DPAC-4: Sender identity agrees with the channel association

```gherkin
Given a designated Team channel serves one registered person
When an incoming message resolves to another person or no registered person
Then the message does not enter the designated person's assistant
And the mismatch is reported through the existing identity and routing refusal contract
```

#### UC-DPAC-5: Shared Team input reaches one resolver

```gherkin
Scenario Outline: shared Team input through <modality>
  Given multiple computers are connected to the guild containing a Team assistant channel
  And one live computer is the mesh master and runs Discord
  When the channel receives <modality> input from its person
  Then Discord passes it through shared conversation ownership
  And exactly one accepted input reaches the master's continuing conversation
  And non-master receivers start no competing session and send no independent assistant reply

  Examples:
    | modality |
    | text     |
    | audio    |
    | image    |
    | file     |
```

#### UC-DPAC-6: Combined attachment and text input is delivered once

```gherkin
Scenario Outline: combined message at <state>
  Given a designated Team assistant channel has <state>
  When its person sends <attachments> with accompanying text
  Then the channel is resolved once to its continuing conversation
  And every accepted attachment reaches that conversation once
  And accompanying text reaches it once across the delivered material
  And attachment-derived content and accompanying text are both retained

  Examples:
    | state                  | attachments    |
    | no session             | an image       |
    | an open session        | an image       |
    | a closed session       | an image       |
    | no session             | multiple files |
    | an open session        | multiple files |
    | a closed session       | multiple files |
    | no session             | audio          |
    | an open session        | audio          |
    | a closed session       | audio          |
```
