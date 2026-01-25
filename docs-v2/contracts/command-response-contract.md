# Response Contract

## Response Envelope

All command responses return immediately and include:

- `request_id`
- `expected_events` (ordered)
- `event_timeouts_ms` (per event)
- `partial_result` (if available)

## Per‑Event Timeouts

- Each expected event has its own timeout window.
- Missing an expected event within its window is a failure.
- Failure is reported via `command_failed` event with error details.

## Partial Results

Commands may return identifiers immediately (e.g., `session_id`, `tmux_session_name`).
These do not imply completion of later events.

## Naming

`request_id` is the public name. Internally this maps to the command pipeline’s `command_id`.
