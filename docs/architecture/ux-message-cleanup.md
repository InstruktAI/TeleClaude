---
description: Message deletion tracking for clean Telegram UX (user input and feedback).
id: teleclaude/architecture/ux-message-cleanup
scope: project
type: architecture
---

# Ux Message Cleanup — Architecture

## Purpose

- @docs/architecture/database

- Keep Telegram topics clean by deleting transient messages at the right times.

- Inputs: incoming user messages, feedback messages, and session UX state.
- Outputs: deletions for transient messages plus persistent output messages that are edited in place.

- User input cleanup: before handling new input, delete all pending user_input messages for the session.
- Feedback cleanup: before sending new feedback, delete all pending feedback messages for the session.
- Tracking: add message IDs to pending deletions with a deletion_type of user_input or feedback.

- Output messages are edited in place and never deleted.
- Persistent messages (AI results, file artifacts) are never deleted.
- AI-to-AI sessions do not receive feedback messages.
- UI responses avoid reply_text to ensure deletions are tracked.

- Missing UX state falls back to sending new feedback without cleanup and re-seeding state.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
