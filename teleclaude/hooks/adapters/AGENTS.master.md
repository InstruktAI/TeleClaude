# Hook Adapters

@docs/third-party/claude-code/hooks.md
@docs/third-party/gemini-cli/hooks.md
@docs/third-party/codex-cli/hooks.md

## Internal typed payloads

TeleClaude uses typed internal payload models (see `teleclaude/core/events.py`):

- `AgentSessionStartPayload`
- `AgentStopPayload`
- `AgentNotificationPayload`
- `AgentSessionEndPayload` (reserved)

These are constructed in `teleclaude/core/adapter_client.py`, frozen (immutable),
and enforced via direct field access (no `.get` fallbacks for required fields).

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

## Summary generation

Adapters never mutate payloads. The daemon generates summaries on `stop` events by running
summarization against the transcript markdown produced by
`teleclaude/utils/transcript.py` (see `parse_session_transcript(...)`).
