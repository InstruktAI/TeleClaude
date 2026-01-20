---
id: architecture/telegram-adapter
description: Telegram UI adapter for commands, topics, messaging, and peer heartbeat.
type: architecture
scope: project
requires:
  - adapter-client.md
  - ux-message-cleanup.md
  - session-lifecycle.md
---

# Telegram Adapter

## Purpose
- Provide the primary UI for TeleClaude via Telegram supergroup topics and commands.

## Inputs/Outputs
- Inputs: Telegram updates (commands, messages, callbacks, files, voice messages).
- Outputs: TeleClaude events to the daemon, topic/channel operations, message edits and deletions.

## Invariants
- Requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_SUPERGROUP_ID` to start.
- User access is restricted to a configured whitelist.
- Message length limit is 4096 characters; output is chunked/edited accordingly.
- Pre-handler deletes pending ephemerals before processing user input.

## Primary Flows
- Start: initialize bot, optionally register commands (master only), restore registry state, start heartbeat.
- Command handling: map Telegram commands to TeleClaude events and session operations.
- Messaging: send/edit/delete and output updates; track ephemerals for cleanup.

## Failure Modes
- Missing supergroup or permissions are logged and prevent normal operation.
- Topic creation is guarded with locks to avoid duplicate topics per session.
