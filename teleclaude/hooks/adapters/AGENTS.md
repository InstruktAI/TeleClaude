# Hook Adapters

---

# Claude Code Hooks

## Overview

Claude Code hooks run shell commands at lifecycle events. Hooks are configured in settings
files and receive JSON input describing the event.

## Configuration locations

- `~/.claude/settings.json`
- `.claude/settings.json`
- `.claude/settings.local.json`

Managed settings can be enforced by policy files.

## Hook events (documented)

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `PostToolUseFailure`
- `SubagentStart`
- `SubagentStop`
- `Stop`
- `PreCompact`
- `SessionEnd`
- `Notification`

## Sources

- https://docs.claude.com/en/docs/claude-code/hooks

---

# Gemini CLI Hooks

## Overview

Gemini CLI hooks run local commands at lifecycle events. Hooks are configured in settings
and receive JSON payloads describing the event.

## Note on hooks.enabled warning

Gemini CLI may emit a validation warning when `"hooks.enabled": true` is present in
`~/.gemini/settings.json` (e.g., “Expected array, received boolean”). In practice,
the runtime still honors `hooks.enabled` and hooks fire correctly. This appears to be
an upstream schema/validation mismatch; keep `hooks.enabled` set to true and ignore
the warning unless/until Gemini fixes the validator.

## Sources

- https://geminicli.com/docs/hooks
- https://geminicli.com/docs/hooks/reference

---

# Codex CLI Hooks

## Status

The official Codex CLI documentation does not describe a hooks system. The configuration and
CLI reference pages do not define hook events or hook configuration.

## Sources

- https://developers.openai.com/docs/codex/config-reference
- https://developers.openai.com/docs/codex/cli/reference


## Internal typed payloads

TeleClaude uses typed internal payload models (see `teleclaude/core/events.py`):

- `AgentSessionStartPayload`
- `AgentStopPayload`
- `AgentNotificationPayload`
- `AgentSessionEndPayload` (reserved)

These are constructed in `teleclaude/core/adapter_client.py` and enforced via
direct field access (no `.get` fallbacks for required fields).

The hook receiver writes events to the `hook_outbox` database table with the
following internal shape:

```
{
  "session_id": "<teleclaude_session_id>",
  "event_type": "session_start|stop|session_end|notification",
  "data": { ...normalized hook payload... }
}
```

The daemon's `_hook_outbox_worker` processes queued events and dispatches them.

## Summary enrichment

Adapters never enrich payloads. The daemon enriches `stop` events by running
summarization against the transcript markdown produced by
`teleclaude/utils/transcript.py` (see `parse_session_transcript(...)`).
