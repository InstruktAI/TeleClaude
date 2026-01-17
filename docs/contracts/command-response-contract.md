# Command Response Contract

## Response Envelope

Commands processed via the API or Durable Outbox return a standard envelope:
- `status`: "success" or "error"
- `data`: Partial result or success payload
- `error`: Error message (if status is error)
- `code`: Machine-readable error code (optional)

## Partial Results

Hybrid commands (like session creation) return identifiers immediately in the `data` field:
- `session_id`
- `tmux_session_name`

These identifiers do not imply completion of background initialization (like agent startup), which is signaled via separate events.

## Async Completion

For async commands, "success" in the immediate response means the command was successfully *validated and queued* for execution. Final completion is signaled via domain events (`session_updated`, `agent_event`, etc.) delivered via WebSocket or transport streams.
