---
id: project/policy/ux-message-cleanup
type: policy
scope: project
description: Automatic cleanup of Telegram message clutter for a clean UI.
---

# Ux Message Cleanup — Policy

## Rules

Track user input and feedback messages for automatic deletion to keep Telegram topics clean and focused on AI output.

**Message Categories**:

- **User Input**: Text messages, voice transcriptions, file notifications sent by user → deleted on next input
- **Feedback**: Confirmation messages ("✅ Sent to AI", "🎤 Transcribing...") → deleted on next feedback
- **Output**: AI response messages → NEVER deleted, edited in-place
- **Artifacts**: File uploads, result documents → NEVER deleted

**Cleanup Triggers**:

- `CleanupTrigger.NEXT_NOTICE`: Delete on next feedback message
- `CleanupTrigger.NEXT_INPUT`: Delete on next user input (currently unused - all use NEXT_NOTICE)
- `CleanupTrigger.TURN_COMPLETE`: Delete when AI finishes turn (future extension)
- `CleanupTrigger.MANUAL`: No automatic deletion

**Implementation**:

- Store message_id in `pending_deletions` table with session_id
- Query and delete all pending messages before sending new feedback
- Clear `pending_deletions` after successful deletion

## Rationale

Without cleanup, Telegram topics become cluttered with:

- Redundant user messages (visible in AI output anyway)
- Stale feedback ("Sending..." when already sent)
- Repeated confirmations creating visual noise

Clean topics keep focus on the AI conversation and make session history scannable.

## Scope

Applies to:

- All UI adapters (Telegram, future Slack/WhatsApp)
- User message handlers in input_handlers.py
- Feedback emission in adapter_client.py and ui_adapter.py
- Voice message transcription flows

Does NOT apply to:

- Transport adapters (Redis - no UI messages)
- API adapter (no persistent message history)
- MCP adapter (stdio-based, no message concepts)

## Enforcement

**Code patterns**:

- Use `AdapterClient.send_message(..., cleanup_trigger=CleanupTrigger.NEXT_NOTICE)` for feedback
- Call `AdapterClient.pre_handle_command(session, origin)` before processing user input
- Never use raw Telegram `reply_text` - always route through tracking APIs

**Testing**:

- Verify `pending_deletions` table populated when sending feedback
- Verify deletion occurs before next feedback (no duplicate confirmations visible)
- Verify output messages never appear in `pending_deletions`

## Exceptions

- **AI-to-AI sessions**: No feedback messages sent (listeners handle notifications instead)
- **Persistent artifacts**: Files uploaded by AI, result documents, logs → never tracked for deletion
- **Output messages**: Single persistent message per session, edited in-place → never deleted until session closes
