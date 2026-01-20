---
id: teleclaude/architecture/telegram-adapter
type: architecture
scope: project
description: Telegram UI adapter that maps topics to sessions and enforces UX cleanup rules.
requires:
  - ../architecture/ux-message-cleanup.md
  - ../architecture/session-lifecycle.md
---

Purpose
- Provide the human-facing Telegram interface for sessions, commands, and streaming output.

Inputs/Outputs
- Inputs: Telegram commands, messages, file uploads, voice messages.
- Outputs: edited output messages, feedback messages, topic creation/updates, registry heartbeats.

Primary flows
- Commands map to daemon events via AdapterClient.
- Session topics are created per session and named with the computer prefix.
- Output is streamed by editing a single persistent message per session.
- Heartbeats update a shared registry topic for peer discovery.

Invariants
- Command registration is performed only by the master bot.
- Command names must follow the trailing-space policy when published.
- Feedback messages are temporary and cleaned up before sending new feedback.
- User input messages are deleted on the next user input.

Failure modes
- Missing topic threads trigger recovery and metadata repair before retry.
- Unauthorized users are ignored based on the whitelist.
