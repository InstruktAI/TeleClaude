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

#### UC-DPAC-1: A person can use their assistant through a private Team channel

```gherkin
Scenario Outline: Continue the conversation with <input>
  Given a registered person has a designated Team assistant channel
  When they send <input> through that channel
  Then it reaches their continuing assistant conversation
  And the response returns to that channel

  Examples:
    | input                 |
    | text                  |
    | audio without text    |
    | an image without text |
    | a file without text   |
```

#### UC-DPAC-2: Attachment-only input carries the same designation

#### UC-DPAC-3: A forum post stays independently selected

#### UC-DPAC-4: Sender identity agrees with the channel association

#### UC-DPAC-5: Shared Team input reaches one resolver

#### UC-DPAC-6: A person can send attachments with text in one Team message

```gherkin
Scenario: Send attachments and text together
  Given a person has a designated Team assistant channel
  When they send one or more attachments with accompanying text
  Then each accepted attachment and the text reach the same conversation once
  And the conversation retains both the attachment-derived content and the text
```
