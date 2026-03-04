# Input: telegram-callback-payload-migration

## Context

`default-agent-resolution` intentionally deferred migration of Telegram explicit user-selection callback payloads (`agent claude|gemini|codex`) in:

- `teleclaude/adapters/telegram/callback_handlers.py` (explicit selection callback map)

These callbacks are user-choice payloads, not default-agent resolution paths, and were left unchanged to avoid breaking existing buttons.

## Requested Outcome

Implement a dedicated callback payload migration/compatibility strategy for explicit user-selection callbacks that:

1. Preserves compatibility for existing buttons/payloads.
2. Moves callback payloads to the new canonical agent identifiers.
3. Includes tests for both legacy and new payload formats.
4. Defines migration and deprecation behavior.

## Notes

- Keep this scoped to explicit callback payload handling.
- Do not regress default-agent resolution behavior completed in `default-agent-resolution`.
