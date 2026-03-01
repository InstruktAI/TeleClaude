# Demo: typing-indicators-adapters

## Medium

Live platforms (Telegram, Discord) + unit test output.

## What the user observes

1. **Telegram**: Send a message to the bot. A "typing..." bubble appears within ~100ms — before the agent starts responding. The indicator confirms "your message was received and queued."

2. **Discord**: Send a message in a managed thread. The bot's "typing..." indicator appears immediately after the message is enqueued, before the agent processes it.

3. **Duplicate resilience**: Send the same message twice rapidly (e.g., Telegram retry). Only one typing indicator fires. The second enqueue is deduplicated silently.

4. **Non-UI origins unaffected**: Messages from API or terminal origins produce no typing indicator — no adapter interaction occurs.

## Validation commands

```bash
# Run unit tests for the typing callback
pytest tests/unit/test_typing_indicator_callback.py -v

# Run inbound queue integration tests
pytest tests/unit/test_inbound_queue.py -v -k typing

# Full test suite
pytest tests/ -x --timeout=30
```

## What changed (builder refines)

- `command_handlers.py`: new `typing_indicator_callback` function
- `command_service.py`: wired callback into `init_inbound_queue_manager`
- New test file for callback unit tests
