# Output Origin Routing — Input

## Problem

When a user sends a message via Discord, output updates are also delivered to Telegram. The user expects responses only on the adapter and thread they're currently talking in. This is a cross-adapter leak.

## Root Cause

`send_output_update` in `adapter_client.py` (line 525) broadcasts to ALL registered UI adapters:

```python
# Broadcast to ALL UI adapters (per-adapter lanes)
tasks = [
    (adapter_type, self._run_ui_lane(session, adapter_type, adapter, make_task))
    for adapter_type, adapter in self.adapters.items()
    if isinstance(adapter, UiAdapter)
]
```

This bypasses the origin-aware routing that other methods use correctly.

## Routing Data Already Exists

The full return address is already tracked per session — no new fields needed:

| Field                                            | What it identifies                        | Set when                 |
| ------------------------------------------------ | ----------------------------------------- | ------------------------ |
| `session.last_input_origin`                      | Which adapter (`"discord"`, `"telegram"`) | Every inbound message    |
| `session.adapter_metadata.ui.telegram.topic_id`  | Telegram supergroup thread                | Telegram message handler |
| `session.adapter_metadata.ui.discord.thread_id`  | Discord forum thread                      | Discord message handler  |
| `session.adapter_metadata.ui.discord.channel_id` | Discord channel                           | Discord message handler  |

The routing tuple `(adapter, thread_id)` is already fully populated. Each adapter's `send_output_update` implementation already reads its own thread/topic from `session.adapter_metadata` to target the right thread. The only problem is the dispatch layer ignoring this and broadcasting to all adapters.

## Correctly Routed Methods (Same File)

| Method                             | Uses origin?                                   | Broadcast?          | Pattern |
| ---------------------------------- | ---------------------------------------------- | ------------------- | ------- |
| `send_message` (line 307)          | Yes, via `_route_to_ui`                        | To observers only   | Correct |
| `_handle_session_updated` feedback | Yes, checks `last_input_origin == ADAPTER_KEY` | No                  | Correct |
| `send_output_update` (line 525)    | **No**                                         | **All UI adapters** | **BUG** |

## Existing Infrastructure

The fix should use what already exists:

- `_origin_ui_adapter(session)` (line 81) — resolves origin adapter from `session.last_input_origin`
- `_route_to_ui(session, method, broadcast=True)` (line 249) — routes to origin, then optionally broadcasts to observers
- `_broadcast_to_observers(session, method, make_task)` (line 233) — best-effort observer fan-out

## Fix

Route `send_output_update` through `_route_to_ui()` instead of its own all-adapter broadcast loop. The origin adapter receives the update and uses its stored thread/topic metadata to target the exact thread. No observer broadcast needed for output updates — admin channel mirroring is a separate feature (`help-desk-control-room`).

## Key Code References

- **Bug site:** `adapter_client.py` `send_output_update` line 525
- **Origin resolver:** `adapter_client.py` `_origin_ui_adapter` line 81
- **Correct routing:** `adapter_client.py` `_route_to_ui` line 249
- **Origin field:** `session.last_input_origin` (set by each adapter on inbound messages)
- **Thread metadata:** `session.adapter_metadata.ui.discord.thread_id`, `.telegram.topic_id`
