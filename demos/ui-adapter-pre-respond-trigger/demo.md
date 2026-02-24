# Demo: ui-adapter-pre-respond-trigger

## Demonstration Not Applicable

This feature adds typing indicators to UI adapters (Telegram and Discord) when users send messages. The typing indicator is a visual element in the UI platforms that cannot be demonstrated via executable code blocks.

**Why this cannot be demonstrated:**

1. **UI-only feature**: Typing indicators are visual feedback elements in Telegram/Discord clients that show when the bot is "typing".
2. **Requires live platform interaction**: The feature requires sending a message through Telegram or Discord to trigger, and the indicator only displays in the native client UI.
3. **Fire-and-forget pattern**: The indicator is sent asynchronously and doesn't produce observable output in logs or files that can be captured in a demo.

**Verification method:**

The feature has been verified through:

- Unit tests in `tests/unit/test_ui_adapter.py::TestTypingIndicator` covering:
  - Typing indicator is called for normal sessions
  - Typing indicator is skipped for headless sessions
  - Handler continues executing even if typing indicator fails
- All existing tests pass (`make test`)
- Lint passes (`make lint`)

**Manual verification (if needed):**

To manually verify this feature:

1. Start TeleClaude with Telegram or Discord adapter enabled
2. Create a new session via the UI
3. Send a message to the session
4. Observe the "typing..." indicator appear in the Telegram topic or Discord thread within ~200ms
5. The indicator should disappear when the AI response arrives (auto-cleared by the platform)
