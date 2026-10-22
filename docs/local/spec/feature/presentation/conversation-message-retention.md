---
description: Display lifetime of human conversation text and completed speech transcripts
  on Discord, distinct from transient recording, feedback and control cleanup.
---

# Conversation Message Retention — Spec

## What it is

The presentation context owns the display lifetime of human conversation text
on Discord. Message retention follows the conversational continuity rationale
in `local/projects/teleclaude/policy/ux-message-cleanup`.

## Canonical fields

- Human text input and completed speech transcripts remain readable in their
  Discord conversation across later inputs and assistant responses.
- This retention applies to existing visible conversation messages as well as
  newly delivered messages.
- Consumed source recordings, transient feedback and replaceable turn controls
  keep their distinct cleanup lifetimes under
  `local/projects/teleclaude/policy/ux-message-cleanup`.
- Other adapters retain their existing cleanup policy. Native transcript
  acceptance and source truth remain owned by
  `local/projects/teleclaude/spec/domain/agent_runtime`; this contract changes
  the lifetime of the Discord display, not the accepted conversation.
