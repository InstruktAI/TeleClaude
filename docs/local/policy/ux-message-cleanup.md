---
description: 'Automatic cleanup of UiAdapter message clutter for a clean UI.'
visibility: 'public'
---

# Ux Message Cleanup — Policy

## Rules

Presentation owns message display lifetimes. Adapters execute the declared
cleanup of transient messages while retaining conversational content according
to `local/projects/teleclaude/spec/feature/presentation/conversation-message-retention`.

**Message Categories**:

- **User Input**: Discord conversation text follows
  `local/projects/teleclaude/spec/feature/presentation/conversation-message-retention`;
  other adapters retain next-input cleanup of text messages, voice transcriptions
  and user file notifications.
- **Source Recordings**: The consumed voice recording is removed after successful
  transcription; its completed text has its own conversation lifetime.

- **Feedback**: Confirmation messages ("✅ Sent to AI", "🎤 Transcribing...") → deleted on next feedback
- **Turn Controls**: Replaceable controls such as Discord `Listen here` → deleted on next input and recreated after the next completed output
- **Output**: AI response messages → NEVER deleted; edited in place on an `EditableUiAdapter`, sent once per finished turn on any other `UiAdapter`
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

- A pending cleanup entry remains retryable until its platform deletion succeeds,
  unless its owning lifetime policy withdraws that deletion. Withdrawal removes
  the cleanup intent while leaving the platform message intact.

## Rationale

A readable Discord conversation contains both the person's words and the
assistant's responses. An accepted transcript in source storage does not replace
the person's visible side of that conversation. Transient recording, status and
control cleanup removes completed interaction scaffolding without treating
conversation text as redundant feedback. Other adapters keep their established
display lifetimes.

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
- **Output messages**: On an `EditableUiAdapter`, one tracked message per output generation, edited in place; on any other `UiAdapter`, each finished turn sent once, with continuation messages for overflow → never deleted until session closes
