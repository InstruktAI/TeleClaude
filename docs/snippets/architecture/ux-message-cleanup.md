---
id: teleclaude/architecture/ux-message-cleanup
type: architecture
scope: project
description: Message deletion tracking for clean Telegram UX (user input and feedback).
requires:
  - database.md
---

Purpose
- Keep Telegram topics clean by deleting transient messages at the right times.

Mechanism
- User input messages are queued for deletion on the next user input.
- Feedback messages are queued for deletion before new feedback is sent.
- Message IDs are persisted in session UX state for restart resilience.

Invariants
- Output messages are edited in place and never deleted.
- AI-to-AI sessions do not receive feedback messages.

Failure modes
- Missing UX state falls back to creating new feedback messages and re-seeding state.
