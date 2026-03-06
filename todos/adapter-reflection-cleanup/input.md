# adapter-reflection-cleanup — Input

Consolidates `adapter-boundary-cleanup` and `reflection-routing-ownership`. Both describe
violations of the same architectural intent: core is a dumb broadcast pipe, adapters own
everything else.

## Architecture (source of truth)

Three docs define the target state:

- `project/spec/session-output-routing` — Reflection lane: "broadcast to all adapters
  unconditionally. Each adapter owns its local routing decision. Core attaches source
  metadata but never excludes adapters based on source."
- `project/design/architecture/adapter-client` — Invariant: "Reflection Broadcast Without
  Exclusion." Flow §4: parallel delivery (tmux inject ‖ broadcast ‖ break_threaded_turn).
- `project/design/architecture/ui-adapter` — Invariant: "Reflection Routing Ownership."
  Flow §10: adapter-local decision tree. Boundary: "No core-level routing assumptions."
- `project/policy/adapter-boundaries` — "Core logic never imports adapter modules or
  vendor SDKs."

## Violations in current code

### V1: Core excludes source adapter from reflections

`_fanout_excluding()` (adapter_client.py:221-264) skips the source adapter. Called from
`broadcast_user_input` (line 670) with `exclude=source_adapter` and `_broadcast_action`
(line 914). Core is making a routing decision that belongs to adapters.

### V2: Core constructs per-adapter presentation

`broadcast_user_input` (lines 624-657) contains:
- `render_reflection_text()` — formats text differently per adapter
- `adapter.ADAPTER_KEY == InputOrigin.TELEGRAM.value` — core checking adapter type
- `reflection_header`, `display_origin_label`, `default_actor` — all presentation logic

Core should pass raw text + metadata. Each adapter formats locally.

### V3: Core reaches into private adapter state

`break_threaded_turn` (line 443-453) calls `getattr(adapter, "_qos_scheduler", None)`
and directly invokes `scheduler.drop_pending()`. Also calls `_clear_output_message_id`
and `_set_char_offset` (lines 456-457) — private methods.

`move_badge_to_bottom` (line 430) calls `adapter._move_badge_to_bottom()` — private.

### V4: Missing metadata field

`MessageMetadata` has `reflection_actor_id/name/avatar_url` but no `reflection_origin`.
Without it, adapters cannot inspect where a reflection came from to make local decisions.

### V5: deliver_inbound is sequential

Architecture flow §4 shows parallel: `gather(tmux_inject, broadcast, break_threaded_turn)`.
Current code (command_handlers.py:1022-1063) runs them sequentially.

### V6: Adapters have no local reflection decision logic

No adapter inspects reflection origin to decide suppress/render/route. Currently core
handles suppression via `_fanout_excluding` — when that goes away, adapters need their
own logic. Discord has webhook rendering for cross-source reflections but no own-user
suppression. Telegram has nothing.

## What's NOT a violation

- **Two broadcast paths** (deliver_inbound + handle_user_prompt_submit): Both needed
  for different input sources. Echo guard bridges them.
- **Echo heuristic** (20s + 200-char match): Working. Nice-to-have improvement, not broken.
- **Execution order** (break_threaded_turn before echo guard): Fixed by per-adapter
  metadata (commit 841fbdae0). No longer causes duplicate output.

## Files to change

1. `teleclaude/core/adapter_client.py` — Strip `_fanout_excluding` from reflection path,
   remove presentation logic from `broadcast_user_input`, expose public adapter methods
2. `teleclaude/core/models.py` — Add `reflection_origin` to `MessageMetadata`
3. `teleclaude/adapters/ui_adapter.py` — Add `drop_pending_output()` base method,
   make `move_badge_to_bottom()` public, add `clear_turn_state()` public method
4. `teleclaude/adapters/telegram_adapter.py` — Implement adapter-local reflection
   handling: inspect origin, suppress own-user, format with header/separator for others
5. `teleclaude/adapters/discord_adapter.py` — Add origin guard for own-user suppression;
   webhook rendering for others already works
6. `teleclaude/core/command_handlers.py` — Parallelize deliver_inbound per architecture
7. Tests — Move reflection formatting tests from core to adapter-level tests

## Retires

- `adapter-boundary-cleanup` (presentation violations V2, V3)
- `reflection-routing-ownership` (routing violations V1, V4, V5, V6)
