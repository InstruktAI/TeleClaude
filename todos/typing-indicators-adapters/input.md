# Input: typing-indicators-adapters

## Problem

Users do not see a "typing..." indicator when their message is being enqueued and delivered. After the core inbound queue is implemented, the gap between message receipt (adapter journaling) and delivery (queue worker drains) may be seconds under load. The user should know their message was received.

This is a deferred enhancement from the guaranteed-inbound-delivery build phase.

## Scope

Implement typing indicators in Discord and Telegram adapters after successful message enqueue:

- **Discord**: Call `await channel.typing()` context manager after successful `inbound_queue_manager.enqueue()`.
- **Telegram**: Call `await context.bot.send_chat_action(chat_id, ChatAction.TYPING)` after successful enqueue.

The typing indicator fires immediately when the adapter journals the message, signaling "I received your message, it's safe."

## Deliverables

1. Refactor Discord `_handle_on_message()` to call `inbound_queue_manager.enqueue()` directly instead of via `process_message` command dispatch, then trigger typing indicator.
2. Refactor Telegram `_handle_message()` similarly with `ChatAction.TYPING`.
3. Update adapter-boundaries.md to document the enqueue boundary and typing indicator signal.
4. Tests: verify typing indicator is called after successful enqueue; verify it's not called on duplicate messages.

## Definition of Done

- Typing indicator appears in Discord and Telegram within 100ms of successful enqueue.
- No duplicate typing indicators on message retries (only on first enqueue).
- Tests pass; all adapters tested in isolation.
