# Deferrals: default-agent-resolution

## Deferred Items

1. `teleclaude/adapters/telegram/callback_handlers.py:465`
- Deferral: explicit user-selection callback map still contains `agent claude|gemini|codex` payloads.
- Reason: these are explicit user choices, not default-resolution paths; changing callback payload shape risks breaking existing buttons.
- Follow-up: dedicated callback payload migration/compatibility task.

2. Transcript parser fallbacks
- Files:
  - `teleclaude/api_server.py` parser-selection fallback when `session.active_agent` is unknown
  - `teleclaude/api/streaming.py` `_get_agent_name()` fallback
- Deferral: retain parser fallback behavior for unknown/legacy transcripts.
- Reason: this is transcript-format selection, not default launch resolution; fail-fast behavior here could break transcript rendering.
- Follow-up: separate parser-fallback policy decision and migration.

## Resolution (2026-03-03)

1. `teleclaude/adapters/telegram/callback_handlers.py:465`
- Suggested outcome: `NEW_TODO`
- Created: `todos/telegram-callback-payload-migration/`
- Status: Processed

2. Transcript parser fallbacks
- Suggested outcome: `NEW_TODO`
- Created: `todos/transcript-parser-fallback-policy/`
- Status: Processed
