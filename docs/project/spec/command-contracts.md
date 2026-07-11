---
description: 'Command contract highlights for session creation, messaging, agent control, and subscription management.'
visibility: 'public'
---

# Command Contracts — Spec

## What it is

- Command contract highlights for session creation, messaging, agent control, and subscription management.

- Commands require explicit session identifiers and payloads.
- Command intent must be explicit and stable across interfaces.
- Enumerated intent values are treated as strict contracts.

- Enumerated intent fields must match the declared command contract.

- Commands are rejected when the target session is missing or closed, except where the spec marks the command as idempotent (see `unsubscribe_session`).

- Subscription state semantics for caller-target pairs are defined in `project/spec/session-subscriptions`. Verbs in this spec mutate that state — refer to that spec for the canonical state model.

## Canonical fields

- `command`: command name.
- `session_id`: target session UUID (required for send / end / unsubscribe).
- `payload`: command-specific data (message, agent, computer, etc.).
- `request_id`: unique correlation id for transport requests.
- `source`: originating adapter/client.

## Allowed values

<!-- planned-change:detect-stalled-agent-startup -->

- `command`: `start_session`, `send_message`, `end_session`, `run_agent_command`, `get_session_data`, `unsubscribe_session`.

<!-- change:detect-stalled-agent-startup -->

- `command`: `start_session`, `send_message`, `end_session`, `run_agent_command`, `get_session_data`, `unsubscribe_session`, `watch_session`.

<!-- /planned-change:detect-stalled-agent-startup -->

- `payload.intent`: `user_message`, `system_command`, `agent_control` (where applicable).
- CLI mapping: `get_session_data` backs `telec sessions tail`; `unsubscribe_session` backs `telec sessions unsubscribe` in user-facing workflows.

<!-- planned:detect-stalled-agent-startup -->

### `watch_session`

One-shot wake timer: arms (or replaces) the caller's durable session watch on the target; on firing, one wake notification with a factual status snapshot is delivered to the caller's host pane and the watch removes itself.

- Endpoint: `POST /sessions/{session_id}/watch`
- Identity: requires `X-Caller-Session-Id` (caller identity)
- Payload: `{ "in_seconds": <int> }` to arm; `{ "cancel": true }` to cancel without firing
- Validation: `in_seconds` is a typed positive bounded duration (1 ≤ in_seconds ≤ 86400); out-of-bounds values are rejected at the API boundary, and by the CLI before the request is sent
- Idempotent on cancel: empty state returns `success` with `watch_removed: false`
- CLI mapping: backs `telec sessions watch <session_id> [--in <seconds>] [--cancel]`
- `unsubscribe_session` additionally clears the pair's watch state (umbrella semantics)

<!-- /planned:detect-stalled-agent-startup -->

### `unsubscribe_session`

Umbrella verb: removes any listener and severs any active direct link the caller holds with the target.

- Endpoint: `POST /sessions/{session_id}/unsubscribe`
- Identity: requires `X-Caller-Session-Id` (caller identity)
- Idempotent: empty state returns `success` (not error)
- Response payload:
  ```json
  { "status":            "success",
    "listener_removed":  true | false,
    "link_closed":       true | false,
    "link_id":           "<uuid>" | null }
  ```

## Known caveats

- Transport layer may wrap commands in request/response envelopes.
- Missing or invalid `session_id` leads to immediate rejection (except for idempotent commands, which return success with all action flags false).
- `unsubscribe_session` and `send_message --close-link` overlap on the link axis. `unsubscribe_session` is the umbrella verb (both axes); `--close-link` only severs the link, leaving listener state intact.
- Direct-link creation (via `send_message --direct` or `start_session --direct`) must not mutate listener rows. Suppression of listener notifications while a link is active is enforced at delivery time, not by record mutation.
