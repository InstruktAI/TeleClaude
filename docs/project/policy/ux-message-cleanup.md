---
id: policy/ux-message-cleanup
type: policy
scope: project
description: Automatic cleanup of Telegram message clutter for a clean UI.
---

# Ux Message Cleanup — Policy

## Rule

- Track user input and feedback messages for deletion to keep Telegram topics clean.
- Use `pending_deletions` with `deletion_type` to distinguish user input vs feedback.
- Never delete persistent AI results or file artifacts.
- Use tracking APIs instead of raw `reply_text`.

- Prevents clutter, keeps session context readable, and avoids message spam.

- Applies to all Telegram UI adapter flows and message responses.

- Verify cleanup flows delete user_input messages on next input.
- Verify feedback cleanup runs before sending new feedback.
- Audit usage of `db.add_pending_deletion` in adapter responses.

- Persistent AI results and file artifacts are never deleted.

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.
