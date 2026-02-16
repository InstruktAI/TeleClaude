# Output Origin Routing — Implementation Plan

## Overview

Replace the all-adapter broadcast loop in `send_output_update` with a call to `_route_to_ui(broadcast=False)`. This is the same pattern used by `send_threaded_output`.

## Changes

### 1. `adapter_client.py` — `send_output_update` (line 525 region)

**Remove** the manual broadcast loop (lines ~525-573):

```python
# Broadcast to ALL UI adapters (per-adapter lanes)
tasks = [
    (adapter_type, self._run_ui_lane(session, adapter_type, adapter, make_task))
    for adapter_type, adapter in self.adapters.items()
    if isinstance(adapter, UiAdapter)
]
# ... result gathering, logging, error handling ...
return first_success
```

**Replace with** a single `_route_to_ui` call:

```python
result = await self._route_to_ui(
    session,
    "send_output_update",
    output,
    started_at,
    last_output_changed_at,
    is_final,
    exit_code,
    render_markdown,
    broadcast=False,
)
return str(result) if result else None
```

This delegates origin resolution, lane execution, and the no-origin fallback entirely to `_route_to_ui`, which already handles all cases:

- **Origin present**: routes to origin adapter only (no observer broadcast because `broadcast=False`).
- **No origin**: falls back to broadcasting to all UI adapters via `_broadcast_to_ui_adapters` (existing behavior in `_route_to_ui` line 280-288).

### 2. Update docstring

Update the `send_output_update` docstring from "Sends filtered output to all registered UiAdapters" to reflect origin-routed delivery.

### 3. Remove dead logging

The `[OUTPUT_ROUTE]` broadcast logging on lines 532-536 becomes unnecessary since `_route_to_ui` has its own logging. The early-return threaded output check (lines 503-512) and `make_task` factory (lines 514-523) remain unchanged.

## Files Changed

| File                                | Change                                                      |
| ----------------------------------- | ----------------------------------------------------------- |
| `teleclaude/core/adapter_client.py` | Replace broadcast loop with `_route_to_ui(broadcast=False)` |

## Build Sequence

1. [x] Edit `send_output_update` in `adapter_client.py`.
2. [x] Lint/type check.
3. Manual verification: Discord-only and Telegram-only session tests.

## Risk Assessment

**Low risk.** The fix replaces a bespoke broadcast loop with the same routing infrastructure that `send_message` and `send_threaded_output` already use successfully. The `_route_to_ui` no-origin fallback preserves broadcast for API/MCP-originated sessions. No data model changes, no new code paths.
