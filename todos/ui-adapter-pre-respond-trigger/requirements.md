# Requirements: ui-adapter-pre-respond-trigger

## Goal

When a user sends a message to a session via a UI adapter, immediately send a platform-specific "typing" indicator so the user gets visual feedback that the system is processing their input. Currently, after the user sends a message there is no acknowledgment until either a feedback message arrives or the AI starts responding — a noticeable gap.

## Scope

### In scope

- **UiAdapter base**: new `send_typing_indicator(session)` async method (no-op default).
- **TelegramAdapter**: override using `bot.send_chat_action(chat_id, action=TYPING, message_thread_id=topic_id)`.
- **DiscordAdapter**: override using `channel.trigger_typing()` on the session thread.
- **Integration point**: call from `UiAdapter._dispatch_command()` after `pre_handle_command()`, before invoking the command handler.

### Out of scope

- Continuous/repeating typing indicators during long AI processing (follow-up todo if needed).
- Web/API adapter typing events (no persistent connection model yet).
- Redis/MCP transport adapters (non-UI, no typing concept).
- Typing indicators for AI-to-AI sessions (no human observing).

## Success Criteria

- [ ] Telegram: user sees "typing..." bubble in the forum topic within ~200ms of sending a message.
- [ ] Discord: user sees typing indicator in the session thread within ~200ms of sending a message.
- [ ] Typing indicator failure never blocks or delays message processing (fire-and-forget with error suppression).
- [ ] No typing indicator sent for headless/AI-to-AI sessions (`lifecycle_status == "headless"`).
- [ ] Existing tests pass; new unit test covers the call site.

## Constraints

- Must not add latency to the user input → AI processing path (fire-and-forget, not awaited on the critical path, or at minimum wrapped in error suppression).
- Must reuse existing session metadata patterns for resolving platform channel/thread IDs.
- Telegram typing status auto-clears after 5 seconds or when the bot sends a message — no explicit cancel needed.
- Discord typing indicator lasts ~10 seconds — same pattern.

## Risks

- Telegram rate limits on `sendChatAction` could cause `RetryAfter` exceptions if called excessively. Mitigation: fire-and-forget with logged warning on failure; no retry.
- Discord `trigger_typing()` requires the client to have channel access. Mitigation: guard with channel existence check and suppress errors.
