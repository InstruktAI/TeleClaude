# Output Origin Routing — Review Findings

## Review Round 1

### Scope

Single file changed: `teleclaude/core/adapter_client.py` — `send_output_update` method.

### Analysis

The change replaces a bespoke broadcast loop (manual `asyncio.gather` over all UI adapters) with a single `_route_to_ui(broadcast=False)` call. This is the exact pattern used by `send_threaded_output` (line 413-420), making the routing behavior consistent across all output delivery methods.

**Behavioral correctness:**

- **Origin-present sessions** (e.g., `last_input_origin=telegram`): `_origin_ui_adapter` resolves the adapter, `_route_to_ui` routes via `_run_ui_lane`, and `broadcast=False` skips `_broadcast_to_observers`. Output goes only to the originating adapter.
- **No-origin sessions** (API/MCP/hook or missing): `_origin_ui_adapter` returns `None`, `_route_to_ui` falls back to `_broadcast_to_ui_adapters`, preserving the existing broadcast behavior.
- **No observer broadcast**: `broadcast=False` explicitly prevents `_broadcast_to_observers` from running.

**Return type handling:** `str(result) if result else None` matches `send_threaded_output` and `send_message`. The `_route_to_ui` method returns the first truthy result or `None`, so this conversion is safe and consistent.

**Dead code removal:** The removed code (manual broadcast loop, per-adapter error logging, `make_task` factory, "NO ADAPTERS SUCCEEDED" logging) is fully superseded by `_route_to_ui` and `_run_ui_lane` infrastructure, which have their own logging and error handling.

**Docstring:** Accurately reflects origin-routed delivery, fallback behavior, and no-observer semantics.

**Test coverage:** Existing tests exercise both paths — origin-routed (telegram origin) and broadcast fallback (API origin). Recovery tests (missing thread, topic deleted, missing metadata) continue to pass through the new routing.

### Findings

No findings.

### Verdict

**APPROVE**

The change is minimal, correct, and follows an established pattern. All requirements are satisfied, the implementation plan is fully executed, and build gates are complete.
