# Requirements: typing-indicators-adapters

## Problem

After a user sends a message, there is no visible feedback until the agent begins responding. The inbound queue introduces a gap between message receipt (adapter enqueue) and delivery (worker drains to tmux). Users should see a platform-native "typing..." indicator immediately upon enqueue to signal "message received, processing."

## Success Criteria

1. Typing indicator appears in the originating platform within 100ms of successful `InboundQueueManager.enqueue()`.
2. No typing indicator fires on duplicate messages (enqueue returns `None`).
3. Only the adapter matching the message's `origin` shows the typing indicator — other adapters are not triggered.
4. Typing indicator failures are logged but never block enqueue or delivery.
5. All three UI adapters (Discord, Telegram, WhatsApp) are wired.
6. Adapter-boundaries policy compliance: the typing indicator is the only adapter-side side effect of inbound message receipt.

## Functional Requirements

### R1: Wire typing callback into InboundQueueManager

The `InboundQueueManager` already accepts an optional `typing_callback: TypingCallback` (signature: `async (session_id: str, origin: str) -> None`). The callback is invoked inside `enqueue()` after successful DB insert, before worker dispatch. Currently it is never provided.

**Requirement:** `CommandService.__init__` must pass a `typing_callback` to `init_inbound_queue_manager()` that resolves `session_id` → `Session`, determines the origin adapter, and calls `send_typing_indicator(session)` on it.

### R2: Implement the typing callback function

The callback must:
- Accept `(session_id, origin)`.
- Load the `Session` from the database.
- Resolve which UI adapter matches `origin` (e.g., `"telegram"` → `TelegramAdapter`, `"discord"` → `DiscordAdapter`).
- Call `adapter.send_typing_indicator(session)` on the matching adapter only.
- Catch and log all exceptions without re-raising (fire-and-forget).

The callback is defined in `command_handlers.py` alongside `deliver_inbound`, keeping queue-related handler logic in one place.

### R3: Origin-to-adapter routing

The `origin` string from `enqueue()` maps to an adapter type. The `AdapterClient` holds registered adapters keyed by type string. The callback must use the `AdapterClient` to find the correct UI adapter.

Origin values use the `InputOrigin` enum. The mapping:
- `InputOrigin.TELEGRAM` (`"telegram"`) → `"telegram"` adapter
- `InputOrigin.DISCORD` (`"discord"`) → `"discord"` adapter
- `InputOrigin.WHATSAPP` (`"whatsapp"`) → `"whatsapp"` adapter
- Other origins (`api`, `terminal`, `redis`, `hook`) → no typing indicator (not user-facing platforms)

### R4: No refactoring of adapter message handling

The existing flow (`_handle_on_message` → `_dispatch_command` → `process_message` → `enqueue`) remains unchanged. The typing indicator is injected via the callback mechanism already built into `InboundQueueManager.enqueue()`. No adapter code changes are needed beyond wiring the callback.

### R5: Tests

- Unit test: verify `send_typing_indicator` is called on the correct adapter after successful enqueue.
- Unit test: verify `send_typing_indicator` is NOT called when enqueue returns `None` (duplicate).
- Unit test: verify typing callback exceptions do not propagate.
- Unit test: verify only the origin-matching adapter receives the typing call.

## Non-Requirements

- No changes to the existing `_dispatch_command` typing indicator (that one fires during command execution, serving a different purpose — it signals "agent is thinking").
- No changes to adapter message handlers (`_handle_on_message`, `_handle_private_text`).
- No adapter-boundaries doc update needed — rule 19 already documents this behavior.

## Dependencies

- `guaranteed-inbound-delivery` (delivered) — provides the `InboundQueueManager` and `typing_callback` hook.
