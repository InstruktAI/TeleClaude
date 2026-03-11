# Input: session-async-control-lane

Split from parent `session-runtime-overhaul` — Phase 5 (Ephemeral Control Lane).

Depends on: `session-adaptive-runtime` (needs SessionRuntime actor for the control_queue field).

## What

1. **Per-session control queue** — Create `teleclaude/core/session_control_queue.py`
   with `SessionControlQueue` (asyncio.Queue wrapper), `ControlAction`, and
   `ControlReceipt`. Internal worker drains queue sequentially, handles tmux timing.
   Lifecycle: created with runtime, drained on cleanup, NOT persisted.

2. **Route compound controls** — Modify `escape_command` handler's compound path
   (with args, `command_handlers.py:1265-1320`) to enqueue through
   `SessionControlQueue` instead of blocking inline. Plain escape (no args) remains
   direct. All single-key controls remain direct. Public `/sessions/{id}/keys` API
   unchanged. Durable `/message` delivery via inbound queue unchanged.

## Why

The 1.0s delay in `tmux_bridge._send_keys_tmux()` blocks the calling coroutine inline
for compound control paths (escape with args). The queue decouples callers from tmux
timing. Only compound paths with inline delays benefit; simple keys are
latency-sensitive and gain nothing from queue overhead.

## Success Criteria

- SessionControlQueue exists with enqueue/worker/cleanup lifecycle
- Enqueue returns ControlReceipt immediately
- Worker processes items sequentially with tmux timing
- Queue is ephemeral: not persisted, drained on cleanup
- Compound escape+text enqueues instead of blocking
- Plain escape (no args) remains direct
- Simple key controls do NOT go through queue
- Public key API unchanged
- Durable message delivery unchanged
- All tests pass
