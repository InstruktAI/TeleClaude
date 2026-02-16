# Output Origin Routing — Requirements

## Problem

`send_output_update` in `adapter_client.py` broadcasts output to ALL registered UI adapters instead of routing to the adapter that originated the user input. This causes cross-adapter output leak: when a user sends a message via Discord, the AI output also appears on Telegram (and vice versa).

## Success Criteria

1. Output updates are delivered only to the originating UI adapter (the one identified by `session.last_input_origin`).
2. When `last_input_origin` is missing or non-UI (api, hook, mcp), output falls back to broadcasting to all UI adapters (preserving current behavior for programmatic origins).
3. No observer broadcast for output updates — output is a streaming edit-in-place operation, not a notification. Observer mirroring of output is a separate feature (`help-desk-control-room`).
4. Existing `_route_to_ui` infrastructure is reused; no new routing primitives needed.
5. All other methods (`send_message`, `send_threaded_output`, session feedback) continue working unchanged.

## Scope

### In Scope

- Modify `send_output_update` in `adapter_client.py` to route through `_route_to_ui` with `broadcast=False`.
- Verify that `_route_to_ui` with `broadcast=False` delivers only to origin adapter and skips observer fan-out.

### Out of Scope

- Admin supergroup mirroring of output (that's `help-desk-control-room`).
- Changes to `_route_to_ui`, `_origin_ui_adapter`, or `_broadcast_to_observers`.
- Changes to adapter-level `send_output_update` implementations (they already use per-adapter thread metadata).
- New fields or data model changes.

## Verification

1. Start a session via Discord, verify output appears only in Discord (not Telegram).
2. Start a session via Telegram, verify output appears only in Telegram (not Discord).
3. Start a session via API/MCP (no `last_input_origin`), verify output broadcasts to all UI adapters (fallback).
4. Verify `send_message` and other routed methods continue to work with observer broadcast.
