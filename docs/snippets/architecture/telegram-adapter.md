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
- Outputs: edited output messages, temporary feedback messages, topic creation/updates, registry heartbeats.

Primary flows
- Commands map to daemon events via AdapterClient and command mappers.
- Session topics are created per session and named with the computer prefix.
- Output is streamed by editing a single persistent message per session.
- Heartbeats update a shared registry topic for peer discovery.

Invariants
- Command registration is performed only by the master bot.
- BotCommand names include trailing spaces when published.
- Feedback and user input messages are deleted via pending_deletions rules.
- Unauthorized users are ignored based on whitelist.

Failure modes
- Missing topic threads trigger recovery and metadata repair before retry.
- Telegram API errors are logged and surfaced as adapter failures.
