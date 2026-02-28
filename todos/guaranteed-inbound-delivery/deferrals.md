# Deferrals: guaranteed-inbound-delivery

These items were planned but not implemented in this build phase. They are explicitly deferred — not silently dropped.

---

## D1: Typing indicators in Discord and Telegram adapters

**From:** Tasks 2.1, 2.2

**What was planned:**

- Discord: call `await channel.typing()` after successful enqueue
- Telegram: call `await context.bot.send_chat_action(chat_id, ChatAction.TYPING)` after successful enqueue

**Why deferred:**
The adapter-boundaries policy states: "After successful enqueue, adapters show a platform-native typing indicator." The core queue plumbing is fully implemented and working. The typing indicator is a UX enhancement — it doesn't affect message durability or delivery guarantees.

Adding typing indicators requires refactoring the adapter enqueue path to call `inbound_queue_manager.enqueue()` directly (bypassing `process_message`), since the typing indicator must fire after the enqueue is confirmed. This is a separate, bounded adapter change with no dependency on the core queue implementation.

**Impact:** Users will not see a "typing..." indicator while their message is queued for delivery. Message delivery itself is unaffected.

**Scope for follow-up todo:**

- Refactor Discord `_handle_on_message()` to call `inbound_queue_manager.enqueue()` directly, then `await channel.typing()`
- Refactor Telegram `_handle_message()` similarly with `ChatAction.TYPING`

---

## D2: Voice message durable path

**From:** Tasks 2.1, 2.2

**What was planned:**

- If voice transcription fails (returns None), enqueue the message as `message_type='voice'` with `payload_json` containing CDN URL / file_id for later retry
- Discord: CDN URL + local file path in `payload_json`
- Telegram: Telegram `file_id` (permanent) in `payload_json`

**Why deferred:**
The current voice path still uses fast-path transcription only. If transcription fails, the message is dropped (as before). The inbound queue schema already includes `message_type='voice'` and `payload_json` columns to support this — the schema work is done.

The durable voice path requires a voice-type delivery handler in `deliver_inbound` that re-downloads and re-transcribes on retry, which is a non-trivial addition touching voice handling, CDN, and the Telegram/Discord file APIs.

**Impact:** Failed voice transcriptions continue to be silently dropped, as before this build. Text and file messages gain full durability.

**Scope for follow-up todo:**

- Extend `deliver_inbound` to handle `message_type='voice'` rows: re-download from CDN/file_id, re-transcribe, send text
- Update Discord `_handle_voice_attachment` to enqueue voice on transcription failure
- Update Telegram voice handler similarly

---

## D3: TUI status indicator for terminal input

**From:** Task 2.3

**What was planned:**
Add a TUI status indicator showing "message received" when terminal input is enqueued.

**Why deferred:**
Terminal input routes through `process_message` (now the enqueue boundary) — the durability guarantee is present. The TUI status indicator is a UX feature requiring investigation of the TUI rendering layer, which is out of scope for this core queue delivery feature.

**Impact:** Terminal users do not see a confirmation indicator. Their messages are still reliably queued and delivered.

**Scope for follow-up todo:**

- Identify the TUI event bus or notification mechanism
- Fire a "message enqueued" event after `process_message` returns from the terminal path
