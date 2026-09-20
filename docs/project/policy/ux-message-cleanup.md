---
description: 'Automatic cleanup of UiAdapter message clutter for a clean UI.'
visibility: 'public'
---

# Ux Message Cleanup — Policy

## Rules

Track user input and feedback messages for automatic deletion to keep UiAdapter topics clean and focused on AI output.

**Message Categories**:

- **User Input**: Text messages, voice transcriptions, file notifications sent by user → deleted on next input
- **Feedback**: Confirmation messages ("✅ Sent to AI", "🎤 Transcribing...") → deleted on next feedback
- **Turn Controls**: Replaceable controls such as Discord `Listen here` → deleted on next input and recreated after the next completed output
- **Output**: AI response messages → NEVER deleted, edited in-place
- **Artifacts**: File uploads, result documents → NEVER deleted

**Cleanup Triggers**:

- `CleanupTrigger.NEXT_NOTICE`: Delete on next feedback message
- `CleanupTrigger.NEXT_INPUT`: Delete on next user input (currently unused - all use NEXT_NOTICE)
- `CleanupTrigger.TURN_COMPLETE`: Delete when AI finishes turn (future extension)
- `CleanupTrigger.MANUAL`: No automatic deletion

**Implementation**:

- Store message_id in `pending_message_deletions` with session_id and the owning adapter key; platform identifiers never cross adapter boundaries
- The shared `UiAdapter` input lifecycle deletes tracked next-input messages; adapters add only their platform-specific state reconciliation after that shared operation
- Only adapters that declare message-deletion capability create pending rows; a non-deleting adapter never accumulates retry work it cannot complete
- Query and delete all pending feedback before sending new feedback
- Remove each `pending_message_deletions` entry only after its platform deletion succeeds so a transient failure remains retryable

## Rationale

Without cleanup, UiAdapter topics become cluttered with:

- Redundant user messages (visible in AI output anyway)
- Stale feedback ("Sending..." when already sent)
- Repeated confirmations creating visual noise

Clean topics keep focus on the AI conversation and make session history scannable.

## Scope

Applies to:

- All UI adapters (Discord, Telegram, future Slack/WhatsApp)
- User message handlers in input_handlers.py
- Feedback emission in adapter_client.py and ui_adapter.py
- Voice message transcription flows

Does NOT apply to:

- API adapter (no persistent message history)
- Tool-call interfaces (no persistent message concepts)

## Enforcement

**Code patterns**:

- Use `AdapterClient.send_message(..., cleanup_trigger=CleanupTrigger.NEXT_NOTICE)` for feedback
- Call `AdapterClient.pre_handle_command(session, origin)` before processing user input
- Use the shared `UiAdapter` pre/post handlers for next-input tracking; adapters must not duplicate the deletion loop
- Never use raw UiAdapter `reply_text` - always route through tracking APIs

**Testing**:

- Verify `pending_message_deletions` table populated when sending feedback
- Verify deletion occurs before next feedback (no duplicate confirmations visible)
- Verify output messages never appear in `pending_message_deletions`

## Exceptions

- **AI-to-AI sessions**: No feedback messages sent (listeners handle notifications instead)
- **Persistent artifacts**: Files uploaded by AI, result documents, logs → never tracked for deletion
- **Output messages**: Single persistent message per session, edited in-place → never deleted until session closes
